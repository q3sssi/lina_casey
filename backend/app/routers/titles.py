import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import Integer, cast, func, select, union_all
from sqlalchemy.orm import Session

from ..common import commit_unique
from ..db import get_db
from ..deps import get_current_user
from ..models import (Season, SeasonReview, Title, TitleKind, TitleReview,
                      TitleScreenshot, User, WatchStatus)
from ..schemas_titles import (ReviewIn, ReviewOut, ScreenshotOut, SeasonDetail,
                              SeasonIn, SeasonOut, SeasonUpdate, TitleCreate,
                              TitleDetail, TitleItem, TitleRef, TitleUpdate)
from ..storage import delete_file, save_image

router = APIRouter(prefix="/api", tags=["cinema"], dependencies=[Depends(get_current_user)])
log = logging.getLogger("app.cinema")
MAX_SCREENSHOTS = 12


def norm(s: str) -> str:
    """Нормализация для антидубликата: регистр, ё/е, лишние пробелы."""
    return " ".join(s.casefold().replace("ё", "е").split())


def _r(x) -> float | None:
    return None if x is None else round(float(x), 1)


def _rating_subq():
    """title_id -> (rating, n). Фильм: AVG оценок. Сериал: AVG по сезонам от AVG оценок каждого сезона
    (каждый сезон весит одинаково; сезоны без оценок не учитываются)."""
    movie = (select(TitleReview.title_id.label("title_id"),
                    func.avg(TitleReview.rating).label("rating"),
                    func.count(TitleReview.rating).label("n"))
             .group_by(TitleReview.title_id))
    per_season = (select(Season.title_id.label("title_id"),
                         func.avg(SeasonReview.rating).label("s_avg"),
                         func.count(SeasonReview.rating).label("s_n"))
                  .join(SeasonReview, SeasonReview.season_id == Season.id)
                  .group_by(Season.id, Season.title_id).subquery())
    series = (select(per_season.c.title_id, func.avg(per_season.c.s_avg),
                     cast(func.sum(per_season.c.s_n), Integer))
              .group_by(per_season.c.title_id))
    return union_all(movie, series).subquery()


def _title(db: Session, title_id: int) -> Title:
    t = db.get(Title, title_id)
    if not t:
        raise HTTPException(404, "Title not found")
    return t


def _owned(db: Session, title_id: int, user: User) -> Title:
    t = _title(db, title_id)
    if t.created_by != user.id:
        raise HTTPException(403, "Only the author can modify this title")
    return t


def _items(db: Session, user: User, rows) -> list[TitleItem]:
    ids = [t.id for t, _, _ in rows]
    seasons = dict(db.execute(select(Season.title_id, func.count())
                              .where(Season.title_id.in_(ids)).group_by(Season.title_id)).all())
    mine = dict(db.execute(select(TitleReview.title_id, TitleReview.status)
                           .where(TitleReview.user_id == user.id, TitleReview.title_id.in_(ids))).all())
    watched = dict(db.execute(select(Season.title_id, func.count())
                              .join(SeasonReview, SeasonReview.season_id == Season.id)
                              .where(SeasonReview.user_id == user.id,
                                     SeasonReview.status == WatchStatus.watched,
                                     Season.title_id.in_(ids))
                              .group_by(Season.title_id)).all())
    out = []
    for t, rating, n in rows:
        series = t.kind == TitleKind.series
        out.append(TitleItem(
            id=t.id, kind=t.kind, title=t.title, duration_min=t.duration_min,
            imdb_rating=_r(t.imdb_rating), local_rating=_r(rating), ratings_count=n or 0,
            seasons_count=seasons.get(t.id, 0) if series else None,
            my_status=None if series else mine.get(t.id),
            my_watched_seasons=watched.get(t.id, 0) if series else None))
    return out


def _season_out(s: Season, avg, n, my: SeasonReview | None) -> SeasonOut:
    return SeasonOut(id=s.id, number=s.number, name=s.name, episodes_count=s.episodes_count,
                     description=s.description, local_rating=_r(avg), ratings_count=n or 0,
                     my_status=my.status if my else None, my_rating=my.rating if my else None)


def _seasons(db: Session, user: User, title_id: int) -> list[SeasonOut]:
    rows = db.execute(select(Season, func.avg(SeasonReview.rating), func.count(SeasonReview.rating))
                      .outerjoin(SeasonReview, SeasonReview.season_id == Season.id)
                      .where(Season.title_id == title_id)
                      .group_by(Season.id).order_by(Season.number)).all()
    mine = {r.season_id: r for r in db.scalars(
        select(SeasonReview).where(SeasonReview.user_id == user.id,
                                   SeasonReview.season_id.in_([s.id for s, _, _ in rows])))}
    return [_season_out(s, avg, n, mine.get(s.id)) for s, avg, n in rows]


def _detail(db: Session, user: User, t: Title) -> TitleDetail:
    rt = _rating_subq()
    rating, n = db.execute(select(rt.c.rating, rt.c.n).where(rt.c.title_id == t.id)).first() or (None, 0)
    item = _items(db, user, [(t, rating, n)])[0]
    series = t.kind == TitleKind.series
    return TitleDetail(
        **item.model_dump(), description=t.description, trailer_url=t.trailer_url,
        created_by=db.get(User, t.created_by) if t.created_by else None, created_at=t.created_at,
        screenshots=db.scalars(select(TitleScreenshot).where(TitleScreenshot.title_id == t.id)
                               .order_by(TitleScreenshot.id)).all(),
        seasons=_seasons(db, user, t.id) if series else [],
        reviews=[] if series else db.scalars(select(TitleReview).where(TitleReview.title_id == t.id)
                                             .order_by(TitleReview.updated_at.desc())).all())


# ---------------- titles ----------------
@router.get("/titles", response_model=list[TitleItem])
def list_titles(kind: TitleKind | None = None, q: str = Query("", max_length=100),
                sort: Literal["new", "title", "rating", "imdb"] = "new",
                limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rt = _rating_subq()
    stmt = select(Title, rt.c.rating, rt.c.n).outerjoin(rt, rt.c.title_id == Title.id)
    if kind:
        stmt = stmt.where(Title.kind == kind)
    if q.strip():
        stmt = stmt.where(Title.title_norm.contains(norm(q), autoescape=True))
    order = {"new": [Title.id.desc()],
             "title": [Title.title_norm],
             "rating": [rt.c.rating.desc().nulls_last(), Title.id.desc()],
             "imdb": [Title.imdb_rating.desc().nulls_last(), Title.id.desc()]}[sort]
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return _items(db, user, rows)


@router.post("/titles", response_model=TitleDetail, status_code=201)
def create_title(data: TitleCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = Title(**data.model_dump(), title_norm=norm(data.title), created_by=user.id)
    db.add(t)
    commit_unique(db, f"A {data.kind.value} with this title already exists")
    db.refresh(t)
    log.info("title created id=%s kind=%s by user_id=%s", t.id, t.kind.value, user.id)
    return _detail(db, user, t)


@router.get("/titles/{title_id}", response_model=TitleDetail)
def get_title(title_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, user, _title(db, title_id))


@router.patch("/titles/{title_id}", response_model=TitleDetail)
def update_title(title_id: int, data: TitleUpdate, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    t = _owned(db, title_id, user)
    changes = data.model_dump(exclude_unset=True)
    for k in ("title", "description"):  # не nullable
        if changes.get(k, "") is None:
            del changes[k]
    if t.kind == TitleKind.movie and "duration_min" in changes and changes["duration_min"] is None:
        raise HTTPException(422, "duration_min is required for movies")
    for k, v in changes.items():
        setattr(t, k, v)
    if "title" in changes:
        t.title_norm = norm(t.title)
    commit_unique(db, f"A {t.kind.value} with this title already exists")
    db.refresh(t)
    return _detail(db, user, t)


@router.delete("/titles/{title_id}", status_code=204)
def delete_title(title_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _owned(db, title_id, user)
    paths = db.scalars(select(TitleScreenshot.path).where(TitleScreenshot.title_id == t.id)).all()
    db.delete(t)  # дочерние строки удаляются каскадом на уровне БД
    db.commit()
    for p in paths:
        delete_file(p)
    log.info("title deleted id=%s by user_id=%s", title_id, user.id)


# ---------------- screenshots ----------------
@router.post("/titles/{title_id}/screenshots", response_model=ScreenshotOut, status_code=201)
def add_screenshot(title_id: int, file: UploadFile, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    t = _owned(db, title_id, user)
    count = db.scalar(select(func.count()).select_from(TitleScreenshot).where(TitleScreenshot.title_id == t.id))
    if count >= MAX_SCREENSHOTS:
        raise HTTPException(409, f"At most {MAX_SCREENSHOTS} screenshots per title")
    shot = TitleScreenshot(title_id=t.id, path=save_image(file, "titles", 1280))
    db.add(shot)
    db.commit()
    return shot


@router.delete("/titles/{title_id}/screenshots/{shot_id}", status_code=204)
def delete_screenshot(title_id: int, shot_id: int, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _owned(db, title_id, user)
    shot = db.get(TitleScreenshot, shot_id)
    if not shot or shot.title_id != title_id:
        raise HTTPException(404, "Screenshot not found")
    path = shot.path
    db.delete(shot)
    db.commit()
    delete_file(path)


# ---------------- seasons ----------------
def _owned_season(db: Session, season_id: int, user: User) -> Season:
    s = db.get(Season, season_id)
    if not s:
        raise HTTPException(404, "Season not found")
    _owned(db, s.title_id, user)
    return s


@router.post("/titles/{title_id}/seasons", response_model=SeasonOut, status_code=201)
def add_season(title_id: int, data: SeasonIn, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    t = _owned(db, title_id, user)
    if t.kind != TitleKind.series:
        raise HTTPException(422, "Seasons can only be added to series")
    number = data.number or db.scalar(
        select(func.coalesce(func.max(Season.number), 0) + 1).where(Season.title_id == t.id))
    s = Season(title_id=t.id, number=number, **data.model_dump(exclude={"number"}))
    db.add(s)
    commit_unique(db, f"Season {number} already exists")
    return _season_out(s, None, 0, None)


@router.get("/seasons/{season_id}", response_model=SeasonDetail)
def get_season(season_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Season, season_id)
    if not s:
        raise HTTPException(404, "Season not found")
    avg, n = db.execute(select(func.avg(SeasonReview.rating), func.count(SeasonReview.rating))
                        .where(SeasonReview.season_id == s.id)).one()
    reviews = db.scalars(select(SeasonReview).where(SeasonReview.season_id == s.id)
                         .order_by(SeasonReview.updated_at.desc())).all()
    my = next((r for r in reviews if r.user_id == user.id), None)
    t = db.get(Title, s.title_id)
    return SeasonDetail(**_season_out(s, avg, n, my).model_dump(),
                        title=TitleRef(id=t.id, kind=t.kind, title=t.title), reviews=reviews)


@router.patch("/seasons/{season_id}", response_model=SeasonDetail)
def update_season(season_id: int, data: SeasonUpdate, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    s = _owned_season(db, season_id, user)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is None and k in ("number", "description"):  # не nullable
            continue
        setattr(s, k, v)
    commit_unique(db, "Season with this number already exists")
    return get_season(season_id, user, db)


@router.delete("/seasons/{season_id}", status_code=204)
def delete_season(season_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned_season(db, season_id, user))
    db.commit()


# ---------------- reviews (upsert/delete своей оценки) ----------------
def _upsert_review(db: Session, model, fk: str, fk_value: int, user: User, data: ReviewIn):
    rev = db.scalar(select(model).where(getattr(model, fk) == fk_value, model.user_id == user.id))
    if rev is None:
        rev = model(**{fk: fk_value}, user_id=user.id, status=data.status, rating=data.rating,
                    comment=data.comment)
        db.add(rev)
    else:
        rev.status, rev.rating, rev.comment = data.status, data.rating, data.comment
    commit_unique(db, "Concurrent update, please retry")
    db.refresh(rev)
    return rev


def _delete_review(db: Session, model, fk: str, fk_value: int, user: User) -> None:
    rev = db.scalar(select(model).where(getattr(model, fk) == fk_value, model.user_id == user.id))
    if not rev:
        raise HTTPException(404, "Review not found")
    db.delete(rev)
    db.commit()


@router.put("/titles/{title_id}/review", response_model=ReviewOut)
def put_movie_review(title_id: int, data: ReviewIn, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    t = _title(db, title_id)
    if t.kind != TitleKind.movie:
        raise HTTPException(422, "Series are reviewed per season")
    return _upsert_review(db, TitleReview, "title_id", t.id, user, data)


@router.delete("/titles/{title_id}/review", status_code=204)
def delete_movie_review(title_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _delete_review(db, TitleReview, "title_id", title_id, user)


@router.put("/seasons/{season_id}/review", response_model=ReviewOut)
def put_season_review(season_id: int, data: ReviewIn, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    if not db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    return _upsert_review(db, SeasonReview, "season_id", season_id, user, data)


@router.delete("/seasons/{season_id}/review", status_code=204)
def delete_season_review(season_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _delete_review(db, SeasonReview, "season_id", season_id, user)
