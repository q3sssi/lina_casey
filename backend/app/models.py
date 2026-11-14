import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (CheckConstraint, DateTime, Enum, Float, ForeignKey,
                        Numeric, SmallInteger, String, Text, UniqueConstraint,
                        func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class WatchStatus(str, enum.Enum):
    watched = "watched"
    queued = "queued"
    dropped = "dropped"


class TitleKind(str, enum.Enum):
    movie = "movie"
    series = "series"


WATCH_STATUS = Enum(WatchStatus, name="watch_status", metadata=Base.metadata)  # один тип на все таблицы отзывов


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


def _fk(table: str):
    return mapped_column(ForeignKey(f"{table}.id", ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_path: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _ts()

    @property
    def avatar_url(self) -> str | None:
        return f"/media/{self.avatar_path}" if self.avatar_path else None


class Post(Base):
    """Запись на «стене» профиля: profile_id — чья стена, author_id — кто написал."""
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = _fk("users")
    author_id: Mapped[int] = _fk("users")
    text: Mapped[str] = mapped_column(Text)
    author: Mapped["User"] = relationship(foreign_keys=[author_id], lazy="joined")
    created_at: Mapped[datetime] = _ts()


class Title(Base):
    """Фильм или сериал (общая вкладка «Кино»)."""
    __tablename__ = "titles"
    __table_args__ = (
        UniqueConstraint("kind", "title_norm"),  # «Шрек» ≠ «Шрек 2», но не два «Шрека» одного типа
        CheckConstraint("duration_min > 0", name="duration_positive"),
        CheckConstraint("imdb_rating BETWEEN 0 AND 10", name="imdb_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[TitleKind] = mapped_column(Enum(TitleKind, name="title_kind"))
    title: Mapped[str] = mapped_column(String(200))
    title_norm: Mapped[str] = mapped_column(String(200))
    duration_min: Mapped[int | None]  # фильм: длительность; сериал: средняя длина серии
    description: Mapped[str] = mapped_column(Text, default="")
    imdb_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    trailer_url: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class TitleScreenshot(Base):
    __tablename__ = "title_screenshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = _fk("titles")
    path: Mapped[str] = mapped_column(String(255))

    @property
    def url(self) -> str:
        return f"/media/{self.path}"


class _ReviewCols:
    status: Mapped[WatchStatus] = mapped_column(WATCH_STATUS)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())


class TitleReview(_ReviewCols, Base):
    """Оценка фильма. Для сериалов оценки ставятся на сезоны (SeasonReview)."""
    __tablename__ = "title_reviews"
    __table_args__ = (UniqueConstraint("title_id", "user_id"),
                      CheckConstraint("rating BETWEEN 0 AND 10", name="rating_range"))
    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = _fk("titles")
    user_id: Mapped[int] = _fk("users")
    user: Mapped["User"] = relationship(lazy="joined")


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("title_id", "number"),
                      CheckConstraint("number > 0", name="number_positive"),
                      CheckConstraint("episodes_count > 0", name="episodes_positive"))
    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = _fk("titles")
    number: Mapped[int]
    name: Mapped[str | None] = mapped_column(String(200))
    episodes_count: Mapped[int | None]
    description: Mapped[str] = mapped_column(Text, default="")


class SeasonReview(_ReviewCols, Base):
    __tablename__ = "season_reviews"
    __table_args__ = (UniqueConstraint("season_id", "user_id"),
                      CheckConstraint("rating BETWEEN 0 AND 10", name="rating_range"))
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = _fk("seasons")
    user_id: Mapped[int] = _fk("users")
    user: Mapped["User"] = relationship(lazy="joined")


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), default="other")  # restaurant|cafe|park|...
    description: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = _fk("places")
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    description: Mapped[str] = mapped_column(Text, default="")


class PlaceReview(Base):
    __tablename__ = "place_reviews"
    __table_args__ = (
        UniqueConstraint("place_id", "user_id"),
        CheckConstraint("rating BETWEEN 0 AND 10", name="rating_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = _fk("places")
    user_id: Mapped[int] = _fk("users")
    user: Mapped["User"] = relationship(lazy="joined")
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())
