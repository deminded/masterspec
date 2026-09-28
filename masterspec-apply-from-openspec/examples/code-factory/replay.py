#!/usr/bin/env python3
"""Replay THIS reviewed fixture in a disposable directory; not a production merger.

The CLI accepts no destination. Production application remains the agent workflow
masterspec-apply-change. Only this fixture's modify-bullet and ADDED forms exist here.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import check_import
from openspec_inventory import check_saved, inventory


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in sorted(path.rglob("*")) if p.is_file()}


def section_bounds(text: str, heading: str) -> tuple[int, int]:
    matches = list(re.finditer(r"(?m)^" + re.escape(heading) + r"$", text))
    if len(matches) != 1:
        raise ValueError(f"section missing or ambiguous: {heading}")
    level = len(heading) - len(heading.lstrip("#"))
    start = matches[0].end() + 1
    end = re.search(r"(?m)^#{1," + str(level) + r"} ", text[start:])
    return start, start + end.start() if end else len(text)


def reindex(files: dict[str, bytes]) -> bytes:
    """Canonical full rebuild for the three artifact types present in this fixture."""
    old = files["00-masterspec-index.md"].decode("utf-8")
    head = old[:old.index("## 1. Паспорт")]
    passport = old[slice(*section_bounds(old, "## 1. Паспорт"))]
    gaps = old[slice(*section_bounds(old, "## 7. Белые пятна и открытые вопросы"))]
    comments = dict(re.findall(r"(?m)^ [+-] `([^`]+)` # (.*)$", old))
    groups = {"function": [], "test-acceptance": [], "component": []}
    for name, content in files.items():
        if name == "00-masterspec-index.md":
            continue
        text = content.decode("utf-8")
        kind = re.search(r"(?m)^type: (.+)$", text)[1]
        if kind not in groups:
            raise ValueError(f"fixture reindex does not support type {kind}")
        slug = re.search(r"(?m)^slug: (.+)$", text)[1]
        status = re.search(r"(?m)^status: (.+)$", text)[1]
        title = re.search(r"(?m)^# (.+)$", text)[1].split(": ", 1)[-1]
        comment = comments.get(name, title)
        groups[kind].append((slug, f" {'+' if status == 'actual' else '-'} `{name}` # {comment}\n"))
    out = head + "## 1. Паспорт\n" + passport
    for layer, entries in (
        ("## 3. Слой требований", (("function", "### 3.2. Функции АС/ФП"),
                                  ("test-acceptance", "### 3.8. Приёмочные тесты"))),
        ("## 4. Слой спецификаций", (("component", "### 4.1. Компоненты и их возможности"),)),
    ):
        out += layer + "\n\n"
        for kind, title in entries:
            if groups[kind]:
                out += title + "\n" + "".join(line for _, line in sorted(groups[kind])) + "\n"
    out += "## 7. Белые пятна и открытые вопросы\n" + gaps
    return out.encode("utf-8")


class Replay:
    """A test-only transaction whose writable project is always owned tempfile storage."""
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="masterspec-openspec-example-")
        self.root = Path(self._temp.name) / "project"
        shutil.copytree(HERE / "before", self.root)
        self.factory = self.root / "masterspec"
        self.change = self.factory / "changes/from-openspec-quote-breakdown"
        shutil.copytree(HERE / "prepared/from-openspec-quote-breakdown", self.change)
        self.source = self.root / "openspec/changes/quote-breakdown"
        self.specs = self.root / "openspec/specs"
        self._untouched = {"openspec": tree(self.root / "openspec"), "src": tree(self.root / "src")}
        self.applied_inventory = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._temp.cleanup()

    def factory_tree(self):
        return {name: data for name, data in tree(self.factory).items() if not name.startswith("changes/")}

    def assert_untouched(self):
        for directory, expected in self._untouched.items():
            if tree(self.root / directory) != expected:
                raise ValueError(f"import modified protected {directory}")

    def apply(self) -> str:
        current = inventory(self.source, self.specs)
        check_saved(self.change / "source-inventory.json", current)
        expected = tree(HERE / "after/masterspec")
        if self.applied_inventory == current["inventory_id"]:
            if self.factory_tree() != expected:
                raise ValueError("applied postconditions drifted: review again")
            self.assert_untouched()
            return "no-op"
        check_import.check(self.change, self.factory, self.source, self.specs)
        planned = self.factory_tree()
        text = (self.change / "change.md").read_text(encoding="utf-8")
        body = text[slice(*section_bounds(text, "## 4. MODIFIED — diff-блоки"))]
        pattern = (r"\*\*Файл\*\*: `([^`]+)`\n\*\*Раздел\*\*: `([^`]+)`\n"
                   r"\*\*Тип правки\*\*: modify-bullet\n\nДО:\n```\n(.*?)\n```"
                   r"\n\nПОСЛЕ:\n```\n(.*?)\n```")
        blocks = re.findall(pattern, body, re.S)
        if len(blocks) != 6:
            raise ValueError("fixture expects exactly six modify-bullet blocks")
        for path, heading, before, after in blocks:
            content = planned[path].decode("utf-8")
            start, end = section_bounds(content, heading)
            section = content[start:end]
            if section.count(before) != 1:
                raise ValueError(f"BEFORE does not match exactly once: {path} / {heading}")
            planned[path] = (content[:start] + section.replace(before, after, 1)
                             + content[end:]).encode("utf-8")
        name = "tc-acc-quote-breakdown.md"
        destination = "01-requirements/08-test-cases/" + name
        if destination in planned:
            raise ValueError("ADDED collision")
        added = (self.change / "new" / name).read_text(encoding="utf-8")
        planned[destination] = added.replace("status: draft\n", "status: actual\n", 1).encode("utf-8")
        planned["00-masterspec-index.md"] = reindex(planned)
        # Check the complete expected result before the first mutation.
        if planned != expected:
            raise ValueError("planned fixture does not match reviewed after/ snapshot")
        for path, content in planned.items():
            target = self.factory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.applied_inventory = current["inventory_id"]
        self.assert_untouched()
        return "applied-in-disposable-example"


def main():
    with Replay() as example:
        print(example.apply())
        print(example.apply())
        print("PASS: expected MasterSpec result; source and code unchanged; no certificate claimed")


if __name__ == "__main__":
    main()
