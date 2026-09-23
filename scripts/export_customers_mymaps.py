"""Export one Google My Maps row per customer location.

Customer info lives on payroll jobs (name, address, price, tips, and the
original calendar text). This groups repeat visits at the same place into a
single pin and writes a CSV My Maps can geocode.

Usage (from the project root):
    .venv\\Scripts\\python.exe scripts\\export_customers_mymaps.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.job import Job  # noqa: E402
from sqlalchemy import select  # noqa: E402

OUTPUT = ROOT / "customers-google-mymaps.csv"

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
HOUSE_RE = re.compile(r"^\d+")
SUFFIXES = {
    "street": "st",
    "avenue": "ave",
    "drive": "dr",
    "road": "rd",
    "lane": "ln",
    "circle": "cir",
    "court": "ct",
    "boulevard": "blvd",
    "place": "pl",
    "trail": "trl",
    "terrace": "ter",
}
STREET_SUFFIX_RE = re.compile(
    r"\b(st|ave|dr|rd|ln|cir|ct|blvd|pl|trl|ter)$"
)
UTAH_CITIES = (
    "Salt Lake City",
    "American Fork",
    "Pleasant Grove",
    "Saratoga Springs",
    "South Jordan",
    "Centerville",
    "Park City",
    "Midvale",
    "Provo",
    "Draper",
    "Sandy",
    "Orem",
)


@dataclass
class Location:
    jobs: list[Job] = field(default_factory=list)
    geocode_note: str = ""

    def raw_addresses(self) -> list[str]:
        return [((job.address or "").strip()) for job in self.jobs if (job.address or "").strip()]


def normalize_address(address: str) -> str:
    text = address.lower().replace(".", " ")
    text = re.sub(r",?\s*united states\s*$", "", text)
    text = ZIP_RE.sub(" ", text)
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for long, short in SUFFIXES.items():
        text = re.sub(rf"\b{long}\b", short, text)
    return re.sub(r"\s+", " ", text).strip()


def tidy_address(raw: str) -> str:
    """Turn stored address text into a single geocodable line."""
    text = re.sub(r"\s+", " ", raw).strip().rstrip(",")
    text = re.sub(r",?\s*United States\s*$", "", text, flags=re.I).strip().rstrip(",")

    patterns = [
        r"^(?P<street>.*?),\s*(?P<city>[^,]+?),\s*(?P<state>[A-Za-z]{2})(?:\s+(?P<zip>\d{5}))?$",
        r"^(?P<street>.*?),\s*(?P<city>[A-Za-z .]+?)\s+(?P<state>[A-Za-z]{2})(?:\s+(?P<zip>\d{5}))?$",
        r"^(?P<street>.*?)\s+(?P<city>Salt Lake City|Sandy|Midvale|Orem|Provo|Pleasant Grove|American Fork|South Jordan|Centerville|Saratoga Springs|Draper|Park City),?\s*(?P<state>[A-Za-z]{2})?(?:\s+(?P<zip>\d{5}))?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.I)
        if not match:
            continue
        street = match.group("street").strip(" ,")
        city = re.sub(r"\s+", " ", match.group("city")).strip(" ,")
        state = (match.group("state") or "").upper()
        zip_code = match.group("zip") or ""
        if not street or not city:
            continue
        tail = city
        if state:
            tail = f"{city}, {state}"
        if zip_code:
            tail = f"{tail} {zip_code}"
        return f"{street}, {tail}"
    return text


def has_state(address: str) -> bool:
    return bool(re.search(r"\b[A-Z]{2}\b", address.split(",")[-1] if "," in address else address))


def street_fingerprint(normalized: str) -> str:
    text = re.sub(r"^\d+\s+", "", normalized)
    text = re.sub(
        r"\b(salt lake city|sandy|midvale|orem|provo|pleasant grove|american fork|"
        r"south jordan|centerville|saratoga springs|draper|park city|utah|ut)\b",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = STREET_SUFFIX_RE.sub("", text).strip()
    return text


def phones_in(*texts: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", match)
            if len(digits) != 10 or digits in seen:
                continue
            seen.add(digits)
            found.append(f"{digits[:3]}-{digits[3:6]}-{digits[6:]}")
    return found


def is_phone_only(text: str) -> bool:
    stripped = PHONE_RE.sub("", text)
    return bool(PHONE_RE.search(text)) and not re.search(r"[A-Za-z]", stripped)


def same_person(left: str, right: str) -> bool:
    a = re.sub(r"\s+", " ", left).strip().lower()
    b = re.sub(r"\s+", " ", right).strip().lower()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a_parts, b_parts = a.split(), b.split()
    if not a_parts or not b_parts or a_parts[-1] != b_parts[-1]:
        return False
    return len(a_parts[0]) >= 4 and a_parts[0][:4] == b_parts[0][:4]


def choose_name(names: list[str], dated: list[tuple[str, date | None]]) -> tuple[str, str]:
    cleaned = []
    seen = set()
    for name in names:
        text = re.sub(r"\s+", " ", name).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    if not cleaned:
        return "Unknown customer", ""

    clusters: list[list[str]] = []
    for name in cleaned:
        placed = False
        for cluster in clusters:
            if any(same_person(name, other) for other in cluster):
                cluster.append(name)
                placed = True
                break
        if not placed:
            clusters.append([name])

    def newest(name: str) -> date:
        dates = [when for label, when in dated if label.strip().lower() == name.lower() and when]
        return max(dates) if dates else date.min

    labels = []
    aliases = []
    for cluster in clusters:
        primary = max(cluster, key=lambda name: (len(name), newest(name)))
        labels.append(primary)
        aliases.extend(name for name in cluster if name.lower() != primary.lower())
    return " / ".join(labels), "; ".join(aliases)


def clean_note(text: str) -> str | None:
    text = PHONE_RE.sub(" ", text)
    text = re.sub(r"\(\s*\$[^)]*\)?", " ", text)
    text = re.sub(r"\$\s*\d[\d,]*(?:\.\d{2})?(?:\s*-\s*\$?\s*\d[\d,]*(?:\.\d{2})?)?", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -;:,+/")
    if not text or not re.search(r"[A-Za-z]", text):
        return None
    if re.fullmatch(r"gate code", text, flags=re.I):
        return None
    return text


def is_name_echo(note: str, names: list[str]) -> bool:
    filler = {"windows", "window", "ty", "rental", "realtor", "the"}
    note_words = set(re.findall(r"[a-z0-9']+", note.lower()))
    name_words: set[str] = set()
    for name in names:
        name_words.update(re.findall(r"[a-z0-9']+", name.lower()))
    return bool(note_words) and not (note_words - name_words - filler)


def service_notes(job: Job) -> list[str]:
    notes: list[str] = []
    description = re.sub(r"\s+", " ", (job.service_description or "")).strip()
    if description and description.lower() != "manual entry" and not is_phone_only(description):
        notes.append(description)

    source = (job.source_text or "").strip()
    if not source or source == "Manual entry":
        return notes

    name = re.sub(r"\s+", " ", (job.customer_name or "")).strip().lower()
    address = re.sub(r"\s+", " ", (job.address or "")).strip().lower()
    for line in source.splitlines():
        text = re.sub(r"\s+", " ", line).strip()
        if not text:
            continue
        lowered = text.lower()
        if name and (lowered == name or lowered.startswith(name)):
            continue
        if address and (lowered in address or address in lowered):
            continue
        if is_phone_only(text):
            continue
        if re.search(r"\b(ut|utah|united states)\b", lowered) and not re.search(
            r"\b(gate|code|dog|note|alarm)\b", lowered
        ):
            continue
        if description and lowered == description.lower():
            continue
        notes.append(text)
    cleaned = []
    for note in notes:
        text = clean_note(note)
        if text:
            cleaned.append(text)
    return cleaned


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    kept = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item.strip())
    return kept


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def group_jobs(jobs: list[Job]) -> list[Location]:
    keyed: list[tuple[Job, str]] = []
    blanks: list[Job] = []
    for job in jobs:
        address = (job.address or "").strip()
        if not address:
            blanks.append(job)
            continue
        keyed.append((job, normalize_address(address)))

    groups = UnionFind(len(keyed))
    order = sorted(range(len(keyed)), key=lambda index: len(keyed[index][1]), reverse=True)
    for longer_index in order:
        longer = keyed[longer_index][1]
        if not HOUSE_RE.match(longer):
            continue
        for shorter_index in order:
            if shorter_index == longer_index:
                continue
            shorter = keyed[shorter_index][1]
            if not HOUSE_RE.match(shorter):
                continue
            if longer == shorter or longer.startswith(shorter + " "):
                groups.union(longer_index, shorter_index)

    buckets: dict[int, list[Job]] = defaultdict(list)
    for index, (job, _) in enumerate(keyed):
        buckets[groups.find(index)].append(job)

    locations = [Location(jobs=bucket) for bucket in buckets.values()]
    for job in blanks:
        locations.append(Location(jobs=[job], geocode_note="No address on file. This row will not plot."))
    return locations


def city_by_street(locations: list[Location]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for location in locations:
        for raw in location.raw_addresses():
            tidy = tidy_address(raw)
            match = re.search(r",\s*([^,]+),\s*([A-Z]{2})\b", tidy)
            if not match:
                continue
            fingerprint = street_fingerprint(normalize_address(raw))
            if fingerprint:
                found[fingerprint].add(f"{match.group(1).strip()}, {match.group(2)}")
    return found


def cities_for_street(fingerprint: str, cities: dict[str, set[str]]) -> set[str]:
    direct = cities.get(fingerprint, set())
    if direct:
        return set(direct)
    matched: set[str] = set()
    for known, city_names in cities.items():
        if known.endswith(" " + fingerprint) or fingerprint.endswith(" " + known):
            matched.update(city_names)
    return matched


def with_state(address: str) -> str:
    if re.search(r",\s*[A-Z]{2}\b", address):
        return address
    for city in UTAH_CITIES:
        match = re.search(rf"(?i)(?P<head>.*?)(?:,\s*)?{re.escape(city)}$", address)
        if not match or not match.group("head").strip(" ,"):
            continue
        street = match.group("head").strip(" ,")
        return f"{street}, {city}, UT"
    return address


def display_address(location: Location, cities: dict[str, set[str]]) -> str:
    candidates = location.raw_addresses()
    if not candidates:
        return ""
    ranked = sorted(candidates, key=lambda raw: (has_state(tidy_address(raw)), len(raw)), reverse=True)
    address = with_state(tidy_address(ranked[0]))
    if re.search(r",\s*[A-Z]{2}\b", address):
        return address

    fingerprint = street_fingerprint(normalize_address(ranked[0]))
    matches = cities_for_street(fingerprint, cities)
    if len(matches) == 1:
        location.geocode_note = (
            "City and state were added from your other jobs on this street. Confirm the pin."
        )
        return f"{address}, {next(iter(matches))}"

    if re.match(r"^\d+\s+[NSEW]\s+\d+\s+[NSEW]$", address, flags=re.I):
        location.geocode_note = (
            "City and state were added because this is a Salt Lake grid address. Confirm the pin."
        )
        return f"{address}, Salt Lake City, UT"

    if "," in address:
        location.geocode_note = "No state on file. Google may place this pin in the wrong place or skip it."
    else:
        location.geocode_note = "No city on file. Google may place this pin in the wrong city or skip it."
    return address


def location_row(location: Location, cities: dict[str, set[str]]) -> dict[str, str]:
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

    dates = [job.job_date.isoformat() for job in jobs if job.job_date]
    prices = [job.ticket_price for job in jobs if job.ticket_price is not None]
    tips = [job.tips for job in jobs if job.tips is not None]
    latest_price = next((job.ticket_price for job in reversed(jobs) if job.ticket_price is not None), None)
    cash_count = sum(1 for job in jobs if job.is_cash)
    address = display_address(location, cities)

    description_lines = []
    if phones:
        description_lines.append("Phone: " + ", ".join(phones))
    if dates:
        description_lines.append(f"Visits: {len(jobs)} ({dates[0]} to {dates[-1]})" if len(dates) > 1 else f"Visit: {dates[0]}")
    else:
        description_lines.append(f"Visits: {len(jobs)}")
    if latest_price is not None:
        description_lines.append(f"Latest ticket: ${latest_price:.2f}")
    if prices:
        description_lines.append(f"Total tickets: ${sum(prices, Decimal('0')):.2f}")
    if tips:
        description_lines.append(f"Total tips: ${sum(tips, Decimal('0')):.2f}")
    if notes:
        description_lines.append("Notes: " + "; ".join(notes))
    if aliases:
        description_lines.append("Also listed as: " + aliases)
    if location.geocode_note:
        description_lines.append(location.geocode_note)

    return {
        "Name": name,
        "Address": address,
        "Description": "\n".join(description_lines),
        "Phone": ", ".join(phones),
        "Visits": str(len(jobs)),
        "First Visit": dates[0] if dates else "",
        "Last Visit": dates[-1] if dates else "",
        "Latest Ticket": money(latest_price),
        "Total Tickets": money(sum(prices, Decimal("0"))) if prices else "",
        "Total Tips": money(sum(tips, Decimal("0"))) if tips else "",
        "Cash Jobs": str(cash_count),
        "Services": "; ".join(notes),
        "Also Known As": aliases,
        "Visit Dates": ", ".join(dates),
        "Geocode Note": location.geocode_note,
    }


COLUMNS = [
    "Name",
    "Address",
    "Description",
    "Phone",
    "Visits",
    "First Visit",
    "Last Visit",
    "Latest Ticket",
    "Total Tickets",
    "Total Tips",
    "Cash Jobs",
    "Services",
    "Also Known As",
    "Visit Dates",
    "Geocode Note",
]


def main() -> None:
    db = SessionLocal()
    try:
        jobs = list(db.scalars(select(Job).order_by(Job.job_date, Job.id)))
    finally:
        db.close()

    locations = group_jobs(jobs)
    cities = city_by_street(locations)
    rows = [location_row(location, cities) for location in locations]
    rows.sort(key=lambda row: (row["Name"].lower(), row["Address"].lower()))

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    missing_city = [row["Name"] for row in rows if row["Geocode Note"].startswith("No city")]
    no_address = [row["Name"] for row in rows if row["Geocode Note"].startswith("No address")]
    added_city = [row["Name"] for row in rows if row["Geocode Note"].startswith("City and state")]
    print(f"Wrote {len(rows)} locations from {len(jobs)} jobs to {OUTPUT}")
    print(f"City added: {len(added_city)}")
    print(f"No city: {len(missing_city)} -> {', '.join(missing_city) or 'none'}")
    print(f"No address: {len(no_address)} -> {', '.join(no_address) or 'none'}")


if __name__ == "__main__":
    main()
