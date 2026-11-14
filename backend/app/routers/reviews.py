from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Place, PlaceReview, Season, SeasonReview, Title, TitleReview, WatchStatus
from .users import _by_username

router = APIRouter(prefix="/api", tags=["reviews"], dependencies=[Depends(get_current_user)])


class ReviewItem(BaseModel):
    kind: Literal["movie", "series", "place"]  # series = оценка сезона
    review_id: int
    target_id: int                # id фильма/сериала или места
    title: str                    # название фильма/сериала или места
    season_id: int | None
    season_number: int | None
    status: WatchStatus | None    # у мест статуса нет
    rating: int | None
    comment: str
    updated_at: datetime


@router.get("/users/{username}/reviews", response_model=list[ReviewItem])
def user_reviews(username: str, kind: Literal["movie", "series", "place"] | None = None,
                 limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db)):
    """Все оценки пользователя одним списком, новые сверху. Три источника сливаются в Python:
    у человека их десятки или сотни, а UNION по разнотипным колонкам — лишний риск."""
    uid = _by_username(db, username).id
    n = offset + limit
    items: list[ReviewItem] = []

    if kind in (None, "movie"):
        rows = db.execute(
            select(TitleReview.id.label("review_id"), Title.id.label("target_id"), Title.title,
                   TitleReview.status, TitleReview.rating, TitleReview.comment, TitleReview.updated_at)
            .join(Title, Title.id == TitleReview.title_id).where(TitleReview.user_id == uid)
            .order_by(TitleReview.updated_at.desc(), TitleReview.id.desc()).limit(n)).all()
        items += [ReviewItem(kind="movie", season_id=None, season_number=None, **r._mapping) for r in rows]

    if kind in (None, "series"):
        rows = db.execute(
            select(SeasonReview.id.label("review_id"), Title.id.label("target_id"), Title.title,
                   Season.id.label("season_id"), Season.number.label("season_number"),
                   SeasonReview.status, SeasonReview.rating, SeasonReview.comment, SeasonReview.updated_at)
            .join(Season, Season.id == SeasonReview.season_id).join(Title, Title.id == Season.title_id)
            .where(SeasonReview.user_id == uid)
            .order_by(SeasonReview.updated_at.desc(), SeasonReview.id.desc()).limit(n)).all()
        items += [ReviewItem(kind="series", **r._mapping) for r in rows]

    if kind in (None, "place"):
        rows = db.execute(
            select(PlaceReview.id.label("review_id"), Place.id.label("target_id"), Place.name.label("title"),
                   PlaceReview.rating, PlaceReview.comment, PlaceReview.updated_at)
            .join(Place, Place.id == PlaceReview.place_id).where(PlaceReview.user_id == uid)
            .order_by(PlaceReview.updated_at.desc(), PlaceReview.id.desc()).limit(n)).all()
        items += [ReviewItem(kind="place", season_id=None, season_number=None, status=None, **r._mapping)
                  for r in rows]

    items.sort(key=lambda i: (i.updated_at, i.review_id), reverse=True)
    return items[offset:offset + limit]
