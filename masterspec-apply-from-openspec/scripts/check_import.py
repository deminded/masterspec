#!/usr/bin/env python3
"""Read-only pre-apply gate for a mapped native OpenSpec import (stdlib only).

diagnose() and the CLI return a JSON report. ``checks`` records passed/failed/
skipped phases; ``diagnostics`` contains check, kind (structural or semantic),
message and optional operation_id. Any diagnostic blocks application (CLI exit
1), including unresolved semantic mappings. Independent checks still run.
check() preserves the raising API; ImportCheckError.report carries that report.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from openspec_inventory import check_saved, inventory, safe_path


def load_scope():
    path = Path(__file__).resolve().parents[2] / "masterspec/scripts/check-change-scope.py"
    spec = importlib.util.spec_from_file_location("masterspec_change_scope", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCOPE = load_scope()
require = SCOPE.require


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def mapping_path(value):
    require(isinstance(value, str), "mapping path must be a string")
    relative = SCOPE.relative_path(value)
    require(relative.as_posix() == value, f"noncanonical mapping path: {value}")
    if value != "00-masterspec-index.md":
        SCOPE.target_path(value)
    return relative


class ImportCheckError(ValueError):
    def __init__(self, report: dict):
        self.report = report
        super().__init__("\n".join(item["message"] for item in report["diagnostics"]))


class Diagnostics:
    def __init__(self):
        self.items = []
        self.checks = dict.fromkeys(("paths", "factory", "inventory", "source-snapshot",
                                   "mapping", "operation-coverage", "target-snapshots", "scope",
                                   "readiness"), "skipped")

    def test(self, condition, message, stage, *, kind="structural", operation_id=None):
        if self.checks[stage] == "skipped":
            self.checks[stage] = "passed"
        if not condition:
            self.checks[stage] = "failed"
            item = {"check": stage, "kind": kind, "message": message}
            if isinstance(operation_id, str):
                item["operation_id"] = operation_id
            self.items.append(item)
        return bool(condition)

    @contextmanager
    def guard(self, stage, *, operation_id=None):
        self.test(True, "", stage)
        try:
            yield
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            self.test(False, str(exc), stage, operation_id=operation_id)

    def report(self, current=None, *, operations=0, changed=False):
        return {"inventory_id": current["inventory_id"] if current else None,
                "operations": operations,
                "result": "blocked" if self.items else
                          "ready-for-review" if changed else "no-op-needs-semantic-verification",
                "checks": self.checks, "diagnostics": self.items}


def diagnose(change: Path, factory: Path, source: Path, specs: Path) -> dict:
    diagnostics = Diagnostics()
    test, guard = diagnostics.test, diagnostics.guard
    with guard("paths"):
        change, factory, source = safe_path(change), safe_path(factory), safe_path(source)
        require(change != factory, "destination change must not be the factory root")
        require(not change.is_relative_to(source) and not source.is_relative_to(change),
                "source and destination changes must not overlap")
    if diagnostics.items:
        return diagnostics.report()  # Unsafe roots cannot be used by later checks.
    with guard("factory"):
        require((factory / "00-masterspec-index.md").is_file(), "factory has no index")
    current = None
    with guard("inventory"):
        current = inventory(source, specs)
    if current is not None:
        with guard("source-snapshot"):
            snapshot = SCOPE.bounded_file(change, SCOPE.relative_path("source-inventory.json"))
            check_saved(snapshot, current)

    mapping = None
    with guard("mapping"):
        map_file = SCOPE.bounded_file(change, SCOPE.relative_path("import-map.json"))
        candidate = json.loads(map_file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
        require(isinstance(candidate, dict) and candidate.get("schema_version") == 1,
                "unsupported import-map schema")
        mapping = candidate
    operations = {operation["id"]: operation for operation in current["operations"]} if current else None
    seen, mapped_paths, changed_paths, positive_evidence = set(), set(), set(), set()
    changed = blocked = 0
    files = None
    if mapping is not None:
        if current is not None:
            test(mapping.get("inventory_id") == current["inventory_id"],
                 "mapping has a different inventory_id", "operation-coverage")
        bindings, files = mapping.get("bindings"), mapping.get("target_files")
        valid_bindings = test(isinstance(bindings, list), "bindings must be an array", "mapping")
        test(isinstance(files, list), "target_files must be an array", "mapping")
        for binding in bindings if valid_bindings else []:
            if not test(isinstance(binding, dict), "binding must be an object", "mapping"):
                continue
            operation = binding.get("operation_id")
            valid_id = isinstance(operation, str) and bool(operation)
            unique = valid_id and operation not in seen
            test(unique,
                 f"unknown or repeated operation_id: {operation}", "mapping", operation_id=operation)
            if valid_id and operations is not None:
                test(operation in operations, f"unknown or repeated operation_id: {operation}",
                     "operation-coverage", operation_id=operation)
            if valid_id:
                seen.add(operation)
            reason, disposition = binding.get("reason"), binding.get("disposition")
            test(isinstance(reason, str) and bool(reason.strip()),
                 f"{operation}: missing reason", "mapping", operation_id=operation)
            test(disposition in ("change", "already-satisfied", "blocked"),
                 f"{operation}: invalid disposition", "mapping", operation_id=operation)
            if disposition in ("change", "already-satisfied", "blocked"):
                test(disposition != "blocked", f"{operation}: unresolved mapping: {reason}",
                     "readiness", kind="semantic", operation_id=operation)
            if disposition == "blocked":
                blocked += 1
            changed += disposition == "change"
            targets = binding.get("targets")
            if not test(isinstance(targets, list) and (bool(targets) or disposition == "blocked"),
                        f"{operation}: missing evidence targets", "mapping", operation_id=operation):
                continue
            for target in targets:
                with guard("mapping", operation_id=operation):
                    require(isinstance(target, dict), f"{operation}: target must be an object")
                    relative = mapping_path(target.get("path"))
                    require(relative.as_posix() != "00-masterspec-index.md", "index is not a normative mapping target")
                    anchor = target.get("anchor")
                    require(isinstance(anchor, str) and bool(anchor.strip()), f"{operation}: missing anchor")
                    mapped_paths.add(relative.as_posix())
                    if disposition == "change":
                        changed_paths.add(relative.as_posix())
                    elif (disposition == "already-satisfied" and operations is not None and
                          operation in operations and operations[operation]["operation"] != "REMOVED"):
                        positive_evidence.add(relative.as_posix())
        if operations is not None and valid_bindings:
            test(not (operations.keys() - seen), f"unmapped source operations: {sorted(operations.keys() - seen)}",
                 "operation-coverage")

    snapshots, path_keys = {}, set()
    if isinstance(files, list):
        for entry in files:
            with guard("target-snapshots"):
                require(isinstance(entry, dict), "target_files entry must be an object")
                relative = mapping_path(entry.get("path"))
                key = relative.as_posix()
                require(key.casefold() not in path_keys, f"duplicate target snapshot: {key}")
                path_keys.add(key.casefold())
                checksum = entry.get("sha256")
                require("sha256" in entry and (checksum is None or
                        isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum)),
                        f"{key}: expected SHA256 or null")
                snapshots[key] = checksum
                path = SCOPE.bounded_file(factory, relative, target=key != "00-masterspec-index.md")
                require(not path.exists() or path.is_file(), f"target is not a regular file: {key}")
                actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                require(actual == checksum, f"stale target: {key}; remap and review, do not refresh hashes blindly")
        test(snapshots.get("00-masterspec-index.md") is not None,
             "index snapshot must exist", "target-snapshots")

    expected = mapped_paths | {"00-masterspec-index.md"}
    change_file = None
    with guard("paths"):
        change_file = SCOPE.bounded_file(change, SCOPE.relative_path("change.md"))
    if change_file is not None and (change_file.exists() or changed):
        # Even a wholly blocked draft needs structural checks; it is not a no-op.
        with guard("scope"):
            SCOPE.check(change, factory)
        lines = None
        with guard("scope"):
            lines = SCOPE.markdown_lines(change_file.read_text(encoding="utf-8-sig"))
            test(not any(re.search(r"\*\*Статус\*\*:\s*Заблокировано", line) for line in lines),
                 "change.md status is Заблокировано", "readiness", kind="semantic")
        declared = set()
        if lines is not None:
            for number in ("2.1", "2.2", "2.3"):
                with guard("scope"):
                    for _, slug, relative in SCOPE.declarations(lines, number):
                        declared.add(relative.as_posix())
                        if relative.suffix == ".md" and relative.name != "00-glossary.md":
                            with guard("scope"):
                                if number == "2.2":
                                    artifact = SCOPE.bounded_file(change, SCOPE.relative_path("new/" + relative.name))
                                else:
                                    artifact = SCOPE.bounded_file(factory, relative, target=True)
                                metadata = SCOPE.frontmatter(artifact)
                                machine = SCOPE.sidecar(metadata, slug)
                                if machine:
                                    expected.add((relative.parent / machine).as_posix())
            test(changed_paths <= declared,
                 f"mapped changes absent from change.md: {sorted(changed_paths - declared)}", "scope")
        expected |= declared
    # Only a complete unblocked mapping can claim the no-op branch.
    if (mapping is not None and not changed and not blocked and
            diagnostics.checks["mapping"] == diagnostics.checks["operation-coverage"] == "passed"):
        with guard("scope"):
            require(change_file is not None and not change_file.exists(), "no-op import must not contain a change.md")
            staged = SCOPE.bounded_file(change, SCOPE.relative_path("new"))
            require(not staged.exists() or not any(staged.iterdir()), "no-op import must not stage new artifacts")
    if isinstance(files, list):
        test(expected <= snapshots.keys(), f"missing target snapshots: {sorted(expected - snapshots.keys())}",
             "target-snapshots")
        test(all(snapshots.get(path) is not None for path in positive_evidence),
             "already-satisfied positive requirements need existing evidence targets", "target-snapshots")
    return diagnostics.report(current, operations=len(seen & operations.keys()) if operations is not None else 0,
                              changed=bool(changed))


def check(change: Path, factory: Path, source: Path, specs: Path) -> dict:
    result = diagnose(change, factory, source, specs)
    if result["diagnostics"]:
        raise ImportCheckError(result)
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("change", "factory", "source", "specs"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(args.change, args.factory, args.source, args.specs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for item in result["diagnostics"]:
        print(f"BLOCKER [{item['check']}/{item['kind']}]: {item['message']}", file=sys.stderr)
    return int(bool(result["diagnostics"]))


if __name__ == "__main__":
    sys.exit(main())
