#!/usr/bin/env python3
"""Create bounded prepare workspaces and project canonical drafts into copies.

This is not apply-change: it never writes the factory, promotes status, updates
dates, rebuilds the index, or certifies a change. Semantic blockers remain open.
Only the standard library is required. The returned write roots are an agent
contract, not an operating-system sandbox for unrelated commands.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
import check_import
from openspec_inventory import check_saved, digest, inventory, safe_path, visible_lines


SCOPE = check_import.SCOPE
require = SCOPE.require
LIMITATIONS = ["not-production-apply", "no-approval-or-certification",
               "status-and-dates-unchanged", "index-is-baseline-copy",
               "code-native-specs-and-other-changes-excluded"]


def regular(path: Path) -> Path:
    path = safe_path(path)
    require(path.is_file(), f"expected regular file: {path}")
    require(path.stat().st_nlink == 1, f"hard-linked input is unsupported: {path}")
    return path


def read_json(path: Path) -> dict:
    data = json.loads(regular(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=check_import.unique_object)
    require(isinstance(data, dict), f"expected JSON object: {path}")
    return data


def header_text(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        return ""
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    require(end is not None, "unterminated frontmatter while discovering machine sidecars")
    return "\n".join(lines[1:end])


def roots(change: Path, factory: Path, source: Path, specs: Path) -> dict[str, str]:
    paths = {key: safe_path(value) for key, value in
             (("change", change), ("factory", factory), ("source", source), ("specs", specs))}
    change = paths["change"]
    for name in ("factory", "source", "specs"):
        root = paths[name]
        require(root.is_dir() or name == "specs" and not root.exists(),
                f"missing/invalid {name} directory: {root}")
        require(change != root and not root.is_relative_to(change),
                f"destination overlaps {name} root: {change}")
    require(not change.is_relative_to(paths["source"]), "destination is inside native source")
    require(not change.is_relative_to(paths["specs"]), "destination is inside native specs")
    require(not any(part.casefold() in {".git", ".work", "03-codemap"} for part in change.parts),
            "destination is inside protected code/service storage")
    if change.is_relative_to(paths["factory"]):
        require(change.parent == paths["factory"] / "changes" and change.name.casefold() != "archive",
                "destination inside factory must be one change directly under changes/")
    regular(paths["factory"] / "00-masterspec-index.md")
    return {key: str(value) for key, value in paths.items()}


def validate_workspace(path: Path) -> tuple[dict, Path, dict[str, Path]]:
    path = regular(path)
    document = read_json(path)
    run = path.parent
    require(path.name == "workspace.json" and run.parent.name == ".work",
            "workspace must be <destination>/.work/<run>/workspace.json")
    require(document.get("schema_version") == 1 and document.get("kind") == "openspec-prepare",
            "unsupported workspace manifest")
    require(document.get("run") == run.name and document.get("work_root") == str(run) and
            document.get("write_roots") == [str(run)], "workspace write root mismatch")
    source_paths = document.get("paths")
    require(isinstance(source_paths, dict) and
            set(source_paths) == {"change", "factory", "source", "specs"}, "invalid workspace paths")
    require(all(isinstance(value, str) for value in source_paths.values()), "invalid workspace path")
    current = roots(**{key: Path(value) for key, value in source_paths.items()})
    require(current == source_paths and Path(current["change"]) == run.parent.parent,
            "workspace provenance/path mismatch")
    return document, run, {key: Path(value) for key, value in current.items()}


def init_workspace(change: Path, factory: Path, source: Path, specs: Path,
                   run: str | None = None) -> dict:
    identity = roots(change, factory, source, specs)
    change = Path(identity["change"])
    if run is None:
        run = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run) is not None,
            "run must be one safe directory name (letters, digits, _ and -)")
    SCOPE.relative_path(run)
    workspace = safe_path(change / ".work" / run)
    require(not workspace.exists(), f"workspace already exists: {workspace}")
    if change.exists():
        require(change.is_dir(), "destination must be a directory")
        if any(change.iterdir()):
            matching = False
            work = safe_path(change / ".work")
            if work.exists():
                require(work.is_dir(), ".work must be a directory")
                for candidate in sorted(work.iterdir()):
                    candidate = safe_path(candidate)
                    if candidate.is_dir() and (candidate / "workspace.json").exists():
                        previous, _, _ = validate_workspace(candidate / "workspace.json")
                        require(previous["paths"] == identity, "destination has different provenance")
                        matching = True
            snapshot = safe_path(change / "source-inventory.json")
            if snapshot.exists() and not matching:
                check_saved(regular(snapshot), inventory(Path(identity["source"]), Path(identity["specs"])))
                matching = True
            require(matching, "occupied destination has no matching workspace or source inventory")
    document = {"schema_version": 1, "kind": "openspec-prepare", "run": run,
                "paths": identity, "work_root": str(workspace), "write_roots": [str(workspace)],
                "limitations": LIMITATIONS}
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "logs").mkdir()
    manifest = workspace / "workspace.json"
    with manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return {"result": "workspace-created", "workspace": str(manifest), **document}


def spec_slice(factory: Path) -> dict[str, bytes]:
    """Read Markdown and declared sidecars only; never recurse outside allowed layers."""
    result = {}

    def visit(path: Path) -> None:
        path = safe_path(path)
        relative = path.relative_to(factory).as_posix()
        if path.is_dir():
            for child in sorted(path.iterdir()):
                require(child.name not in {".git", ".work", "changes", "03-codemap"},
                        f"unexpected service/code directory in specification layer: {child}")
                visit(child)
        elif path.suffix == ".md":
            if relative != "00-masterspec-index.md":
                SCOPE.target_path(relative)
            result[relative] = regular(path).read_bytes()

    visit(factory / "00-masterspec-index.md")
    for name in ["00-glossary.md", *sorted(SCOPE.LAYERS)]:
        candidate = safe_path(factory / name)
        if candidate.exists():
            visit(candidate)
    for relative, content in list(result.items()):
        if relative in {"00-masterspec-index.md", "00-glossary.md"}:
            continue
        text = content.decode("utf-8-sig")
        header = header_text(text)
        # Unchanged legacy Markdown does not acquire new metadata requirements.
        # A declared machine pair still needs an unambiguous bounded sidecar.
        if re.search(r"(?m)^.*\bsidecar(?:_format)?\b.*:", header):
            metadata = SCOPE.frontmatter(factory / relative)
            slug = metadata.get("slug")
            require(isinstance(slug, str) and bool(slug), f"sidecar companion has no slug: {relative}")
            machine = SCOPE.sidecar(metadata, slug)
            if machine:
                name = (Path(relative).parent / machine).as_posix()
                SCOPE.target_path(name)
                result[name] = regular(factory / name).read_bytes()
    return result


def draft_snapshot(change: Path) -> dict[str, str]:
    result = {name: digest(regular(change / name).read_bytes())
              for name in ("change.md", "source-inventory.json", "import-map.json")}
    staging = safe_path(change / "new")
    if staging.exists():
        require(staging.is_dir(), "new/ must be a directory")
        for path in sorted(staging.iterdir()):
            SCOPE.relative_path(path.name)
            result["new/" + path.name] = digest(regular(path).read_bytes())
    return result


def section_range(text: str, selector: str) -> tuple[int, int, int]:
    """Return body line bounds and level, ignoring fenced examples and comments."""
    original, visible = visible_lines(text)
    # Frontmatter is metadata, never the body of a normal diff operation.
    if original and original[0].lstrip("\ufeff") == "---":
        end = next((i for i in range(1, len(original)) if original[i] == "---"), None)
        require(end is not None, "unterminated target frontmatter")
        visible[:end + 1] = [""] * (end + 1)
    selector = selector.strip()
    if selector.startswith("`") and selector.endswith("`") and selector.count("`") == 2:
        selector = selector[1:-1]
    chain = [SCOPE.literal(part) for part in selector.split("→")]
    lower, upper, level = 0, len(visible), 1
    for heading in chain:
        match = re.fullmatch(r"(#{2,6})\s+\S.*", heading)
        require(match is not None and len(match[1]) > level, f"invalid heading route: {selector}")
        level = len(match[1])
        positions = [i for i in range(lower, upper) if visible[i] == heading]
        require(len(positions) == 1, f"section missing or ambiguous: {selector}")
        lower = positions[0] + 1
        upper = next((i for i in range(lower, upper)
                      if re.match(rf"^#{{1,{level}}}\s", visible[i])), upper)
    return lower, upper, level


def diff_blocks(text: str) -> list[dict[str, str]]:
    original, visible = visible_lines(text)
    starts = [i for i, line in enumerate(visible) if re.match(r"^##\s+4(?:\.|\s|$)", line)]
    require(len(starts) == 1, "expected one section 4")
    start = starts[0] + 1
    end = next((i for i in range(start, len(visible)) if re.match(r"^#{1,2}\s", visible[i])), len(visible))
    blocks = [i for i in range(start, end) if re.match(r"^#{3,4}\s+4\.\d+(?:\.|\s|$)", visible[i])]
    result = []
    for left, right in zip(blocks, [*blocks[1:], end]):
        record = {}
        for field, key in (("Файл", "path"), ("Раздел", "section"), ("Тип правки", "operation")):
            values = []
            for line in visible[left + 1:right]:
                normalized = line.strip().removeprefix("- ").replace("**", "")
                if normalized.startswith(field + ":"):
                    values.append(normalized.split(":", 1)[1].strip())
            require(len(values) == 1, f"diff block needs exactly one {field}")
            record[key] = values[0]
        record["path"] = SCOPE.target_path(record["path"]).as_posix()
        record["operation"] = SCOPE.literal(record["operation"])
        require(record["operation"] in {"modify-bullet", "replace-section", "add-subsection"},
                f"unsupported projection operation: {record['operation']}")
        for label, key in (("ДО:", "before"), ("ПОСЛЕ:", "after")):
            found = [i for i in range(left + 1, right) if visible[i].strip() == label]
            require(len(found) <= 1, f"duplicate {label} payload")
            if not found:
                require(key == "before" and record["operation"] != "modify-bullet", f"missing {label}")
                record[key] = ""
                continue
            fence_line = found[0] + 1
            while fence_line < right and not original[fence_line].strip():
                fence_line += 1
            marker = re.fullmatch(r"\s{0,3}(`{3,}|~{3,})([^\n]*)", original[fence_line]) if fence_line < right else None
            require(marker is not None, f"{label} must use a fenced payload")
            closing = next((i for i in range(fence_line + 1, right)
                            if re.fullmatch(r"\s{0,3}" + re.escape(marker[1][0]) +
                                            "{" + str(len(marker[1])) + r",}\s*", original[i])), None)
            require(closing is not None, f"unterminated {label} payload")
            record[key] = "\n".join(original[fence_line + 1:closing])
        result.append(record)
    return result


def apply_block(data: bytes, block: dict[str, str]) -> bytes:
    text = data.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    start, end, level = section_range(text, block["section"])
    newline = "\r\n" if "\r\n" in text else "\n"
    after = block["after"].splitlines()
    _, after_visible = visible_lines(block["after"])
    require(not any(re.match(rf"^#{{1,{level}}}\s", line) for line in after_visible),
            "payload escapes its selected section")
    operation = block["operation"]
    if operation == "modify-bullet":
        before = block["before"].splitlines()
        require(bool(before), "modify-bullet requires nonempty BEFORE")
        normalized = [line.lstrip(" \t") for line in before]
        candidates = [i for i in range(start, end - len(before) + 1)
                      if [line.rstrip("\r\n").lstrip(" \t") for line in lines[i:i + len(before)]] == normalized]
        require(len(candidates) == 1, f"BEFORE must match exactly once: {block['path']} / {block['section']}")
        left, right = candidates[0], candidates[0] + len(before)
        terminal = lines[right - 1].endswith(("\n", "\r"))
        replacement = [line + newline for line in after]
        if replacement and not terminal:
            replacement[-1] = replacement[-1].rstrip("\r\n")
        lines[left:right] = replacement
    elif operation == "replace-section":
        # BEFORE is review history for this operation; snapshot checks guard drift.
        prefix = [newline] if start < end and not lines[start].strip() else []
        suffix = [newline] if start < end and not lines[end - 1].strip() else []
        lines[start:end] = prefix + [line + newline for line in after] + suffix
    else:
        first = next((line for line in after_visible if line.strip()), "")
        require(re.match(rf"^#{{{level + 1}}}\s+\S", first) is not None,
                "add-subsection must start with a direct child heading")
        _, visible = visible_lines(text)
        require(first not in visible[start:end], "add-subsection heading already exists")
        position = next((i for i in range(start, end) if visible[i].strip() == "---"), end)
        prefix = [] if position > 0 and not lines[position - 1].strip() else [newline]
        lines[position:position] = prefix + [line + newline for line in after] + [newline]
    result = "".join(lines)
    visible_lines(result)  # Reject newly broken fences/comments, never silently truncate.
    return (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + result.encode("utf-8")


def project_plan(change: Path, factory: Path, baseline: dict[str, bytes]) -> dict[str, bytes]:
    text = regular(change / "change.md").read_text(encoding="utf-8-sig")
    lines = SCOPE.markdown_lines(text)
    groups = {operation: SCOPE.declarations(lines, number) for operation, number in
              (("MODIFIED", "2.1"), ("ADDED", "2.2"), ("REMOVED", "2.3"))}
    planned = baseline.copy()
    blocks = diff_blocks(text)
    require({block["path"] for block in blocks} ==
            {path.as_posix() for _, _, path in groups["MODIFIED"] if path.suffix == ".md"},
            "parsed diff targets differ from MODIFIED declarations")
    for block in blocks:
        planned[block["path"]] = apply_block(planned[block["path"]], block)
    removals = set()
    for operation, rows in groups.items():
        for _, slug, relative in rows:
            name = relative.as_posix()
            if operation == "ADDED":
                require(name not in planned, f"ADDED collision: {name}")
                artifact = regular(change / "new" / relative.name)
                planned[name] = artifact.read_bytes()
                metadata = SCOPE.frontmatter(artifact) if name != "00-glossary.md" else {}
                machine = SCOPE.sidecar(metadata, slug)
                if machine:
                    target = (relative.parent / machine).as_posix()
                    require(target not in planned, f"ADDED sidecar collision: {target}")
                    planned[target] = regular(change / "new" / machine).read_bytes()
            elif operation == "REMOVED":
                removals.add(name)
                if relative.suffix == ".md" and name != "00-glossary.md":
                    machine = SCOPE.sidecar(SCOPE.frontmatter(regular(factory / name)), slug)
                    if machine:
                        removals.add((relative.parent / machine).as_posix())
            elif relative.suffix != ".md":
                companion = regular(factory / relative.parent / (slug + ".md"))
                header = header_text(companion.read_text(encoding="utf-8-sig"))
                origins = re.findall(r"(?m)^contract_origin:\s*(.*?)\s*$", header)
                require(len(origins) == 1 and re.fullmatch(r'''(?:authored|"authored"|'authored')(?:\s+#.*)?''', origins[0]),
                        f"projection only supports explicitly authored sidecar replacements: {name}")
                planned[name] = regular(change / "new" / relative.name).read_bytes()
    for name in removals:
        require(name in baseline, f"missing REMOVED target: {name}")
        planned.pop(name)
    return planned


def project_workspace(manifest: Path) -> dict:
    _, workspace, paths = validate_workspace(manifest)
    for name in ("baseline", "after", "projection.json"):
        require(not safe_path(workspace / name).exists(), f"projection output already exists: {name}")
    baseline = spec_slice(paths["factory"])
    # Reject linked inputs before the shared structural checker reads them.
    for name in ("change.md", "source-inventory.json", "import-map.json"):
        regular(paths["change"] / name)
    staging = safe_path(paths["change"] / "new")
    if staging.exists():
        require(staging.is_dir(), "new/ must be a directory")
        for entry in staging.iterdir():
            regular(entry)
    SCOPE.check(paths["change"], paths["factory"])
    draft = draft_snapshot(paths["change"])
    mapping = read_json(paths["change"] / "import-map.json")
    snapshots = mapping.get("target_files")
    require(isinstance(snapshots, list), "target_files must be an array")
    for entry in snapshots:
        require(isinstance(entry, dict), "target snapshot must be an object")
        relative = check_import.mapping_path(entry.get("path"))
        candidate = safe_path(paths["factory"] / relative)
        require(not candidate.exists() or relative.as_posix() in baseline,
                f"snapshot target is outside Markdown/declared sidecar slice: {relative}")
    # Semantic blockers are expected in draft projections. Structural failures,
    # including stale snapshots, still fail closed and never create an after tree.
    report = check_import.diagnose(**paths)
    structural = [item for item in report["diagnostics"] if item["kind"] != "semantic"]
    require(not structural, "import structure blocks projection: " +
            "; ".join(item["message"] for item in structural))
    planned = project_plan(paths["change"], paths["factory"], baseline)
    source_hashes = {name: digest(content) for name, content in baseline.items()}
    result = {"schema_version": 1, "result": "draft-projection", "production_apply": False,
              "approval": False, "workspace": str(workspace / "workspace.json"),
              "baseline": str(workspace / "baseline"), "after": str(workspace / "after"),
              "write_roots": [str(workspace)], "inventory_id": report["inventory_id"],
              "semantic_blockers": [item for item in report["diagnostics"] if item["kind"] == "semantic"],
              "limitations": LIMITATIONS, "index": "baseline-copy",
              "draft_files": draft,
              "baseline_files": source_hashes,
              "after_files": {name: digest(content) for name, content in planned.items()},
              "changed_files": sorted(name for name in baseline.keys() | planned.keys()
                                      if baseline.get(name) != planned.get(name))}
    # Finish the complete plan before writing output. Recheck inputs and exclusive
    # output ownership immediately before materializing; no source files are opened for write.
    require(spec_slice(paths["factory"]) == baseline, "factory changed while projection was planned")
    require(draft_snapshot(paths["change"]) == draft, "draft changed while projection was planned")
    check_saved(regular(paths["change"] / "source-inventory.json"), inventory(paths["source"], paths["specs"]))
    for name, files in (("baseline", baseline), ("after", planned)):
        output = safe_path(workspace / name)
        output.mkdir(exist_ok=False)
        for relative, content in sorted(files.items()):
            target = safe_path(output / relative)
            require(target.is_relative_to(output), "projection output escapes workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
    with (workspace / "projection.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="allocate a bounded workspace before the first log")
    for name in ("change", "factory", "source", "specs"):
        init.add_argument("--" + name, type=Path, required=True)
    init.add_argument("--run", help="optional single directory name; must not exist")
    project = commands.add_parser("project", help="project a structurally valid draft into disposable copies")
    project.add_argument("--workspace", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = init_workspace(**args) if command == "init" else project_workspace(args["workspace"])
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
        print(json.dumps({"result": "blocked", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
