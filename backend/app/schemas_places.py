from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import UserBrief
from .schemas_titles import Comment, Desc, Name

Category = Literal["restaurant", "cafe", "bar", "park", "museum", "shop", "other"]
Lat = Annotated[float, Field(ge=-90, le=90)]
Lng = Annotated[float, Field(ge=-180, le=180)]
Price = Annotated[Decimal, Field(ge=0, le=10_000_000, decimal_places=2)]


# ---------- input ----------
class PlaceCreate(BaseModel):
    name: Name
    category: Category = "other"
    description: Desc = ""
    lat: Lat
    lng: Lng


class PlaceUpdate(BaseModel):  # перенос метки = PATCH lat/lng
    name: Name | None = None
    category: Category | None = None
    description: Desc | None = None
    lat: Lat | None = None
    lng: Lng | None = None


class MenuItemIn(BaseModel):
    name: Name
    price: Price | None = None
    description: Desc = ""


class MenuItemUpdate(BaseModel):  # null очищает только price
    name: Name | None = None
    price: Price | None = None
    description: Desc | None = None


class PlaceReviewIn(BaseModel):
    rating: int = Field(ge=0, le=10)
    comment: Comment = ""


# ---------- output ----------
class PlaceMarker(BaseModel):
    """Всё, что нужно для метки и превью по клику: название + средний рейтинг."""
    id: int
    name: str
    category: str
    lat: float
    lng: float
    rating: float | None
    ratings_count: int


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price: float | None
    description: str


class PlaceReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rating: int
    comment: str
    created_at: datetime
    updated_at: datetime
    user: UserBrief


class PlaceDetail(PlaceMarker):
    description: str
    created_by: UserBrief | None
    created_at: datetime
    menu: list[MenuItemOut]  # имеет смысл для restaurant/cafe/bar
    reviews: list[PlaceReviewOut]
