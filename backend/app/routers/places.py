import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import avg1, commit_unique
from ..db import get_db
from ..deps import get_current_user
from ..models import MenuItem, Place, PlaceReview, User
from ..schemas_places import (Category, MenuItemIn, MenuItemOut, MenuItemUpdate,
                              PlaceCreate, PlaceDetail, PlaceMarker, PlaceReviewIn,
                              PlaceReviewOut, PlaceUpdate)

router = APIRouter(prefix="/api", tags=["places"], dependencies=[Depends(get_current_user)])
log = logging.getLogger("app.places")
MENU_CATEGORIES = {"restaurant", "cafe", "bar"}
MAX_MENU_ITEMS = 200


def _rating_subq():
    return (select(PlaceReview.place_id.label("place_id"),
                   func.avg(PlaceReview.rating).label("rating"),
                   func.count().label("n"))
            .group_by(PlaceReview.place_id).subquery())


def _marker(p: Place, rating, n) -> PlaceMarker:
    return PlaceMarker(id=p.id, name=p.name, category=p.category, lat=p.lat, lng=p.lng,
                       rating=avg1(rating), ratings_count=n or 0)


def _place(db: Session, place_id: int) -> Place:
    p = db.get(Place, place_id)
    if not p:
        raise HTTPException(404, "Place not found")
    return p


def _owned(db: Session, place_id: int, user: User) -> Place:
    p = _place(db, place_id)
    if p.created_by != user.id:
        raise HTTPException(403, "Only the author can modify this place")
    return p


def _detail(db: Session, p: Place) -> PlaceDetail:
    rt = _rating_subq()
    rating, n = db.execute(select(rt.c.rating, rt.c.n).where(rt.c.place_id == p.id)).first() or (None, 0)
    return PlaceDetail(
        **_marker(p, rating, n).model_dump(), description=p.description,
        created_by=db.get(User, p.created_by) if p.created_by else None, created_at=p.created_at,
        menu=db.scalars(select(MenuItem).where(MenuItem.place_id == p.id).order_by(MenuItem.id)).all(),
        reviews=db.scalars(select(PlaceReview).where(PlaceReview.place_id == p.id)
                           .order_by(PlaceReview.updated_at.desc())).all())


# ---------------- places ----------------
@router.get("/places", response_model=list[PlaceMarker])
def list_places(category: Category | None = None,
                min_lat: float | None = Query(None, ge=-90, le=90), max_lat: float | None = Query(None, ge=-90, le=90),
                min_lng: float | None = Query(None, ge=-180, le=180), max_lng: float | None = Query(None, ge=-180, le=180),
                db: Session = Depends(get_db)):
    """Метки для карты (+ превью: название и средний рейтинг). Необязательный bbox — границы видимой области."""
    rt = _rating_subq()
    stmt = select(Place, rt.c.rating, rt.c.n).outerjoin(rt, rt.c.place_id == Place.id)
    if category:
        stmt = stmt.where(Place.category == category)
    for col, op, val in ((Place.lat, "ge", min_lat), (Place.lat, "le", max_lat),
                         (Place.lng, "ge", min_lng), (Place.lng, "le", max_lng)):
        if val is not None:
            stmt = stmt.where(getattr(col, f"__{op}__")(val))
    return [_marker(p, r, n) for p, r, n in db.execute(stmt.order_by(Place.id).limit(2000)).all()]


@router.post("/places", response_model=PlaceDetail, status_code=201)
def create_place(data: PlaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = Place(**data.model_dump(), created_by=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    log.info("place created id=%s by user_id=%s", p.id, user.id)
    return _detail(db, p)


@router.get("/places/{place_id}", response_model=PlaceDetail)
def get_place(place_id: int, db: Session = Depends(get_db)):
    return _detail(db, _place(db, place_id))


@router.patch("/places/{place_id}", response_model=PlaceDetail)
def update_place(place_id: int, data: PlaceUpdate, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    p = _owned(db, place_id, user)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:  # все поля места not null
            setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _detail(db, p)


@router.delete("/places/{place_id}", status_code=204)
def delete_place(place_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, place_id, user))  # меню и отзывы — каскадом на уровне БД
    db.commit()
    log.info("place deleted id=%s by user_id=%s", place_id, user.id)


# ---------------- menu ----------------
@router.post("/places/{place_id}/menu", response_model=MenuItemOut, status_code=201)
def add_menu_item(place_id: int, data: MenuItemIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = _owned(db, place_id, user)
    if p.category not in MENU_CATEGORIES:
        raise HTTPException(422, "Menu is only available for restaurant, cafe and bar")
    count = db.scalar(select(func.count()).select_from(MenuItem).where(MenuItem.place_id == p.id))
    if count >= MAX_MENU_ITEMS:
        raise HTTPException(409, f"At most {MAX_MENU_ITEMS} menu items per place")
    item = MenuItem(place_id=p.id, **data.model_dump())
    db.add(item)
    db.commit()
    return item


def _owned_item(db: Session, item_id: int, user: User) -> MenuItem:
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(404, "Menu item not found")
    _owned(db, item.place_id, user)
    return item


@router.patch("/menu/{item_id}", response_model=MenuItemOut)
def update_menu_item(item_id: int, data: MenuItemUpdate, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    item = _owned_item(db, item_id, user)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is None and k != "price":  # null допустим только для цены
            continue
        setattr(item, k, v)
    db.commit()
    return item


@router.delete("/menu/{item_id}", status_code=204)
def delete_menu_item(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned_item(db, item_id, user))
    db.commit()


# ---------------- reviews ----------------
@router.put("/places/{place_id}/review", response_model=PlaceReviewOut)
def put_review(place_id: int, data: PlaceReviewIn, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _place(db, place_id)
    rev = db.scalar(select(PlaceReview).where(PlaceReview.place_id == place_id, PlaceReview.user_id == user.id))
    if rev is None:
        rev = PlaceReview(place_id=place_id, user_id=user.id, rating=data.rating, comment=data.comment)
        db.add(rev)
    else:
        rev.rating, rev.comment = data.rating, data.comment
    commit_unique(db, "Concurrent update, please retry")
    db.refresh(rev)
    return rev


@router.delete("/places/{place_id}/review", status_code=204)
def delete_review(place_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rev = db.scalar(select(PlaceReview).where(PlaceReview.place_id == place_id, PlaceReview.user_id == user.id))
    if not rev:
        raise HTTPException(404, "Review not found")
    db.delete(rev)
    db.commit()
