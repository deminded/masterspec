#!/usr/bin/env python3
"""Machine gate for acceptance/apply after patch runs; never infer human approval."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import uuid


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATE = load("pending_inputs", "verification_state.py")
CHECKER = load("pending_report", "check-verify-report.py")
require = STATE.require


def marker_path(factory: Path, scope: str, change: Path | None = None) -> Path:
    directory = STATE.owner(factory, scope, change)
    name = "change-pending.json" if scope == "change" else "design-pending.json"
    return STATE.PROJECT.safe_path(directory / ".verification" / name)


def mark(factory: Path, scope: str, change: Path | None = None) -> Path:
    path = marker_path(factory, scope, change)
    document = {"schema": 1, "requires_full_verify": True, "scope": scope,
                "factory_root": str(STATE.PROJECT.safe_path(factory)),
                "marked_at": datetime.now(timezone.utc).isoformat(), "id": uuid.uuid4().hex}
    if scope == "change":
        document["change_root"] = str(STATE.owner(factory, scope, change))
    STATE.PATCH.write_json(path, document)
    return path


def check(factory: Path, scope: str, change: Path | None = None,
          report: Path | None = None, *, clear: bool = False) -> bool:
    marker = marker_path(factory, scope, change)
    if not marker.exists():
        return False
    raw, marker_stat = marker.read_bytes(), marker.stat()
    pending = json.loads(raw)
    require(isinstance(pending, dict), "invalid pending marker")
    if "schema" in pending:
        require(pending.get("schema") == 1 and pending.get("scope") == scope
                and pending.get("factory_root") == str(STATE.PROJECT.safe_path(factory)), "pending marker identity mismatch")
        if scope == "change":
            require(pending.get("change_root") == str(STATE.owner(factory, scope, change)), "pending change mismatch")
    report = STATE.PROJECT.regular(report or STATE.owner(factory, scope, change) / "verify-report.md")
    data, errors = CHECKER.validate(report)
    require(not errors, "invalid full verification report: " + "; ".join(errors))
    require(data.get("mode") == "full" and data.get("preset") == "full" and data.get("scope") == scope,
            "pending requires mode=full, preset=full and the selected scope")
    readiness = "cascade_ready" if scope == "change" else "codegen_ready"
    require(data.get(readiness) == "yes", f"pending requires {readiness}: yes")
    require(bool(data.get("inputs")) and bool(data.get("verified_inputs_digest")),
            "pending requires full verification inputs and digest")
    stored = STATE.validate_evidence(report, data)
    require(stored.get("factory_root") == str(STATE.PROJECT.safe_path(factory)), "report belongs to another factory")
    if scope == "change":
        require(stored.get("change_root") == str(STATE.owner(factory, scope, change)), "report belongs to another change")
    marked = datetime.fromtimestamp(marker_stat.st_mtime, timezone.utc)
    if "marked_at" in pending:
        stamp = datetime.fromisoformat(pending["marked_at"].replace("Z", "+00:00"))
        require(stamp.tzinfo is not None and stamp.utcoffset() is not None, "pending timestamp requires a timezone")
        marked = max(marked, stamp)
    captured = datetime.fromisoformat(stored["captured_at"].replace("Z", "+00:00"))
    require(captured >= marked, "full verification predates the pending marker")
    require(marker.read_bytes() == raw and marker.stat().st_mtime_ns == marker_stat.st_mtime_ns,
            "pending marker changed during validation")
    if clear:
        marker.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("mark", "capture", "check", "clear"))
    parser.add_argument("factory", type=Path)
    parser.add_argument("--scope", choices=("spec", "change"), required=True)
    parser.add_argument("--change", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--rules", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "mark":
            print(f"PENDING: {mark(args.factory, args.scope, args.change)}")
        elif args.command == "capture":
            require(args.out is not None, "capture requires --out")
            directory = STATE.owner(args.factory, args.scope, args.change) / ".verification"
            target = STATE.PROJECT.safe_path(args.out)
            require(target.is_relative_to(directory), "capture output must be in the selected .verification directory")
            require(not target.exists(), "capture output already exists; preserve the inputs recorded before verification")
            state = STATE.capture(args.factory, args.scope, args.change, args.rules)
            STATE.PATCH.write_json(target, state)
            print(json.dumps({"inputs": str(target), "verified_inputs_digest": STATE.state_digest(state)}))
        else:
            present = check(args.factory, args.scope, args.change, args.report, clear=args.command == "clear")
            print("PASS: full verification matches current inputs" if present else "PASS: no pending patch run")
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError, STATE.yaml.YAMLError) as error:
        print(f"BLOCKER: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
