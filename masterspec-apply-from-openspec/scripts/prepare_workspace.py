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


import importlib.util
_projection_spec = importlib.util.spec_from_file_location(
    "prepare_change_projection", Path(__file__).resolve().parents[2] / "masterspec/scripts/change_projection.py"
)
assert _projection_spec and _projection_spec.loader
_projection = importlib.util.module_from_spec(_projection_spec)
_projection_spec.loader.exec_module(_projection)
regular = _projection.regular
header_text = _projection.header_text
spec_slice = _projection.spec_slice
section_range = _projection.section_range
diff_blocks = _projection.diff_blocks
apply_block = _projection.apply_block
project_plan = _projection.project_plan


SCOPE = check_import.SCOPE
require = SCOPE.require
LIMITATIONS = ["not-production-apply", "no-approval-or-certification",
               "status-and-dates-unchanged", "index-is-baseline-copy",
               "code-native-specs-and-other-changes-excluded"]


def read_json(path: Path) -> dict:
    data = json.loads(regular(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=check_import.unique_object)
    require(isinstance(data, dict), f"expected JSON object: {path}")
    return data


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
        run = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%MZ-") + uuid.uuid4().hex[:8]
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
