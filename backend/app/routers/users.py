from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Post, User
from ..schemas import PostIn, PostOut, ProfileUpdate, UserOut
from ..storage import delete_file, save_image

# весь раздел — только для авторизованных
router = APIRouter(prefix="/api", tags=["users"], dependencies=[Depends(get_current_user)])


def _by_username(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username.lower()))
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(q: str = Query("", max_length=32), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.username).limit(50)
    if q:
        stmt = stmt.where(User.username.startswith(q.lower(), autoescape=True))
    return db.scalars(stmt).all()


@router.patch("/users/me", response_model=UserOut)
def update_profile(data: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.bio = data.bio
    db.commit()
    return user


@router.put("/users/me/avatar", response_model=UserOut)
def set_avatar(file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    old = user.avatar_path
    user.avatar_path = save_image(file, "avatars", 256, square=True)
    db.commit()
    delete_file(old)
    return user


@router.delete("/users/me/avatar", response_model=UserOut)
def remove_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    old = user.avatar_path
    user.avatar_path = None
    db.commit()
    delete_file(old)
    return user


@router.get("/users/{username}", response_model=UserOut)
def get_profile(username: str, db: Session = Depends(get_db)):
    return _by_username(db, username)


@router.get("/users/{username}/posts", response_model=list[PostOut])
def list_posts(username: str, before_id: int | None = None, limit: int = Query(20, ge=1, le=50),
               db: Session = Depends(get_db)):
    owner = _by_username(db, username)
    stmt = select(Post).where(Post.profile_id == owner.id).order_by(Post.id.desc()).limit(limit)
    if before_id:  # keyset-пагинация: стабильна при добавлении новых записей
        stmt = stmt.where(Post.id < before_id)
    return db.scalars(stmt).all()


@router.post("/users/{username}/posts", response_model=PostOut, status_code=201)
def create_post(username: str, data: PostIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owner = _by_username(db, username)
    post = Post(profile_id=owner.id, author_id=user.id, text=data.text)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if user.id not in (post.author_id, post.profile_id):  # автор или владелец стены
        raise HTTPException(403, "Forbidden")
    db.delete(post)
    db.commit()
