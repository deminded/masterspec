#!/usr/bin/env python3
"""Check the write scope of an evolve/spec-only change (standard library only).

This is a structural gate, not a YAML validator or semantic layer review. It
checks declared targets, diff targets and the new/ inventory. Code instructions
hidden in otherwise allowed prose still require the review in layer-discipline.md.
Legacy/general changes are outside this command's contract.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


LAYERS = {"01-requirements", "02-specifications", "04-decisions"}
CODE_TYPES = {"repo-map", "component-map", "cmap", "scenario-trace", "trace", "data-map", "dmap"}
SIDECAR_TYPES = {"api", "data-schema", "data", "scenario", "scn", "algorithm", "alg"}
FIELDS = {"type", "slug", "sidecar", "sidecar_format", "block", "scope"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def literal(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    require(bool(value) and "`" not in value, f"invalid literal: {value!r}")
    return value


def relative_path(value: str) -> PurePosixPath:
    """Reject escape paths and Windows aliases even when running on POSIX."""
    value = literal(value)
    windows = PureWindowsPath(value)
    require(not windows.drive and not windows.root, f"absolute/drive path: {value}")
    parts = value.replace("\\", "/").split("/")
    for part in parts:
        require(part not in {"", ".", ".."}, f"non-canonical path: {value}")
        require(not any(ord(c) < 32 or c in '<>:"|?*' for c in part), f"unsafe path: {value}")
        require(part == part.rstrip(" ."), f"Windows path alias: {value}")
        require(not re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part),
                f"Windows reserved path: {value}")
    return PurePosixPath(*parts)


def target_path(value: str) -> PurePosixPath:
    path = relative_path(value)
    require(path.as_posix() == "00-glossary.md" or
            (len(path.parts) > 1 and path.parts[0] in LAYERS),
            f"target outside spec-only scope: {value}")
    require(not any(part.lower() in {"design.md", "tasks.md", "03-codemap"} for part in path.parts),
            f"implementation target is forbidden: {value}")
    return path


def bounded_file(root: Path, path: PurePosixPath, *, target: bool = False) -> Path:
    candidate = root.joinpath(*path.parts)
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root.resolve()), f"resolved path escapes root: {candidate}")
    if target:
        target_path(resolved.relative_to(root.resolve()).as_posix())
    return candidate


def markdown_lines(text: str) -> list[str]:
    """Payload headings/fields inside fenced diffs do not declare write targets."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    result = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            result.append("")
        elif marker:
            fence = marker[1]
            result.append("")
        else:
            result.append(line)
    require(fence is None, "unterminated code fence in change.md")
    require("<!--" not in text, "unterminated comment in change.md")
    return result


def section(lines: list[str], number: str, level: int) -> list[str]:
    pattern = re.compile(rf"^{'#' * level}\s+{re.escape(number)}(?:\.|\s|$)")
    starts = [i for i, line in enumerate(lines) if pattern.match(line)]
    require(len(starts) == 1, f"expected exactly one section {number}")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines))
                if re.match(rf"^#{{1,{level}}}\s", lines[i])), len(lines))
    return lines[start:end]


def declarations(lines: list[str], number: str) -> list[tuple[str, str, PurePosixPath]]:
    rows = []
    header_seen = separator_seen = False
    for line in section(section(lines, "2", 2), number, 3):
        stripped = line.strip()
        if not stripped or stripped in {"Нет изменений.", "---"}:
            continue
        require(stripped.startswith("|") and stripped.endswith("|"),
                f"section {number}: expected canonical declaration table, got {stripped!r}")
        # Escaped pipes can occur in the description, never in target fields.
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)[1:-1]]
        if not header_seen:
            require(len(cells) in {5, 6} and cells[:3] == ["#", "Тип", "Slug"]
                    and cells[3].startswith("Путь"), f"section {number}: malformed table header")
            width = len(cells)
            header_seen = True
            continue
        require(len(cells) == width, f"section {number}: malformed table row")
        if not separator_seen:
            require(all(re.fullmatch(r":?-+:?", cell) for cell in cells),
                    f"section {number}: missing table separator")
            separator_seen = True
            continue
        if not any(cells):  # Empty row supplied by tpl-change.md.
            continue
        require(all(cells[:4]), f"section {number}: incomplete declaration")
        kind, slug = literal(cells[1]), literal(cells[2])
        require(re.fullmatch(r"[a-z][a-z0-9-]*", kind) is not None and kind not in CODE_TYPES,
                f"section {number}: invalid/spec-external type {kind!r}")
        require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is not None,
                f"section {number}: invalid slug {slug!r}")
        rows.append((kind, slug, target_path(cells[3])))
    require(not header_seen or separator_seen, f"section {number}: unfinished table")
    return rows


def frontmatter(path: Path) -> dict[str, str]:
    """Read only scope fields in the canonical flat-scalar YAML form.

    This deliberately rejects aliases, merges and complex/quoted keys instead of
    guessing their meaning without a YAML dependency. Other field values are not
    validated here; the normal artifact validators remain required.
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    require(bool(lines) and lines[0] == "---", f"{path}: missing frontmatter")
    require("---" in lines[1:], f"{path}: unterminated frontmatter")
    result = {}
    for line in lines[1:lines[1:].index("---") + 1]:
        if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
            continue
        match = re.fullmatch(r"([a-z][a-z0-9_]*):(?:\s+(.*))?", line)
        require(match is not None, f"{path}: unsupported frontmatter key declaration: {line!r}")
        key, value = match[1], (match[2] or "").strip()
        if key not in FIELDS:
            continue
        require(key not in result, f"{path}: duplicate {key}")
        scalar = re.fullmatch(r'''(?:"([^"\\]*)"|'([^']*)'|([^\s'"\[\]{}&*!|>#]+))(?:\s+#.*)?''', value)
        require(scalar is not None, f"{path}: {key} must be a plain or simply quoted scalar")
        result[key] = next(item for item in scalar.groups() if item is not None)
    return result


def sidecar(metadata: dict[str, str], slug: str) -> str | None:
    if "sidecar" not in metadata:
        require("sidecar_format" not in metadata, f"{slug}: sidecar_format without sidecar")
        return None
    require(metadata.get("type") in SIDECAR_TYPES, f"{slug}: type cannot own a machine sidecar")
    require(bool(metadata.get("sidecar_format")), f"{slug}: missing sidecar_format")
    path = relative_path(metadata["sidecar"])
    require(len(path.parts) == 1 and path.name.startswith(slug + ".") and path.suffix != ".md",
            f"{slug}: sidecar must be a local basename sharing the companion slug")
    return path.name


def routing_types() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Use the existing routing registry rather than a second artifact-type list."""
    registry = Path(__file__).resolve().parents[1] / "references" / "artifact-routing.md"
    aliases = {}
    routes: dict[str, list[str]] = {}
    for line in registry.read_text(encoding="utf-8-sig").splitlines():
        cells = line.strip().strip("|").split("|")
        if not line.startswith("|") or len(cells) != 4:
            continue
        names = re.findall(r"`([a-z][a-z0-9-]*)`", cells[0])
        for name in names:
            if name not in CODE_TYPES and name != "masterspec-index":
                aliases[name] = names[0]
                routes.setdefault(name, []).append(cells[2].strip().strip("`"))
    require(bool(aliases), "cannot read artifact type aliases from routing registry")
    return aliases, routes


def check(change_dir: Path, factory: Path | None = None) -> None:
    change_dir = change_dir.resolve()
    if factory is None:
        require(change_dir.parent.name == "changes", "noncanonical change location: pass --factory")
        factory = change_dir.parent.parent
    factory = factory.resolve()
    change_file = bounded_file(change_dir, PurePosixPath("change.md"))
    lines = markdown_lines(change_file.read_text(encoding="utf-8-sig"))
    scope = [line for line in lines if re.match(r"^>\s*\*\*Область\*\*:", line)]
    require(len(scope) == 1 and re.fullmatch(r">\s*\*\*Область\*\*:\s*spec-only\s*", scope[0]) is not None,
            "expected one '> **Область**: spec-only' marker; general changes use their own workflow")
    groups = {name: declarations(lines, number) for name, number in
              (("MODIFIED", "2.1"), ("ADDED", "2.2"), ("REMOVED", "2.3"))}
    aliases, routes = routing_types()
    targets = [path for rows in groups.values() for _, _, path in rows]
    require(bool(targets), "no declared changes")
    require(len({path.as_posix().casefold() for path in targets}) == len(targets),
            "duplicate/conflicting target declarations")
    for path in targets:
        bounded_file(factory, path, target=True)

    diff_targets = []
    block_files = None
    for line in section(lines, "4", 2):
        if re.match(r"^#{3,4}\s+4\.\d+(?:\.|\s|$)", line):
            require(block_files is None or block_files == 1,
                    "every section 4 diff block must declare one Файл target")
            block_files = 0
        normalized = line.strip().removeprefix("- ").replace("**", "")
        if normalized.startswith("Файл:"):
            require(block_files is not None, "Файл target outside a section 4 diff block")
            block_files += 1
            diff_targets.append(target_path(normalized.split(":", 1)[1]))
    require(block_files is None or block_files == 1,
            "every section 4 diff block must declare one Файл target")
    modified_md = {path for _, _, path in groups["MODIFIED"] if path.suffix == ".md"}
    require(set(diff_targets) == modified_md, "section 4 targets must match MODIFIED Markdown declarations")

    expected_new: set[str] = set()
    new_dir = bounded_file(change_dir, PurePosixPath("new"))

    def reserve_new(name: str) -> Path:
        require(name.casefold() not in {item.casefold() for item in expected_new},
                f"colliding new/ filename: {name}")
        expected_new.add(name)
        return bounded_file(new_dir, PurePosixPath(name))

    for operation, rows in groups.items():
        for kind, slug, path in rows:
            require(kind in aliases, f"unknown or non-specification artifact type: {kind}")
            if operation == "ADDED":
                require(not bounded_file(factory, path, target=True).exists(),
                        f"ADDED target already exists: {path}")
            if path.suffix == ".md":
                require(path.name == slug + ".md" or path.as_posix() == "00-glossary.md",
                        f"filename must match slug: {path}")
                source = reserve_new(path.name) if operation == "ADDED" else bounded_file(factory, path, target=True)
                require(source.is_file(), f"missing {operation} artifact: {source}")
                if path.as_posix() == "00-glossary.md":
                    require(kind == "glossary", "00-glossary.md requires glossary type")
                    continue  # Singleton glossary has no mandatory frontmatter.
                metadata = frontmatter(source)
                require(metadata.get("slug") == slug and
                        aliases.get(metadata.get("type")) == aliases[kind],
                        f"{source}: companion slug/type does not match spec-only declaration")
                if "block" in metadata:
                    require(len(relative_path(metadata["block"]).parts) == 1,
                            f"{source}: block must be a local directory name")
                if metadata.get("type") == "api":
                    require(metadata.get("scope") in {"internal", "external"},
                            f"{source}: API scope must be internal or external")
                if operation == "ADDED" and aliases[kind] != "decision-record":
                    # apply-change routes new artifacts by metadata. The declared
                    # path must equal that destination, including scope/block.
                    expected = []
                    for route in routes[kind]:
                        if aliases[kind] == "api" and not route.endswith(metadata["scope"] + "/"):
                            continue
                        block = metadata.get("block", "")
                        route = route.replace("[<block>/]", block + "/" if block else "")
                        destination = route if route.endswith(".md") else route + path.name
                        expected.append(target_path(destination))
                    require(path in expected, f"{source}: declared target does not match metadata routing")
                machine = sidecar(metadata, slug)
                if machine:
                    machine_target = bounded_file(factory, target_path(str(path.parent / machine)), target=True)
                    if operation == "ADDED":
                        require(not machine_target.exists(), f"ADDED sidecar already exists: {machine_target}")
                        reserve_new(machine)
            else:
                require(operation != "ADDED", "ADDED machine sidecar must be declared by its Markdown companion")
                companion = bounded_file(factory, path.parent / (slug + ".md"), target=True)
                metadata = frontmatter(companion)
                require(metadata.get("slug") == slug and
                        aliases.get(metadata.get("type")) == aliases[kind] and
                        sidecar(metadata, slug) == path.name,
                        f"{path}: target is not the companion's declared sidecar")
                require(bounded_file(factory, path, target=True).is_file(), f"missing existing sidecar: {path}")
                if operation == "MODIFIED":
                    reserve_new(path.name)

    listed_new: set[str] = set()
    for line in section(lines, "5", 2):
        if not line.strip() or line.strip() in {"Нет изменений.", "---"}:
            continue
        item = re.fullmatch(r"\s*-\s+(?:\([^\n)]+\)\s+)?(?:`([^`]+)`|(\S+))(?:\s+.*)?", line)
        require(item is not None, f"section 5: expected '- `new/<basename>` — purpose', got {line!r}")
        path = relative_path(item[1] or item[2])
        require(len(path.parts) == 2 and path.parts[0] == "new", f"section 5: invalid staging path {path}")
        require(path.name not in listed_new, f"section 5: duplicate staging file {path}")
        listed_new.add(path.name)
    require(listed_new == expected_new,
            f"section 5 must list every declared new/ file (including sidecar replacements); "
            f"missing={sorted(expected_new - listed_new)}, undeclared={sorted(listed_new - expected_new)}")

    actual_new: set[str] = set()
    if new_dir.exists():
        require(new_dir.is_dir(), "new/ must be a directory")
        for entry in new_dir.iterdir():
            relative_path(entry.name)
            bounded_file(new_dir, PurePosixPath(entry.name))
            require(entry.is_file() and not entry.is_symlink(), f"new/ only accepts regular files: {entry}")
            actual_new.add(entry.name)
    require(actual_new == expected_new,
            f"new/ inventory mismatch; missing={sorted(expected_new - actual_new)}, "
            f"undeclared={sorted(actual_new - expected_new)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("change_dir", type=Path, help="evolve change directory containing change.md")
    parser.add_argument("--factory", type=Path, help="factory root; default: parent of canonical changes/")
    args = parser.parse_args()
    try:
        check(args.change_dir, args.factory)
    except (OSError, ValueError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 1
    print("PASS: spec-only path scope and new/ declarations; semantic layer review still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
