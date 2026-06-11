from __future__ import annotations

PAYROLL_STAGES: tuple[str, ...] = ("jobs", "assign", "hours", "calculate", "finalize")

PAYROLL_STEP_LABELS: dict[str, str] = {
    "jobs": "Jobs",
    "assign": "Assign",
    "hours": "Hours",
    "calculate": "Calculate",
    "finalize": "Finalize",
}

PAYROLL_STEPS: list[tuple[str, str]] = [
    (slug, PAYROLL_STEP_LABELS[slug]) for slug in PAYROLL_STAGES
]


def stage_index(stage: str) -> int:
    return PAYROLL_STAGES.index(stage)


def get_stage_url(batch_id: int, stage: str) -> str:
    return f"/payroll/{batch_id}/{stage}"


def is_valid_stage(stage: str) -> bool:
    return stage in PAYROLL_STAGES
