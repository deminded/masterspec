#!/usr/bin/env python3
"""Deterministic schema and telemetry gate for a masterspec verify-report."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path


REQUIRED_FRONTMATTER = (
    "type",
    "factory",
    "scope",
    "preset",
    "last_verified",
    "verified_revision",
    "started_at",
    "finished_at",
)
REQUIRED_METRICS = (
    "last_verified",
    "verification_age_days",
    "oldest_element_last_verified",
    "oldest_element_age_days",
    "stale_after_days",
    "stale_elements",
    "wall_time_seconds",
    "agent_calls",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "estimated_cost",
    "cost_basis",
    "axis_runs_total",
    "axis_runs_machine",
    "machine_axes_percent",
)
PLACEHOLDER = re.compile(r"<[^>]+>|\b(?:TBD|TODO|placeholder)\b|…", re.I)
N_A = re.compile(r"^N/A\s*[—-]\s*\S", re.I)


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def metrics(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*-\s+([a-z_]+):\s*(.*?)\s*$", line)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def integer(value: str) -> int | None:
    return int(value) if re.fullmatch(r"\d+", value) else None


def number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def validate(path: Path, today: date | None = None) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8")
    fm = frontmatter(text)
    data = metrics(text)
    errors: list[str] = []
    today = today or date.today()

    for name in REQUIRED_FRONTMATTER:
        value = fm.get(name, "")
        if not value or PLACEHOLDER.search(value):
            errors.append(f"missing/template frontmatter field {name}")
    if fm.get("type") != "verify-report":
        errors.append("frontmatter type must be verify-report")
    if fm.get("scope") not in {"req", "spec", "change"}:
        errors.append("scope must be req, spec, or change")
    if fm.get("preset") not in {"core", "full"}:
        errors.append("preset must be core or full")

    verified_date: date | None = None
    try:
        verified_date = date.fromisoformat(fm.get("last_verified", ""))
    except ValueError:
        errors.append("last_verified must be YYYY-MM-DD")
    timestamps: dict[str, datetime] = {}
    for name in ("started_at", "finished_at"):
        try:
            timestamps[name] = datetime.fromisoformat(fm.get(name, "").replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{name} must be an ISO-8601 timestamp")
    if len(timestamps) == 2 and timestamps["finished_at"] < timestamps["started_at"]:
        errors.append("finished_at precedes started_at")

    for name in REQUIRED_METRICS:
        value = data.get(name, "")
        if not value or PLACEHOLDER.search(value):
            errors.append(f"missing/template metric {name}")
    if data.get("last_verified") and data["last_verified"] != fm.get("last_verified"):
        errors.append("body last_verified differs from frontmatter last_verified")

    for name in (
        "verification_age_days",
        "oldest_element_age_days",
        "stale_after_days",
        "stale_elements",
        "agent_calls",
        "axis_runs_total",
        "axis_runs_machine",
    ):
        if data.get(name) and integer(data[name]) is None:
            errors.append(f"{name} must be a non-negative integer")

    if data.get("wall_time_seconds") and number(data["wall_time_seconds"]) is None:
        errors.append("wall_time_seconds must be numeric")
    for name in ("input_tokens", "output_tokens", "cached_input_tokens"):
        value = data.get(name, "")
        if not value or N_A.match(value):
            continue
        parsed = integer(value)
        if parsed is None:
            errors.append(f"{name} must be an integer or 'N/A — reason'")
        # cached=0 законно (холодный кеш); нулевой счётчик потреблённых токенов — нет:
        # это неизмеренное значение под видом «было бесплатно» (дыра телеметрии).
        elif parsed == 0 and name != "cached_input_tokens":
            errors.append(f"{name} must be positive or 'N/A — reason' (zero hides an unmeasured value)")
    estimated = data.get("estimated_cost", "")
    if estimated and not N_A.match(estimated):
        amount = re.fullmatch(r"(\d+(?:\.\d+)?)\s+[A-Z]{3}", estimated)
        if not amount:
            errors.append("estimated_cost must be '<decimal> <ISO currency>' or 'N/A — reason'")
        # Нулевая стоимость реального прогона — та же дыра телеметрии: либо число >0, либо N/A с причиной.
        elif float(amount.group(1)) == 0:
            errors.append("estimated_cost must be positive or 'N/A — reason' (zero cost hides an unmeasured value)")
    if data.get("cost_basis") and not N_A.match(data["cost_basis"]) and len(data["cost_basis"]) < 3:
        errors.append("cost_basis must identify tariff/model/date or use 'N/A — reason'")

    total = integer(data.get("axis_runs_total", ""))
    machine = integer(data.get("axis_runs_machine", ""))
    percent = number(data.get("machine_axes_percent", ""))
    if total is not None and total == 0:
        errors.append("axis_runs_total must be greater than zero")
    if total is not None and machine is not None:
        if machine > total:
            errors.append("axis_runs_machine exceeds axis_runs_total")
        if total and percent is not None and abs(percent - round(machine / total * 100, 2)) > 0.005:
            errors.append("machine_axes_percent does not equal machine/total × 100")
    if percent is not None and not 0 <= percent <= 100:
        errors.append("machine_axes_percent must be in range 0..100")

    if verified_date is not None:
        age = integer(data.get("verification_age_days", ""))
        expected_age = (today - verified_date).days
        if expected_age < 0:
            errors.append("last_verified is in the future")
        elif age is not None and age != expected_age:
            errors.append(f"verification_age_days is {age}, expected {expected_age}")
    try:
        oldest = date.fromisoformat(data.get("oldest_element_last_verified", ""))
        oldest_age = integer(data.get("oldest_element_age_days", ""))
        expected_oldest_age = (today - oldest).days
        if expected_oldest_age < 0:
            errors.append("oldest_element_last_verified is in the future")
        elif oldest_age is not None and oldest_age != expected_oldest_age:
            errors.append(
                f"oldest_element_age_days is {oldest_age}, expected {expected_oldest_age}"
            )
    except ValueError:
        if data.get("oldest_element_last_verified"):
            errors.append("oldest_element_last_verified must be YYYY-MM-DD")

    return {**fm, **data}, errors


def run(path: Path) -> int:
    data, errors = validate(path)
    print(
        "VERIFY-REPORT metrics: "
        f"last_verified={data.get('last_verified', '?')} "
        f"age_days={data.get('verification_age_days', '?')} "
        f"wall_time_seconds={data.get('wall_time_seconds', '?')} "
        f"agent_calls={data.get('agent_calls', '?')} "
        f"machine_axes={data.get('axis_runs_machine', '?')}/{data.get('axis_runs_total', '?')} "
        f"machine_axes_percent={data.get('machine_axes_percent', '?')}"
    )
    for error in errors:
        print(f"BLOCKER: {path}: {error}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    return run(args.report)


if __name__ == "__main__":
    sys.exit(main())
