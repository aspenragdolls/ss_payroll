"""Customer portal account auth (separate from business User sessions)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.customer import Customer
from app.models.customer_account import CustomerAccount
from app.models.user import User
from app.services.auth_service import hash_password, verify_password


def get_business_by_slug_or_id(db: Session, business_key: str) -> User | None:
    """Resolve business by numeric id or case-insensitive business_name slug."""
    key = (business_key or "").strip()
    if not key:
        return None
    if key.isdigit():
        return db.get(User, int(key))
    return db.scalar(
        select(User).where(func_lower_business_name(User.business_name) == key.lower())
    )


def func_lower_business_name(column):
    from sqlalchemy import func

    return func.lower(column)


def get_account_by_id(db: Session, account_id: int) -> CustomerAccount | None:
    return db.scalar(
        select(CustomerAccount)
        .where(CustomerAccount.id == account_id, CustomerAccount.is_active.is_(True))
        .options(selectinload(CustomerAccount.customer), selectinload(CustomerAccount.user))
    )


def get_account_by_email(
    db: Session, user_id: int, email: str
) -> CustomerAccount | None:
    return db.scalar(
        select(CustomerAccount).where(
            CustomerAccount.user_id == user_id,
            CustomerAccount.email == email.lower().strip(),
        )
    )


def find_or_create_customer(
    db: Session,
    user_id: int,
    *,
    name: str,
    email: str,
    phone: str | None,
    address: str | None,
    zip_code: str | None = None,
) -> Customer:
    email_norm = email.lower().strip()
    existing = db.scalar(
        select(Customer).where(
            Customer.user_id == user_id,
            Customer.email == email_norm,
        )
    )
    if existing:
        if phone and not existing.phone:
            existing.phone = phone
        if address and not existing.address:
            existing.address = address
        if zip_code and not existing.zip_code:
            existing.zip_code = zip_code
        db.commit()
        db.refresh(existing)
        return existing

    customer = Customer(
        user_id=user_id,
        name=name.strip(),
        email=email_norm,
        phone=(phone or "").strip() or None,
        address=(address or "").strip() or None,
        zip_code=(zip_code or "").strip() or None,
        status="lead",
        lead_source="online",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def register_customer_account(
    db: Session,
    business: User,
    *,
    name: str,
    email: str,
    password: str,
    phone: str | None = None,
    address: str | None = None,
    zip_code: str | None = None,
) -> CustomerAccount:
    email_norm = email.lower().strip()
    if get_account_by_email(db, business.id, email_norm):
        raise ValueError("An account with this email already exists.")

    customer = find_or_create_customer(
        db,
        business.id,
        name=name,
        email=email_norm,
        phone=phone,
        address=address,
        zip_code=zip_code,
    )
    existing_for_customer = db.scalar(
        select(CustomerAccount).where(CustomerAccount.customer_id == customer.id)
    )
    if existing_for_customer:
        raise ValueError("This customer already has a portal account.")

    account = CustomerAccount(
        user_id=business.id,
        customer_id=customer.id,
        email=email_norm,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return get_account_by_id(db, account.id)  # type: ignore[return-value]


def authenticate_customer_account(
    db: Session, business: User, email: str, password: str
) -> CustomerAccount | None:
    account = get_account_by_email(db, business.id, email)
    if not account or not account.is_active:
        return None
    if not verify_password(password, account.password_hash):
        return None
    return get_account_by_id(db, account.id)
