#!/usr/bin/env python3
"""Read-only pre-apply gate for a mapped native OpenSpec import (stdlib only)."""

from __future__ import annotations

import argparse
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


def check(change: Path, factory: Path, source: Path, specs: Path) -> dict:
    change, factory, source = safe_path(change), safe_path(factory), safe_path(source)
    require(change != factory, "destination change must not be the factory root")
    require(not change.is_relative_to(source) and not source.is_relative_to(change),
            "source and destination changes must not overlap")
    require((factory / "00-masterspec-index.md").is_file(), "factory has no index")
    current = inventory(source, specs)
    snapshot = SCOPE.bounded_file(change, SCOPE.relative_path("source-inventory.json"))
    check_saved(snapshot, current)
    map_file = SCOPE.bounded_file(change, SCOPE.relative_path("import-map.json"))
    mapping = json.loads(map_file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    require(isinstance(mapping, dict) and mapping.get("schema_version") == 1,
            "unsupported import-map schema")
    require(mapping.get("inventory_id") == current["inventory_id"], "mapping has a different inventory_id")
    bindings, files = mapping.get("bindings"), mapping.get("target_files")
    require(isinstance(bindings, list) and isinstance(files, list), "bindings/target_files must be arrays")
    operations = {operation["id"]: operation for operation in current["operations"]}
    operation_ids = set(operations)
    seen, mapped_paths, changed_paths = set(), set(), set()
    positive_evidence = set()
    changed = 0
    for binding in bindings:
        require(isinstance(binding, dict), "binding must be an object")
        operation = binding.get("operation_id")
        require(isinstance(operation, str) and operation in operation_ids and operation not in seen,
                f"unknown or repeated operation_id: {operation}")
        seen.add(operation)
        reason = binding.get("reason")
        require(isinstance(reason, str) and bool(reason.strip()), f"{operation}: missing reason")
        disposition = binding.get("disposition")
        require(disposition in {"change", "already-satisfied", "blocked"}, f"{operation}: invalid disposition")
        require(disposition != "blocked", f"{operation}: unresolved mapping: {reason}")
        targets = binding.get("targets")
        require(isinstance(targets, list) and bool(targets), f"{operation}: missing evidence targets")
        for target in targets:
            require(isinstance(target, dict), f"{operation}: target must be an object")
            relative = mapping_path(target.get("path"))
            require(relative.as_posix() != "00-masterspec-index.md", "index is not a normative mapping target")
            anchor = target.get("anchor")
            require(isinstance(anchor, str) and bool(anchor.strip()), f"{operation}: missing anchor")
            mapped_paths.add(relative.as_posix())
            if disposition == "change":
                changed_paths.add(relative.as_posix())
            elif operations[operation]["operation"] != "REMOVED":
                positive_evidence.add(relative.as_posix())
        changed += disposition == "change"
    require(seen == operation_ids, f"unmapped source operations: {sorted(operation_ids - seen)}")

    snapshots = {}
    path_keys = set()
    for entry in files:
        require(isinstance(entry, dict), "target_files entry must be an object")
        relative = mapping_path(entry.get("path"))
        key = relative.as_posix()
        require(key.casefold() not in path_keys, f"duplicate target snapshot: {key}")
        path_keys.add(key.casefold())
        checksum = entry.get("sha256")
        require("sha256" in entry and (checksum is None or
                isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum)),
                f"{key}: expected SHA256 or null")
        path = SCOPE.bounded_file(factory, relative, target=key != "00-masterspec-index.md")
        require(not path.exists() or path.is_file(), f"target is not a regular file: {key}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        require(actual == checksum, f"stale target: {key}; remap and review, do not refresh hashes blindly")
        snapshots[key] = checksum
    expected = mapped_paths | {"00-masterspec-index.md"}
    require(snapshots.get("00-masterspec-index.md") is not None, "index snapshot must exist")

    change_file = SCOPE.bounded_file(change, SCOPE.relative_path("change.md"))
    if changed:
        SCOPE.check(change, factory)
        lines = SCOPE.markdown_lines(change_file.read_text(encoding="utf-8-sig"))
        declared = set()
        for number in ("2.1", "2.2", "2.3"):
            for _, slug, relative in SCOPE.declarations(lines, number):
                declared.add(relative.as_posix())
                if relative.suffix == ".md" and relative.name != "00-glossary.md":
                    artifact = change / "new" / relative.name if number == "2.2" else factory / relative
                    metadata = SCOPE.frontmatter(artifact)
                    machine = SCOPE.sidecar(metadata, slug)
                    if machine:
                        expected.add((relative.parent / machine).as_posix())
        require(changed_paths <= declared, f"mapped changes absent from change.md: {sorted(changed_paths - declared)}")
        expected |= declared
    else:
        require(not change_file.exists(), "no-op import must not contain a change.md")
        require(not (change / "new").exists() or not any((change / "new").iterdir()),
                "no-op import must not stage new artifacts")
    require(expected <= snapshots.keys(), f"missing target snapshots: {sorted(expected - snapshots.keys())}")
    require(all(snapshots.get(path) is not None for path in positive_evidence),
            "already-satisfied positive requirements need existing evidence targets")
    return {"inventory_id": current["inventory_id"], "operations": len(seen),
            "result": "ready-for-review" if changed else "no-op-needs-semantic-verification"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("change", "factory", "source", "specs"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.change, args.factory, args.source, args.specs)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
