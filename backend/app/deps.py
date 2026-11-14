from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_token

COOKIE = "session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = decode_token(request.cookies.get(COOKIE, ""))
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
