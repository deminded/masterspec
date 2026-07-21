#!/usr/bin/env python3
"""Deterministic gate for masterspec artifact physical layout.

Parses the routing table (artifact-routing.md §1, plus §2 scope/block rules)
into a type -> canonical-directory map and compares it against where
artifacts actually live on disk. `--check` reports misplaced artifacts;
`--fix` plans (dry-run) or applies (`--apply`) moving them into place.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


ROUTING_HEADING = "## 1. Таблица маршрутизации"
STOP_HEADING_PREFIX = "## "
SEPARATOR_CELL = re.compile(r":?-+:?")
ANNOTATION_RE = re.compile(r"\(([^)]+)\)")
BLOCK_PLACEHOLDER_RE = re.compile(r"\[<\w+>/?\]")
HAS_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")

# Тип -> русская аннотация в скобках -> английский ключ поля scope: (`api` внутренний/внешний,
# сейчас единственный случай в реестре — не хардкодим ПУТИ, но словарь аннотаций стабилен).
ANNOTATION_TO_SCOPE = {"внутренний": "internal", "внешний": "external"}

# Рабочие/неканонические каталоги фабрики — не артефакты, не проверяем.
EXCLUDED_DIR_NAMES = frozenset({"recover", ".work", ".research", "changes"})


@dataclass(frozen=True)
class RouteRule:
    """Каноническое размещение для одного или нескольких алиасов `type:`."""

    canonical: str
    dir: str | None = None  # относительно factory-root, без завершающего /
    fixed_file: str | None = None  # относительно factory-root, конкретный файл
    block_field: bool = False  # function/fn: вложенная поддиректория по `block:`
    scope_dirs: dict[str, str] | None = None  # api: {"internal": ..., "external": ...}
    skip: bool = False  # не проверяется статически (напр. decision-record/dr)


def _cell_split(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_type_cell(cell: str) -> tuple[list[str], str | None]:
    """`` `api` (внутренний) `` -> (['api'], 'внутренний'); `` `component` / `cmp` `` -> (['component','cmp'], None)."""
    annotation = None
    match = ANNOTATION_RE.search(cell)
    if match:
        annotation = match.group(1).strip()
        cell = cell[: match.start()].strip()
    return [alias.strip().strip("`").strip() for alias in cell.split("/")], annotation


def _build_rule(aliases: list[str], path_cell: str) -> RouteRule:
    canonical = aliases[0]
    cell = path_cell.strip().strip("`").strip()
    if HAS_CYRILLIC_RE.search(cell):
        # Путь описан прозой (напр. dr: "рядом с артефактом-владельцем...") — не проверяемо статически.
        return RouteRule(canonical=canonical, skip=True)
    block_match = BLOCK_PLACEHOLDER_RE.search(cell)
    if block_match:
        base = cell[: block_match.start()].rstrip("/")
        return RouteRule(canonical=canonical, dir=base, block_field=True)
    if cell.endswith(".md"):
        return RouteRule(canonical=canonical, fixed_file=cell)
    return RouteRule(canonical=canonical, dir=cell.rstrip("/"))


def parse_routing_table(text: str) -> list[tuple[list[str], str | None, str]]:
    """Строки §1 как (aliases, annotation, path_cell), в порядке таблицы."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == ROUTING_HEADING)
    except StopIteration as exc:
        raise ValueError(f"routing heading {ROUTING_HEADING!r} not found") from exc

    rows: list[tuple[list[str], str | None, str]] = []
    seen_separator = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith(STOP_HEADING_PREFIX):
            break
        if not stripped.startswith("|"):
            continue
        cells = _cell_split(stripped)
        if not seen_separator:
            if all(SEPARATOR_CELL.fullmatch(cell) for cell in cells):
                seen_separator = True
            continue  # header row, then the separator row itself: neither is data
        if len(cells) < 3:
            continue
        aliases, annotation = _parse_type_cell(cells[0])
        rows.append((aliases, annotation, cells[2]))

    if not rows:
        raise ValueError(f"routing table under {ROUTING_HEADING!r} is empty")
    return rows


def load_routing_map(text: str) -> dict[str, RouteRule]:
    """type-алиас -> RouteRule. Строки с одинаковым набором алиасов и разными аннотациями
    (сейчас — только `api` внутренний/внешний) сливаются в один RouteRule со scope_dirs."""
    groups: dict[tuple[str, ...], list[tuple[str | None, str]]] = {}
    for aliases, annotation, path_cell in parse_routing_table(text):
        groups.setdefault(tuple(aliases), []).append((annotation, path_cell))

    aliases_map: dict[str, RouteRule] = {}
    for alias_tuple, entries in groups.items():
        aliases = list(alias_tuple)
        if len(entries) == 1 and entries[0][0] is None:
            rule = _build_rule(aliases, entries[0][1])
        else:
            scope_dirs: dict[str, str] = {}
            for annotation, path_cell in entries:
                if annotation not in ANNOTATION_TO_SCOPE:
                    raise ValueError(
                        f"unrecognized routing annotation {annotation!r} for type {aliases!r}"
                    )
                base_rule = _build_rule(aliases, path_cell)
                if base_rule.dir is None:
                    raise ValueError(f"scope variant of {aliases!r} must route to a directory")
                scope_dirs[ANNOTATION_TO_SCOPE[annotation]] = base_rule.dir
            rule = RouteRule(canonical=aliases[0], scope_dirs=scope_dirs)
        for alias in aliases:
            aliases_map[alias] = rule
    return aliases_map


def default_routing_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "artifact-routing.md"


# ---------------------------------------------------------------------------
# Frontmatter + factory discovery
# ---------------------------------------------------------------------------


def frontmatter_of(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def locate_factory_root(root_arg: Path) -> Path:
    """`root_arg` может САМ быть фабрикой (00-masterspec-index.md в корне) либо родителем,
    содержащим `masterspec/00-masterspec-index.md`."""
    if (root_arg / "00-masterspec-index.md").is_file():
        return root_arg
    nested = root_arg / "masterspec"
    if (nested / "00-masterspec-index.md").is_file():
        return nested
    raise SystemExit(
        f"BLOCKER: cannot locate factory root under {root_arg} (no 00-masterspec-index.md)"
    )


def iter_artifact_files(factory_root: Path):
    for path in sorted(factory_root.rglob("*.md")):
        rel_parts = path.relative_to(factory_root).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if len(rel_parts) == 1 and path.name.startswith("00-"):
            continue
        yield path


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    ok: bool
    expected_dir: str | None  # posix, relative to factory-root; "" == root; None если не вычислим
    expected_file: Path | None  # абсолютный целевой путь для --fix; None если не чиним
    reason: str | None = None


def _relative_dir(path: Path, factory_root: Path) -> str:
    rel = path.parent.relative_to(factory_root).as_posix()
    return "" if rel == "." else rel


def classify(path: Path, factory_root: Path, fm_data: dict, rule: RouteRule) -> Placement | None:
    """None означает: артефакт этого типа не проверяется статически (пропуск, не флаг)."""
    if rule.skip:
        return None

    actual_dir = _relative_dir(path, factory_root)

    if rule.fixed_file:
        expected_file = factory_root / rule.fixed_file
        expected_parent = Path(rule.fixed_file).parent
        expected_dir = "" if expected_parent == Path(".") else expected_parent.as_posix()
        ok = path.resolve() == expected_file.resolve()
        return Placement(ok=ok, expected_dir=expected_dir, expected_file=expected_file)

    if rule.scope_dirs is not None:
        scope = str(fm_data.get("scope") or "").strip()
        if scope not in rule.scope_dirs:
            return Placement(
                ok=False,
                expected_dir=None,
                expected_file=None,
                reason="missing/invalid scope (internal|external) — needs scope",
            )
        expected_dir = rule.scope_dirs[scope]
        return Placement(
            ok=actual_dir == expected_dir,
            expected_dir=expected_dir,
            expected_file=factory_root / expected_dir / path.name,
        )

    if rule.block_field:
        base = rule.dir or ""
        block = str(fm_data.get("block") or "").strip()
        if block:
            expected_dir = f"{base}/{block}"
            return Placement(
                ok=actual_dir == expected_dir,
                expected_dir=expected_dir,
                expected_file=factory_root / expected_dir / path.name,
            )
        # block опционален: и корень, и любой непосредственный подкаталог base — легитимны.
        ok = actual_dir == base or (
            actual_dir.startswith(base + "/") and actual_dir.count("/") == base.count("/") + 1
        )
        return Placement(ok=ok, expected_dir=base, expected_file=factory_root / base / path.name)

    expected_dir = rule.dir or ""
    return Placement(
        ok=actual_dir == expected_dir,
        expected_dir=expected_dir,
        expected_file=factory_root / expected_dir / path.name,
    )


@dataclass(frozen=True)
class Assessment:
    path: Path
    type_value: str
    frontmatter: dict
    placement: Placement


def assess_factory(
    factory_root: Path, aliases: dict[str, RouteRule]
) -> tuple[list[Assessment], int]:
    """Возвращает (misplaced, checked) — checked считает только реально проверенные артефакты
    (тип известен реестру и статически проверяем; фронтматтер/type отсутствуют или тип не в
    реестре -> артефакт молча пропускается и не входит ни в checked, ни в misplaced)."""
    misplaced: list[Assessment] = []
    checked = 0
    for path in iter_artifact_files(factory_root):
        text = path.read_text(encoding="utf-8")
        fm_data = frontmatter_of(text)
        if fm_data is None:
            continue
        type_value = fm_data.get("type")
        if not type_value:
            continue
        rule = aliases.get(str(type_value).strip())
        if rule is None:
            continue
        placement = classify(path, factory_root, fm_data, rule)
        if placement is None:
            continue
        checked += 1
        if not placement.ok:
            misplaced.append(Assessment(path, str(type_value).strip(), fm_data, placement))
    return misplaced, checked


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def run_check(factory_root: Path, aliases: dict[str, RouteRule]) -> int:
    misplaced, checked = assess_factory(factory_root, aliases)
    violations = []
    for item in misplaced:
        entry = {
            "file": item.path.relative_to(factory_root).as_posix(),
            "type": item.type_value,
            "actual_dir": _relative_dir(item.path, factory_root),
            "expected_dir": item.placement.expected_dir,
        }
        if item.placement.reason:
            entry["reason"] = item.placement.reason
        violations.append(entry)

    print(yaml.safe_dump(violations, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip())
    print(f"checked: {checked}, misplaced: {len(violations)}")
    return 1 if violations else 0


# ---------------------------------------------------------------------------
# --fix
# ---------------------------------------------------------------------------


def sidecar_paths(path: Path, fm_data: dict) -> list[Path]:
    """Компаньоны того же артефакта: по полю `sidecar:` если оно есть и локально (без обхода
    каталога), иначе любой файл с тем же basename (slug) рядом, кроме самого .md."""
    declared = fm_data.get("sidecar")
    if declared:
        name = str(declared).strip()
        if name and "/" not in name and "\\" not in name:
            candidate = path.parent / name
            if candidate.is_file():
                return [candidate]
        return []
    stem_prefix = path.stem + "."
    return sorted(
        sibling
        for sibling in path.parent.iterdir()
        if sibling.is_file() and sibling != path and sibling.name.startswith(stem_prefix)
    )


def plan_moves(misplaced: list[Assessment]) -> tuple[list[tuple[Path, Path]], list[Assessment]]:
    moves: list[tuple[Path, Path]] = []
    unfixable: list[Assessment] = []
    for item in misplaced:
        target = item.placement.expected_file
        if target is None:
            unfixable.append(item)
            continue
        moves.append((item.path, target))
        for sidecar in sidecar_paths(item.path, item.frontmatter):
            moves.append((sidecar, target.parent / sidecar.name))
    return moves, unfixable


def run_fix(factory_root: Path, aliases: dict[str, RouteRule], apply: bool) -> int:
    misplaced, checked = assess_factory(factory_root, aliases)
    moves, unfixable = plan_moves(misplaced)

    for src, dst in moves:
        print(f"mv {src} -> {dst}")
    for item in unfixable:
        print(f"SKIP (unfixable): {item.path} — {item.placement.reason}")

    if not apply:
        print(f"checked: {checked}, planned: {len(moves)}, unfixable: {len(unfixable)}")
        return 1 if moves or unfixable else 0

    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    print(f"checked: {checked}, moved: {len(moves)}, unfixable: {len(unfixable)}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(root: Path, fix: bool, apply: bool, routing_path: Path | None = None) -> int:
    routing_text = (routing_path or default_routing_path()).read_text(encoding="utf-8")
    aliases = load_routing_map(routing_text)
    factory_root = locate_factory_root(root)
    if fix:
        return run_fix(factory_root, aliases, apply=apply)
    return run_check(factory_root, aliases)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check/fix physical layout of masterspec factory artifacts against artifact-routing.md"
    )
    parser.add_argument("root", type=Path, help="factory root, or its parent containing masterspec/")
    parser.add_argument("--check", action="store_true", help="report misplaced artifacts (default mode)")
    parser.add_argument("--fix", action="store_true", help="plan (default) or apply layout fixes")
    parser.add_argument("--apply", action="store_true", help="with --fix, actually move files (default: dry-run)")
    args = parser.parse_args()
    return run(args.root, fix=args.fix, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
