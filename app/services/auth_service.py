import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    business_name: str,
    timezone: str = "America/New_York",
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        business_name=business_name.strip(),
        timezone=timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email.lower().strip())
    if not user or not verify_password(password, user.password_hash):
        return None
    return user
