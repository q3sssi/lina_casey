from datetime import datetime
from typing import Annotated

from pydantic import (AfterValidator, BaseModel, ConfigDict, Field,
                      StringConstraints, model_validator)

from .models import TitleKind, WatchStatus
from .schemas import UserBrief


def _http(v: str) -> str:
    if not v.startswith(("http://", "https://")):  # режем javascript:, data: и т.п.
        raise ValueError("must be an http(s) URL")
    return v


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Desc = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(_http)]
Imdb = Annotated[float, Field(ge=0, le=10), AfterValidator(lambda v: round(v, 1))]
Count = Annotated[int, Field(gt=0, le=1000)]


# ---------- input ----------
class TitleCreate(BaseModel):
    kind: TitleKind
    title: Name
    duration_min: Count | None = None  # фильм: длительность; сериал: средняя серия
    description: Desc = ""
    imdb_rating: Imdb | None = None
    trailer_url: Url | None = None

    @model_validator(mode="after")
    def _movie_needs_duration(self):
        if self.kind == TitleKind.movie and self.duration_min is None:
            raise ValueError("duration_min is required for movies")
        return self


class TitleUpdate(BaseModel):  # kind менять нельзя; null очищает необязательные поля
    title: Name | None = None
    duration_min: Count | None = None
    description: Desc | None = None
    imdb_rating: Imdb | None = None
    trailer_url: Url | None = None


class SeasonIn(BaseModel):
    number: Count | None = None  # по умолчанию — следующий по порядку
    name: Name | None = None
    episodes_count: Count | None = None
    description: Desc = ""


class SeasonUpdate(BaseModel):
    number: Count | None = None
    name: Name | None = None
    episodes_count: Count | None = None
    description: Desc | None = None


class ReviewIn(BaseModel):
    status: WatchStatus
    rating: int | None = Field(None, ge=0, le=10)
    comment: Comment = ""

    @model_validator(mode="after")
    def _queued_has_no_rating(self):
        if self.status == WatchStatus.queued and self.rating is not None:
            raise ValueError("rating is not allowed for status 'queued'")
        return self


# ---------- output ----------
class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: WatchStatus
    rating: int | None
    comment: str
    created_at: datetime
    updated_at: datetime
    user: UserBrief


class ScreenshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str


class SeasonOut(BaseModel):
    id: int
    number: int
    name: str | None
    episodes_count: int | None
    description: str
    local_rating: float | None
    ratings_count: int
    my_status: WatchStatus | None
    my_rating: int | None


class TitleRef(BaseModel):
    id: int
    kind: TitleKind
    title: str


class SeasonDetail(SeasonOut):
    title: TitleRef
    reviews: list[ReviewOut]


class TitleItem(BaseModel):
    id: int
    kind: TitleKind
    title: str
    duration_min: int | None
    imdb_rating: float | None
    local_rating: float | None
    ratings_count: int
    seasons_count: int | None       # только сериалы
    my_status: WatchStatus | None   # только фильмы
    my_watched_seasons: int | None  # только сериалы


class TitleDetail(TitleItem):
    description: str
    trailer_url: str | None
    created_by: UserBrief | None
    created_at: datetime
    screenshots: list[ScreenshotOut]
    seasons: list[SeasonOut]        # только сериалы
    reviews: list[ReviewOut]        # только фильмы (у сериалов — в SeasonDetail)
