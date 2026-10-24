#!/usr/bin/env python3
"""Plan local rechecks between two revisions of one unapplied spec-only change."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

import yaml


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PATCH = load("change_patch_graph", "design-patch.py")
PROJECT = load("change_patch_projection", "change_projection.py")
SCOPE = PROJECT.SCOPE
require = SCOPE.require
EDITABLE = {"Черновик", "Заблокировано", "На согласовании"}


def change_contract(text: str) -> tuple[str, str]:
    """Freeze everything except section-4 AFTER payloads and the review status."""
    original, visible = PROJECT.visible_lines(text)
    headings = [(i, re.match(r"^##\s+([1-8])(?:\.|\s|$)", line))
                for i, line in enumerate(visible) if re.match(r"^##\s", line)]
    require(all(match is not None for _, match in headings)
            and [match[1] for _, match in headings] == list("12345678"),
            "patch requires the canonical eight change sections")
    left, right = headings[3][0], headings[4][0]
    status_lines = [(i, re.fullmatch(r">\s*\*\*Статус\*\*:\s*(.+?)\s*", line))
                    for i, line in enumerate(visible[:headings[0][0]])
                    if re.match(r">\s*\*\*Статус\*\*:", line)]
    require(len(status_lines) == 1 and status_lines[0][1] is not None, "expected one change status")
    status = status_lines[0][1][1]
    require(status in EDITABLE, f"change is approved/applied or has an unsupported status: {status}")
    blocks = PROJECT.diff_blocks(text)
    labels = [i for i in range(left + 1, right) if visible[i].strip() == "ПОСЛЕ:"]
    require(len(labels) == len(blocks), "unprojectable section-4 payload")
    hidden, replacements = set(), set()
    for label in labels:
        opening = label + 1
        while opening < right and not original[opening].strip():
            opening += 1
        marker = re.fullmatch(r"\s{0,3}(`{3,}|~{3,})([^\n]*)", original[opening]) if opening < right else None
        require(marker is not None, "AFTER must use a fenced payload")
        closing = next((i for i in range(opening + 1, right)
                        if re.fullmatch(r"\s{0,3}" + re.escape(marker[1][0]) +
                                        "{" + str(len(marker[1])) + r",}\s*", original[i])), None)
        require(closing is not None, "unterminated AFTER payload")
        replacements.add(opening)
        hidden.update(range(opening + 1, closing))
    protected = []
    for i, line in enumerate(original):
        if i == status_lines[0][0] or i in hidden:
            continue
        protected.append(line)
        if i in replacements:
            protected.append("<AFTER payload>")
    return PATCH.digest("\n".join(protected).encode("utf-8")), status


def snapshot(factory: Path, change: Path, extra_rules: list[str] | None = None) -> dict:
    factory, change = PROJECT.safe_path(factory), PROJECT.safe_path(change)
    parents = {factory / "changes"}
    if factory.name == "specs":
        parents.add(factory.parent / "changes")
    require(change.parent in parents and change.name.casefold() != "archive", "change must be active in resolved changes-root")
    require(not any((change / name).exists() for name in ("import-map.json", "source-inventory.json")),
            "OpenSpec imports require the dedicated import verification workflow")
    SCOPE.check(change, factory)
    text = PROJECT.regular(change / "change.md").read_text(encoding="utf-8-sig")
    contract, status = change_contract(text)
    contents = PATCH.input_contents(factory)
    original = PATCH.snapshot(factory, extra_rules, contents=contents)
    proposed = PROJECT.project_plan(change, factory, contents)
    state = PATCH.snapshot(factory, extra_rules, contents=proposed)
    inputs = {"change.md": PATCH.digest(PROJECT.regular(change / "change.md").read_bytes())}
    for name in ("proposal.md", ".openspec.yaml"):
        if (change / name).exists():
            inputs[name] = PATCH.digest(PROJECT.regular(change / name).read_bytes())
    if (change / "new").exists():
        for path in sorted((change / "new").iterdir()):
            inputs["new/" + path.name] = PATCH.digest(PROJECT.regular(path).read_bytes())
    state.update(workflow="evolve", change_root=str(change), change_status=status,
                 change_contract=contract, change_inputs=inputs, factory_digest=PATCH.state_digest(original))
    return state


def plan(factory: Path, change: Path, baseline: dict, targets: list[str] | None = None) -> dict:
    require(isinstance(baseline, dict) and baseline.get("workflow") == "evolve", "expected an evolve change baseline")
    require(baseline.get("change_root") == str(PROJECT.safe_path(change)), "baseline belongs to another change")
    require(baseline.get("change_status") in EDITABLE, "baseline was approved/applied")
    current = snapshot(factory, change, baseline.get("extra_rules"))
    result = PATCH.plan_states(factory, baseline, current, targets, workflow="evolve")
    reasons = result["reasons"]
    if baseline.get("factory_digest") != current["factory_digest"]:
        reasons.append("factory baseline or rules changed; recheck the whole change")
    if baseline.get("change_contract") != current["change_contract"]:
        reasons.append("change goal/scope/AC/BEFORE anchors or diff structure changed")
    old_inputs = baseline.get("change_inputs")
    require(isinstance(old_inputs, dict), "invalid change input inventory")
    new_inputs = current["change_inputs"]
    changed_inputs = sorted(key for key in old_inputs.keys() | new_inputs.keys()
                            if old_inputs.get(key) != new_inputs.get(key))
    if old_inputs.keys() != new_inputs.keys():
        reasons.append("change staging/projection file inventory changed")
    if any(name in changed_inputs for name in ("proposal.md", ".openspec.yaml")):
        reasons.append("OpenSpec projection/config changed")
    if changed_inputs and result["route"] == "noop":
        reasons.append("change text changed without a projectable artifact delta")
    if reasons:
        result["route"] = "full"
    result.update(workflow="evolve", change_root=current["change_root"],
                  changed_change_files=changed_inputs, reasons=sorted(set(reasons)))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("snapshot", help="capture this proposal and its immutable factory base")
    capture.add_argument("factory", type=Path)
    capture.add_argument("--change", type=Path, required=True)
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--rules", action="append", default=[])
    check = sub.add_parser("plan", help="recheck changed proposal artifacts and old/new dependents")
    check.add_argument("factory", type=Path)
    check.add_argument("--change", type=Path, required=True)
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--target", action="append", default=[])
    check.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = snapshot(args.factory, args.change, args.rules)
            PATCH.write_json(args.out, value)
            print(f"Change baseline: {args.out}; not a verification certificate")
            return 0
        value = plan(args.factory, args.change, json.loads(args.baseline.read_text(encoding="utf-8")), args.target)
        if args.out:
            PATCH.write_json(args.out, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["route"] in {"patch", "noop"} else 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError) as error:
        value = {"route": "full", "reasons": [str(error)]}
        if args.command == "plan" and args.out:
            PATCH.write_json(args.out, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
