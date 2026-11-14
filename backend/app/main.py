import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (регистрирует таблицы в metadata)
from .config import settings
from .db import Base, engine
from .routers import auth, places, reviews, titles, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # на финальном этапе заменим на Alembic
    os.makedirs(settings.upload_dir, exist_ok=True)
    yield


app = FastAPI(title="Hangout API", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(titles.router)
app.include_router(places.router)
app.include_router(reviews.router)

if settings.serve_media:  # dev: в проде /media отдаёт nginx
    os.makedirs(settings.upload_dir, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.upload_dir), name="media")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}
