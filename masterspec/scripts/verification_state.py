"""Bind verification evidence to spec-only inputs without certifying their semantics."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import yaml


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PATCH = load_script("verification_graph", "design-patch.py")
PROJECT = PATCH._projection
require = PATCH.require


def change_root(factory: Path, change: Path | None) -> Path:
    require(change is not None, "scope=change requires --change")
    change = PROJECT.safe_path(change)
    parents = {factory / "changes"}
    if factory.name == "specs":
        parents.add(factory.parent / "changes")
    require(change.is_dir() and change.parent in parents and change.name.casefold() != "archive",
            "change must be active in the resolved changes-root")
    return change


def owner(factory: Path, scope: str, change: Path | None = None) -> Path:
    factory = PROJECT.safe_path(factory)
    require(factory.is_dir() and scope in {"spec", "change"}, "expected factory and scope=spec|change")
    return change_root(factory, change) if scope == "change" else factory


def capture(factory: Path, scope: str, change: Path | None = None,
            extra_rules: list[str] | None = None) -> dict:
    factory = PROJECT.safe_path(factory)
    destination = owner(factory, scope, change)
    extra_rules = extra_rules or []
    require(isinstance(extra_rules, list) and all(isinstance(item, str) for item in extra_rules),
            "extra_rules must be a list of paths")
    state = {
        "schema": 1, "type": "verification-inputs", "scope": scope,
        "factory_root": str(factory), "extra_rules": sorted(extra_rules),
        "files": {key: PATCH.digest(value) for key, value in PATCH.input_contents(factory).items()},
        "rules": PATCH.rules_snapshot(factory, extra_rules),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if scope == "change":
        inputs = {}
        for name in ("change.md", "proposal.md", ".openspec.yaml", "import-map.json", "source-inventory.json"):
            path = PROJECT.safe_path(destination / name)
            if path.exists() or name == "change.md":
                inputs[name] = PATCH.digest(PROJECT.regular(path).read_bytes())
        for path in PATCH.walk_files(destination, destination / "new"):
            inputs[path.relative_to(destination).as_posix()] = PATCH.digest(PROJECT.regular(path).read_bytes())
        state.update(change_root=str(destination), change_files=inputs)
    return state


def state_digest(state: dict) -> str:
    return PATCH.digest(json.dumps({key: value for key, value in state.items() if key != "captured_at"},
                                   sort_keys=True, ensure_ascii=False).encode("utf-8"))


def evidence_path(report: Path, value: str) -> Path:
    value = yaml.safe_load(value)
    require(isinstance(value, str) and bool(value), "evidence path must be a string")
    path = Path(value)
    return PROJECT.safe_path(path if path.is_absolute() else report.parent / path)


def read_json(path: Path) -> dict:
    value = json.loads(PROJECT.regular(path).read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected evidence object: {path}")
    return value


def validate_evidence(report: Path, fm: dict[str, str]) -> dict:
    if fm.get("mode", "full") == "patch":
        baseline = read_json(evidence_path(report, fm.get("baseline", "")))
        saved = read_json(evidence_path(report, fm.get("plan", "")))
        require(saved.get("current_digest") == fm.get("verified_inputs_digest"),
                "verified_inputs_digest differs from plan.current_digest")
        factory = Path(baseline["factory_root"])
        require(saved.get("factory_root") == str(PROJECT.safe_path(factory)), "plan factory mismatch")
        targets = saved.get("targets")
        require(isinstance(targets, list) and all(isinstance(item, str) for item in targets),
                "plan requires replayable targets")
        if fm.get("scope") == "change":
            change = evidence_path(report, fm.get("change", ""))
            require(baseline.get("change_root") == str(change), "report change differs from baseline")
            workflow = load_script("verification_change", "change-patch.py")
            current = workflow.plan(factory, change, baseline, targets)
        else:
            require(fm.get("scope") == "spec", "patch evidence requires scope=spec|change")
            current = PATCH.plan(factory, baseline, targets)
        require(current.get("route") == "patch", f"current patch route is {current.get('route')}, not patch")
        require(saved == current, "saved plan differs from the current tree, rules, or verification scope")
        return baseline

    stored = read_json(evidence_path(report, fm.get("inputs", "")))
    require(stored.get("schema") == 1 and stored.get("type") == "verification-inputs",
            "unknown full verification input schema")
    require(stored.get("scope") == fm.get("scope"), "report scope differs from captured inputs")
    require(state_digest(stored) == fm.get("verified_inputs_digest"), "full verification input digest mismatch")
    factory = PROJECT.safe_path(Path(stored["factory_root"]))
    change = None
    if fm.get("scope") == "change":
        change = evidence_path(report, fm.get("change", ""))
        require(stored.get("change_root") == str(change), "report change differs from captured inputs")
    current = capture(factory, fm["scope"], change, stored.get("extra_rules"))
    require(state_digest(current) == state_digest(stored), "full verification inputs are stale")
    captured = datetime.fromisoformat(stored["captured_at"].replace("Z", "+00:00"))
    started = datetime.fromisoformat(fm["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(fm["finished_at"].replace("Z", "+00:00"))
    require(all(value.tzinfo is not None and value.utcoffset() is not None
                for value in (captured, started, finished)), "input/report timestamps require a timezone")
    require(started <= captured <= finished, "inputs must be captured during the recorded verification run")
    return stored
