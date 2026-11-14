import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import COOKIE, get_current_user
from ..models import User
from ..schemas import LoginIn, RegisterIn, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("app.auth")
# выравнивает время ответа для несуществующих логинов (защита от user enumeration)
DUMMY_HASH = hash_password("dummy-password")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _start_session(resp: Response, user_id: int) -> None:
    resp.set_cookie(
        COOKIE, create_token(user_id),
        max_age=settings.access_token_minutes * 60,
        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, request: Request, resp: Response, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled")
    user = User(username=data.username, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.warning("register conflict username=%s ip=%s", data.username, _ip(request))
        raise HTTPException(409, "Username already taken")
    db.refresh(user)
    _start_session(resp, user.id)
    log.info("register ok user_id=%s username=%s ip=%s", user.id, user.username, _ip(request))
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, request: Request, resp: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    ok = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok):
        log.warning("login failed username=%s ip=%s", data.username, _ip(request))
        raise HTTPException(401, "Invalid username or password")
    _start_session(resp, user.id)
    log.info("login ok user_id=%s ip=%s", user.id, _ip(request))
    return user


@router.post("/logout", status_code=204)
def logout(resp: Response):
    resp.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
