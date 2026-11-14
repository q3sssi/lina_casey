from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def commit_unique(db: Session, conflict_msg: str) -> None:
    """commit(); нарушение уникальности -> 409."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, conflict_msg)


def avg1(x) -> float | None:
    return None if x is None else round(float(x), 1)
