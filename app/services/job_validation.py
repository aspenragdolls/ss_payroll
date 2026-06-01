from app.services.openrouter_job_parser import safe_decimal
from app.services.schemas import DraftJob


def validate_draft_job(draft: DraftJob) -> tuple[DraftJob, list[str]]:
    flags: list[str] = list(draft.ambiguity_flags or [])

    if not draft.customer_name or not draft.customer_name.strip():
        flags.append("missing_customer_name")

    if not draft.address or not draft.address.strip():
        flags.append("missing_address")
    elif draft.confidence_address is not None and draft.confidence_address < 0.5:
        flags.append("uncertain_address")

    raw_price = draft.final_ticket_price
    if raw_price is not None and str(raw_price).strip().startswith("-"):
        flags.append("invalid_ticket_price")
        price = None
    else:
        price = safe_decimal(raw_price)
    if price is None and "invalid_ticket_price" not in flags:
        if raw_price is None or str(raw_price).strip() == "":
            flags.append("missing_ticket_price")
    elif price is not None and price <= 0:
        flags.append("invalid_ticket_price")

    if draft.job_date is None:
        flags.append("missing_job_date")

    if draft.confidence_price is not None and draft.confidence_price < 0.5:
        flags.append("uncertain_price")

    unique_flags = sorted(set(flags))
    draft.ambiguity_flags = unique_flags
    return draft, unique_flags


def draft_requires_review(flags: list[str]) -> bool:
    return True  # User review always mandatory before payroll calculation
