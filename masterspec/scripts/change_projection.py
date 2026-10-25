"""Read-only projection of canonical spec-only changes; no native OpenSpec inputs required."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import stat

_spec = importlib.util.spec_from_file_location("projection_scope", Path(__file__).with_name("check-change-scope.py"))
assert _spec and _spec.loader
SCOPE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCOPE)
require = SCOPE.require


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


def regular(path: Path) -> Path:
    path = safe_path(path)
    require(path.is_file(), f"expected regular file: {path}")
    require(path.stat().st_nlink == 1, f"hard-linked input is unsupported: {path}")
    return path


def header_text(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        return ""
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    require(end is not None, "unterminated frontmatter while discovering machine sidecars")
    return "\n".join(lines[1:end])


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
