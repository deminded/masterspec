#!/usr/bin/env python3
"""Inventory native OpenSpec deltas without interpreting or applying their prose.

Only canonical spec-driven Markdown is supported. This structural check does not
replace `openspec validate` or the semantic review/mapping into MasterSpec.
All paths in the JSON are relative to --source or --specs; no files are written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


OPERATIONS = {"ADDED", "MODIFIED", "REMOVED", "RENAMED"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_path(path: Path) -> Path:
    """Reject links/junctions before resolving, including a linked root itself."""
    path = path.absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(),
                f"symlink/junction input is unsupported: {part}")
        if part.exists():
            # Python < 3.12 has no Path.is_junction(). Windows reparse points
            # must not become an unnoticed second way of crossing a root.
            require(not (getattr(part.lstat(), "st_file_attributes", 0) &
                         getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)),
                    f"symlink/junction input is unsupported: {part}")
    return path.resolve()


def bounded(root: Path, relative: Path) -> Path:
    require(not relative.is_absolute() and ".." not in relative.parts,
            f"path escapes root: {relative}")
    result = safe_path(root / relative)
    require(result.is_relative_to(root), f"path escapes root: {relative}")
    return result


def read_file(path: Path) -> tuple[str, str]:
    require(path.is_file(), f"expected a regular file: {path}")
    data = path.read_bytes()
    return data.decode("utf-8-sig"), digest(data)


def visible_lines(text: str) -> tuple[list[str], list[str]]:
    """Keep line numbers/content while hiding headings inside examples/comments."""
    original = text.splitlines()
    cleaned = re.sub(r"<!--.*?-->", lambda m: "\n" * m[0].count("\n"), text, flags=re.S)
    require("<!--" not in cleaned, "unterminated HTML comment")
    visible = []
    fence = None
    for line in cleaned.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            visible.append("")
        elif marker:
            fence = marker[1]
            visible.append("")
        else:
            visible.append(line)
    require(fence is None, "unterminated code fence")
    # A trailing all-comment line can disappear with splitlines().
    visible.extend([""] * (len(original) - len(visible)))
    return original, visible


def heading(line: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"\s{0,3}(#{1,6})\s+(.+?)\s*", line)
    return (len(match[1]), match[2]) if match else None


def requirement(lines: list[str], visible: list[str], start: int, end: int,
                *, complete: bool) -> dict:
    match = re.fullmatch(r"\s{0,3}### Requirement:\s*(\S.*?)\s*", visible[start])
    require(match is not None, f"line {start + 1}: expected '### Requirement: <name>'")
    name = match[1]
    scenario_starts = []
    for i in range(start + 1, end):
        found = re.fullmatch(r"\s{0,3}#### Scenario:\s*(\S.*?)\s*", visible[i])
        if found:
            scenario_starts.append((i, found[1]))
        elif re.match(r"\s{0,3}#{1,6}\s+(?:Requirement|Scenario)\b", visible[i]):
            raise ValueError(f"line {i + 1}: malformed requirement/scenario heading")
    names = [name for _, name in scenario_starts]
    require(len(names) == len(set(names)), f"duplicate scenario in requirement {name!r}")
    if complete:
        require(bool(scenario_starts), f"requirement {name!r} needs at least one '#### Scenario:'")
        statement_end = scenario_starts[0][0]
        require(re.search(r"\b(?:SHALL|MUST)\b", "\n".join(visible[start + 1:statement_end])) is not None,
                f"requirement {name!r} needs a SHALL or MUST statement before its scenarios")
    scenarios = []
    for index, (position, scenario_name) in enumerate(scenario_starts):
        stop = scenario_starts[index + 1][0] if index + 1 < len(scenario_starts) else end
        scenarios.append({"name": scenario_name, "text": "\n".join(lines[position:stop]).strip() + "\n"})
    return {"name": name, "text": "\n".join(lines[start:end]).strip() + "\n", "scenarios": scenarios}


def parse_specs(text: str, *, delta: bool) -> list[dict]:
    lines, visible = visible_lines(text)
    sections: list[tuple[int, str]] = []
    for i, line in enumerate(visible):
        item = heading(line)
        if delta and item and (re.match(r"(?:ADDED|MODIFIED|REMOVED|RENAMED)\b", item[1]) or
                               re.fullmatch(r"[A-Z]+ Requirements?", item[1])):
            require(item[0] == 2 and item[1] in {f"{op} Requirements" for op in OPERATIONS},
                    f"line {i + 1}: malformed operation heading {item[1]!r}")
        if item and item[0] == 2:
            title = item[1]
            if delta:
                require(title == "Purpose" or title in {f"{op} Requirements" for op in OPERATIONS},
                        f"line {i + 1}: unknown or malformed delta heading {title!r}")
            sections.append((i, title))
    titles = [title for _, title in sections]
    require(len(titles) == len(set(titles)), "duplicate section heading")
    if not delta:
        require(titles.count("Requirements") == 1, "main spec needs one '## Requirements' section")
    parsed = []
    consumed: set[int] = set()
    requirement_lines: set[int] = set()
    for number, (start, title) in enumerate(sections):
        end = sections[number + 1][0] if number + 1 < len(sections) else len(lines)
        operation = title.removesuffix(" Requirements") if delta else "BASE"
        if title == "Purpose" or (not delta and title != "Requirements"):
            continue
        if operation == "RENAMED":
            pending = None
            count = 0
            for i in range(start + 1, end):
                line = visible[i].strip()
                if not line:
                    continue
                match = re.fullmatch(r"- (FROM|TO): `### Requirement: (\S.*?)`", line)
                require(match is not None, f"line {i + 1}: expected canonical FROM/TO rename marker")
                if match[1] == "FROM":
                    require(pending is None, f"line {i + 1}: FROM without preceding TO")
                    pending = (match[2], i)
                else:
                    require(pending is not None, f"line {i + 1}: TO without FROM")
                    old_name, position = pending
                    parsed.append({"operation": operation, "from": old_name, "to": match[2],
                                   "line": position + 1,
                                   "delta_text": "\n".join(lines[position:i + 1]).strip() + "\n"})
                    pending = None
                    count += 1
            require(pending is None, "unfinished rename pair: missing TO")
            require(count > 0, "RENAMED Requirements section is empty")
            continue
        starts = []
        for i in range(start + 1, end):
            item = heading(visible[i])
            if item and item[0] <= 3:
                require(item[0] == 3 and item[1].startswith("Requirement: "),
                        f"line {i + 1}: unexpected heading inside {title}")
                starts.append(i)
                consumed.add(i)
        require(bool(starts), f"{title} section is empty")
        require(not any(line.strip() for line in visible[start + 1:starts[0]]),
                f"line {start + 2}: unassigned content before first requirement")
        for index, position in enumerate(starts):
            stop = starts[index + 1] if index + 1 < len(starts) else end
            block = requirement(lines, visible, position, stop, complete=operation != "REMOVED")
            requirement_lines.update(range(position, stop))
            parsed.append({"operation": operation, "requirement": block, "line": position + 1,
                           "delta_text": block["text"]})
    for i, line in enumerate(visible):
        if re.match(r"\s{0,3}#{1,6}\s+Requirement\b", line):
            require(i in consumed, f"line {i + 1}: requirement outside its canonical section")
        if re.match(r"\s{0,3}#{1,6}\s+Scenario\b", line):
            require(i in requirement_lines, f"line {i + 1}: scenario outside a requirement")
    require(bool(parsed), "no requirement operations found")
    return parsed


def renamed(block: dict, new_name: str) -> dict:
    return {**block, "name": new_name,
            "text": re.sub(r"^\s{0,3}### Requirement:.*", lambda _: f"### Requirement: {new_name}",
                           block["text"], count=1)}


def build_operations(capability: str, source_path: str, delta: list[dict], base: list[dict]) -> list[dict]:
    original = {}
    for item in base:
        block = item["requirement"]
        require(block["name"] not in original, f"duplicate main requirement: {block['name']!r}")
        original[block["name"]] = block
    rename_items = [item for item in delta if item["operation"] == "RENAMED"]
    normal_items = [item for item in delta if item["operation"] != "RENAMED"]
    rename_sources = [item["from"] for item in rename_items]
    rename_targets = [item["to"] for item in rename_items]
    require(len(rename_sources) == len(set(rename_sources)) and len(rename_targets) == len(set(rename_targets)),
            "duplicate rename source or destination")
    declared = [item["requirement"]["name"] for item in normal_items]
    require(len(declared) == len(set(declared)), "duplicate/conflicting requirement operations")
    effective = dict(original)
    result = []

    def append(item: dict, before: dict | None, after: dict | None) -> None:
        identity = {"capability": capability, "operation": item["operation"],
                    "before": before["name"] if before else None, "after": after["name"] if after else None}
        result.append({"id": "op-" + digest(canonical(identity))[:16], "capability": capability,
                       "operation": item["operation"], "before": before, "after": after,
                       "source": {"path": source_path, "line": item["line"]}, "delta_text": item["delta_text"]})

    for item in rename_items:
        old, new = item["from"], item["to"]
        require(old in original, f"RENAMED source does not exist: {old!r}")
        require(new not in original and new not in rename_sources, f"RENAMED destination collides: {new!r}")
        require(old not in declared, f"renamed requirement {old!r}: use its new name in MODIFIED")
        before, after = original[old], renamed(original[old], new)
        del effective[old]
        effective[new] = after
        append(item, before, after)
    for item in normal_items:
        op, block = item["operation"], item["requirement"]
        name = block["name"]
        if op == "ADDED":
            require(name not in effective, f"ADDED requirement already exists: {name!r}; use MODIFIED")
            append(item, None, block)
        else:
            require(name in effective, f"{op} requirement does not exist in main spec: {name!r}")
            require(op == "MODIFIED" or name not in rename_targets,
                    f"requirement {name!r} cannot be both RENAMED and REMOVED")
            append(item, effective[name], block if op == "MODIFIED" else None)
    return result


def check_metadata(text: str) -> None:
    """Recognize canonical metadata, never guess YAML aliases/quoted keys."""
    keys = set()
    document_started = False
    document_ended = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        require(not document_ended, "multiple YAML documents in .openspec.yaml are unsupported")
        if line == "---":
            require(not document_started, "multiple YAML documents in .openspec.yaml are unsupported")
            document_started = True
            continue
        if line == "...":
            document_ended = True
            continue
        document_started = True
        require(not line[0].isspace(),
                "unsupported .openspec.yaml indentation: use root-level scalar fields")
        match = re.fullmatch(r"([a-zA-Z_][a-zA-Z0-9_-]*):(?:\s+(.*))?", line)
        require(match is not None, "unsupported .openspec.yaml form: use a plain mapping without aliases/quoted keys")
        key, value = match[1], (match[2] or "").split(" #", 1)[0].strip()
        require(not value.startswith(("&", "*", "!", "|", ">", "{", "[")),
                "unsupported .openspec.yaml value: use plain or quoted scalars without aliases/tags")
        require(key not in keys, f"duplicate .openspec.yaml key: {key}")
        keys.add(key)
        if key == "skip_specs":
            require(value == "false", "skip_specs must be false: a compatibility bridge is not a native delta source")


def inventory(source: Path, specs: Path) -> dict:
    source, specs = safe_path(source), safe_path(specs)
    require(source.is_dir(), f"source change directory does not exist: {source}")
    require(not specs.exists() or specs.is_dir(), f"main specs root is not a directory: {specs}")
    delta_root = bounded(source, Path("specs"))
    require(delta_root.is_dir(), "source has no native specs/ deltas")
    sources = []
    metadata = bounded(source, Path(".openspec.yaml"))
    if metadata.exists():
        text, checksum = read_file(metadata)
        check_metadata(text)
        sources.append({"path": ".openspec.yaml", "sha256": checksum})
    deltas = []
    for root, directories, files in os.walk(delta_root, followlinks=False):
        for name in (*directories, *files):
            bounded(source, (Path(root) / name).relative_to(source))
        for name in files:
            if name == "spec.md":
                relative = (Path(root) / name).relative_to(delta_root)
                require(len(relative.parts) > 1, "delta spec must have a capability directory")
                deltas.append(relative)
    require(bool(deltas), "source has no native specs/<capability>/spec.md deltas")
    require(len({path.as_posix().casefold() for path in deltas}) == len(deltas),
            "capability paths collide on a case-insensitive filesystem")
    bases, operations = [], []
    for relative in sorted(deltas, key=lambda path: path.as_posix()):
        source_relative = Path("specs") / relative
        text, checksum = read_file(bounded(source, source_relative))
        sources.append({"path": source_relative.as_posix(), "sha256": checksum})
        main_path = bounded(specs, relative)
        base = []
        base_hash = None
        try:
            delta = parse_specs(text, delta=True)
            if main_path.exists():
                base_text, base_hash = read_file(main_path)
                base = parse_specs(base_text, delta=False)
            operations.extend(build_operations(relative.parent.as_posix(), source_relative.as_posix(), delta, base))
        except ValueError as exc:
            raise ValueError(f"{source_relative.as_posix()}: {exc}") from exc
        bases.append({"path": relative.as_posix(), "sha256": base_hash})
    result = {"schema_version": 1, "change": source.name,
              "source_files": sorted(sources, key=lambda entry: entry["path"]),
              "base_files": bases, "operations": operations}
    result["inventory_id"] = digest(canonical(result))
    return result


def check_saved(saved_path: Path, current: dict) -> None:
    saved = json.loads(saved_path.read_text(encoding="utf-8-sig"))
    require(isinstance(saved, dict) and saved.get("schema_version") == 1, "unsupported saved inventory schema")
    recorded_id = saved.get("inventory_id")
    body = {key: value for key, value in saved.items() if key != "inventory_id"}
    require(recorded_id == digest(canonical(body)), "saved inventory checksum is invalid")
    require(saved == current, "inventory is stale: source deltas/metadata or relevant main specs changed; prepare again")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="native OpenSpec change directory")
    parser.add_argument("--specs", required=True, type=Path, help="native OpenSpec main specs root (may not exist for ADDED)")
    parser.add_argument("--check", type=Path, help="fail if the saved inventory differs from current source/base")
    args = parser.parse_args()
    try:
        result = inventory(args.source, args.specs)
        if args.check:
            check_saved(args.check, result)
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
