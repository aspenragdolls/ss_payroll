"""Backfill Customer records from existing payroll jobs.

Groups jobs with the same location (same logic as export_customers_mymaps.py),
creates one Customer per group, and sets jobs.customer_id.

Idempotent: only processes jobs that do not already have a customer_id.

Usage (from the project root):
    .venv\\Scripts\\python.exe scripts\\backfill_customers.py
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.user import User  # noqa: E402

_EXPORT_PATH = ROOT / "scripts" / "export_customers_mymaps.py"
_spec = importlib.util.spec_from_file_location("export_customers_mymaps", _EXPORT_PATH)
assert _spec and _spec.loader
_export = importlib.util.module_from_spec(_spec)
sys.modules["export_customers_mymaps"] = _export
_spec.loader.exec_module(_export)

choose_name = _export.choose_name
city_by_street = _export.city_by_street
dedupe_keep_order = _export.dedupe_keep_order
display_address = _export.display_address
group_jobs = _export.group_jobs
is_name_echo = _export.is_name_echo
phones_in = _export.phones_in
service_notes = _export.service_notes


def _customer_fields(location, cities: dict) -> dict:
    jobs = sorted(location.jobs, key=lambda job: (job.job_date or date.min, job.id))
    names = [(job.customer_name or "") for job in jobs]
    dated = [(job.customer_name or "", job.job_date) for job in jobs]
    name, aliases = choose_name(names, dated)

    phone_list: list[str] = []
    note_list: list[str] = []
    for job in jobs:
        phone_list.extend(phones_in(job.service_description, job.source_text))
        note_list.extend(service_notes(job))
    phones = dedupe_keep_order(phone_list)
    notes = [
        note
        for note in dedupe_keep_order(note_list)
        if not is_name_echo(note, names)
    ]

    address = display_address(location, cities) or None
    zip_code = None
    if address:
        match = _export.ZIP_RE.search(address)
        if match:
            zip_code = match.group(1)

    return {
        "name": name,
        "address": address,
        "phone": phones[0] if phones else None,
        "notes": "; ".join(notes) if notes else None,
        "aliases": aliases or None,
        "status": "active",
        "zip_code": zip_code,
    }


def backfill_user(db, user_id: int) -> tuple[int, int]:
    """Create customers for unlinked jobs. Returns (customers_created, jobs_linked)."""
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.customer_id.is_(None))
            .order_by(Job.job_date, Job.id)
        )
    )
    if not jobs:
        return 0, 0

    locations = group_jobs(jobs)
    cities = city_by_street(locations)
    created = 0
    linked = 0

    for location in locations:
        fields = _customer_fields(location, cities)
        customer = Customer(user_id=user_id, is_active=True, **fields)
        db.add(customer)
        db.flush()
        for job in location.jobs:
            job.customer_id = customer.id
            linked += 1
        created += 1

    db.commit()
    return created, linked


def main() -> None:
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).order_by(User.id)))
        if not users:
            print("No users found.")
            return

        total_created = 0
        total_linked = 0
        for user in users:
            created, linked = backfill_user(db, user.id)
            total_created += created
            total_linked += linked
            print(
                f"User {user.id} ({user.business_name}): "
                f"{created} customers created, {linked} jobs linked"
            )

        print(f"Done. {total_created} customers, {total_linked} jobs linked.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
