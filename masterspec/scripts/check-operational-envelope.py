#!/usr/bin/env python3
"""Deterministic hard gate for masterspec operational-envelope coverage."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.dom.minidom as minidom
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from xml.parsers.expat import ExpatError

import yaml


EXPECTED = (
    "OE-LOAD",
    "OE-INPUT",
    "OE-EVIDENCE",
    "OE-SOURCES",
    "OE-SECURITY",
    "OE-RESILIENCE",
    "OE-DELIVERY",
    "OE-CONTROL",
)
CRITICALITY_WEIGHTS = {"low": 1, "medium": 3, "high": 5}
CRITICALITY_RANK = {"low": 1, "medium": 2, "high": 3}
CATALOG_COVERAGE_RANK = {"single-fault": 1, "dependent-pairs": 2, "pairwise": 3}
CRITICALITY_MIN_COVERAGE = {"low": 1, "medium": 2, "high": 3}
FIELD_NAMES = ("Статус", "Контракт", "Основание", "Проверка")
# Дисциплина слоёв: требования code-free. Ловим код-артефакты в полях OE-граней —
# имена файлов (.py), leading-underscore идентификаторы (_RE/_unwrap), SCREAMING_SNAKE-константы.
CODE_ARTIFACT = re.compile(r"\.py\b|\b_[A-Za-z]\w*[A-Za-z0-9]\b|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
BOUNDARY_FIELD = "Внешний инициатор/канал"
INTERNAL_ONLY = "OE: N/A — internal-only"
OE_REF = re.compile(r"->\s*(fn-[a-z0-9-]+)/(?P<oe>OE-[A-Z]+)\b")
SCN_REF = re.compile(r"->\s*(scn-[a-z0-9-]+)\b")
FN_REF = re.compile(r"->\s*(fn-[a-z0-9-]+)\b")
API_REF = re.compile(r"->\s*(api-[a-z0-9-]+)\b")
TC_INT_REF = re.compile(r"->\s*(tc-int-[a-z0-9-]+)\b")
FAULT_REF = re.compile(r"->\s*(tc-flt-[a-z0-9-]+)/(?P<fault>FLT-[A-Z0-9-]+)\b")
COMMENT = re.compile(r"<!--.*?-->", re.S)
PLACEHOLDER = re.compile(r"<[^>]+>|\b(?:TBD|TODO|placeholder)\b|…", re.I)
GENERIC_EXPECTED = re.compile(
    r"\b(?:работает корректно|обработано корректно|корректный результат|как ожидается|как ожидалось)\b",
    re.I,
)

# Форма артефактов спеки (form-detector). notation сценария валидируется по ОТКРЫТОМУ реестру
# scenario-notation-registry.md (ADR-расширяемый), не по зашитому enum. form алгоритма — закрытый
# канонический набор (meta_model §6.3.3 / patterns/sidecar-formats.md).
NOTATIONS_NO_SIDECAR = frozenset({"yaml-graph", "pull-rules"})
NOTATION_SIDECAR_REQUIRED = frozenset({"bpmn"})
DEFAULT_NOTATIONS = frozenset({"yaml-graph", "sequence", "workflow", "bpmn", "pull-rules"})
ALG_FORMS = frozenset({"procedural", "decision-table"})
ALG_FORM_SIDECAR_OK = frozenset({"decision-table"})
# Согласованность notation/form ↔ sidecar_format: объявленный формат обязан соответствовать нотации.
NOTATION_FORMAT_PREFIX = {"bpmn": ("bpmn",), "sequence": ("mermaid", "plantuml"), "workflow": ("mermaid",)}
ALG_FORM_FORMAT_PREFIX = {"decision-table": ("dmn",)}
MIGRATE_TODO = re.compile(r"MIGRATE-TODO|x-migrate-todo", re.I)
CODE_FENCE = re.compile(r"```")
NOTATION_HEADING = re.compile(r"(?m)^###\s+`([a-z0-9-]+)`")
# Мета-секции сценария: ссылка на api тут — не вызов (маппинг/связи/проверка), а описание.
# Исключаются при notation-aware извлечении api-вызовов у ненумерованных нотаций.
SCENARIO_META_SECTIONS = frozenset({
    "Связи",
    "Реализация контракта живой эксплуатации",
    "Реализация контракта живой эксплуатации (OE)",
    "Проверка",
})
# Секции yaml-graph, несущие ВЫЗОВЫ (нумерованные шаги/ветвления). api-ссылка вне них
# (Цель/Предусловия/Постусловия) — не вызов. «Последовательность шагов» — источник нумерации для O_T4.
YAML_GRAPH_STEP_SECTION = "Последовательность шагов"
YAML_GRAPH_CALL_SECTIONS = (YAML_GRAPH_STEP_SECTION, "Ветвления")


@dataclass(frozen=True)
class Facet:
    function: str
    oe: str
    status: str
    criticality: str
    path: Path

    @property
    def ref(self) -> tuple[str, str]:
        return self.function, self.oe

    @property
    def weight(self) -> int:
        return CRITICALITY_WEIGHTS[self.criticality]


@dataclass(frozen=True)
class TestCase:
    slug: str
    kind: str
    criticality: str
    path: Path
    function_refs: set[str]
    oe_refs: set[tuple[str, str]]
    scenario_refs: set[str]
    fault_refs: set[tuple[str, str]]


@dataclass(frozen=True)
class FaultRow:
    fault_id: str
    injection: str
    mode: str
    other_state: str
    expected: str
    feasibility: str
    test: str


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int


def without_comments(text: str) -> str:
    """Remove comments before parsing fields or scanning cross-references."""
    return COMMENT.sub("", text)


def markdown_lines(text: str) -> list[str]:
    """Return Markdown source lines outside fenced code blocks."""
    result: list[str] = []
    fence: str | None = None
    for line in without_comments(text).splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in ("```", "~~~"):
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            result.append("")
            continue
        result.append("" if fence else line)
    return result


def heading_of(line: str, line_number: int) -> Heading | None:
    """Parse an ATX heading without depending on its incidental Markdown styling."""
    stripped = line.lstrip()
    level = len(stripped) - len(stripped.lstrip("#"))
    if not 1 <= level <= 6 or len(stripped) == level or not stripped[level].isspace():
        return None
    title = stripped[level:].strip().rstrip("#").strip()
    return Heading(level, title, line_number)


def headings_in(lines: list[str]) -> list[Heading]:
    return [heading for number, line in enumerate(lines) if (heading := heading_of(line, number))]


def bullet_body(line: str) -> str | None:
    """Normalize all CommonMark unordered-list markers: '-', '*' and '+'."""
    stripped = line.lstrip()
    if len(stripped) < 2 or stripped[0] not in "-*+" or not stripped[1].isspace():
        return None
    return stripped[2:].strip()


def field_start(line: str, allowed: tuple[str, ...]) -> tuple[str, str] | None:
    """Parse `**Field:** value`, `**Field**: value`, or an unbolded equivalent."""
    body = bullet_body(line)
    if body is None:
        return None
    normalized = body.replace("**", "").replace("__", "")
    if ":" not in normalized:
        return None
    name, value = normalized.split(":", 1)
    name = name.strip()
    if name not in allowed:
        return None
    return name, value.strip()


def fields_in(lines: list[str], allowed: tuple[str, ...]) -> dict[str, str]:
    """Collect named list fields and their continuation lines."""
    values: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        parsed = field_start(line, allowed)
        if parsed:
            current, value = parsed
            values.setdefault(current, []).append(value)
            continue
        if current is not None and heading_of(line, 0) is None:
            body = bullet_body(line)
            values[current].append(body if body is not None else line.strip())
    return {name: clean(" ".join(parts)) for name, parts in values.items()}


def clean(value: str) -> str:
    value = PLACEHOLDER.sub("", value)
    return " ".join(value.split()).strip(" -:|")


def slug_of(text: str, path: Path) -> str:
    match = re.search(r"(?m)^slug:\s*(fn-[a-z0-9-]+)\s*$", without_comments(text))
    return match.group(1) if match else path.stem


def frontmatter_value(text: str, name: str) -> str:
    source = without_comments(text)
    if not source.startswith("---\n"):
        return ""
    end = source.find("\n---\n", 4)
    if end < 0:
        return ""
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.*?)\s*$", source[4:end])
    return match.group(1).strip() if match else ""


def frontmatter_parsed(text: str) -> tuple[dict, str | None]:
    """Фронтматтер как YAML-mapping + причина невалидности. Битый фронтматтер НЕ должен молча
    трактоваться как пустой и обходить проверку формы (F1) — возвращаем ошибку, а не {}."""
    source = without_comments(text)
    if not source.startswith("---\n"):
        return {}, "missing frontmatter delimiters"
    end = source.find("\n---\n", 4)
    if end < 0:
        return {}, "unterminated frontmatter"
    try:
        data = yaml.safe_load(source[4:end])
    except yaml.YAMLError as exc:
        return {}, f"invalid YAML frontmatter ({exc.__class__.__name__})"
    if not isinstance(data, dict):
        return {}, "frontmatter is not a mapping"
    return data, None


def frontmatter_map(text: str) -> dict:
    return frontmatter_parsed(text)[0]


def fm(text: str, name: str) -> str:
    """Скалярное значение поля фронтматтера, распарсенного как YAML (пустая строка, если нет)."""
    value = frontmatter_map(text).get(name)
    return "" if value is None else str(value).strip()


def artifact_type(text: str) -> str:
    return frontmatter_value(text, "type")


def criticality_of(text: str, path: Path, errors: list[str]) -> str:
    value = frontmatter_value(text, "criticality")
    if value not in CRITICALITY_WEIGHTS:
        errors.append(
            f"{path}: criticality must be one of {', '.join(CRITICALITY_WEIGHTS)}, got {value!r}"
        )
        return "low"
    return value


def dated(text: str, field: str) -> str:
    value = frontmatter_value(text, field)
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""


def business_reject_codes(text: str, path: Path) -> tuple[set[str], list[str]]:
    match = re.search(
        r"(?im)^\s*-\s*\*\*Business-reject codes:\*\*\s*(.*?)\s*$",
        "\n".join(markdown_lines(text)),
    )
    if not match:
        return set(), [f"{path}: missing explicit Business-reject codes registry"]
    value = match.group(1).strip()
    if re.match(r"^N/A\s*[—-]\s*\S", value, re.I):
        return set(), []
    codes = set(re.findall(r"`([A-Z][A-Z0-9_-]+)`", value))
    if not codes:
        return set(), [f"{path}: Business-reject codes must use backticked codes or reasoned N/A"]
    return codes, []


def scenario_behavioral_lines(text: str) -> list[str]:
    """Строки ПОВЕДЕНЧЕСКОЙ части сценария — без мета-секций (Связи, OE-таблица, Проверка),
    где ссылка на api — описание/маппинг, а не вызов. База и для шагов, и для ненумерованного извлечения."""
    lines = markdown_lines(text)
    headings = headings_in(lines)
    excluded: list[tuple[int, int]] = []
    for heading in headings:
        if heading.title in SCENARIO_META_SECTIONS:
            end = len(lines)
            for following in headings:
                if following.line > heading.line and following.level <= heading.level:
                    end = following.line
                    break
            excluded.append((heading.line, end))
    return [
        line
        for index, line in enumerate(lines)
        if not any(start <= index < stop for start, stop in excluded)
    ]


def scenario_section_lines(text: str, title: str) -> list[str]:
    """Строки тела конкретной секции сценария (по заголовку); [] если секции нет."""
    lines = markdown_lines(text)
    headings = headings_in(lines)
    for heading in headings:
        if heading.title == title:
            return section_lines(lines, heading, headings)
    return []


def scenario_api_steps(text: str) -> dict[str, set[str]]:
    # Нумерованные шаги с api-вызовами ТОЛЬКО из «Последовательность шагов» — оттуда же номера для O_T4.
    result: dict[str, set[str]] = {}
    for line in scenario_section_lines(text, YAML_GRAPH_STEP_SECTION):
        step = re.match(r"^\s*(\d+)\.\s+.*", line)
        if not step:
            continue
        for api in API_REF.findall(line):
            result.setdefault(api, set()).add(step.group(1))
    return result


def scenario_behavioral_apis(text: str) -> set[str]:
    """api-вызовы из поведенческой части (диаграмма/«Участники»/правила) — для ненумерованных нотаций."""
    result: set[str] = set()
    for line in scenario_behavioral_lines(text):
        result.update(API_REF.findall(line))
    return result


def section_lines(lines: list[str], heading: Heading, headings: list[Heading]) -> list[str]:
    end = len(lines)
    for following in headings:
        if following.line > heading.line and following.level <= heading.level:
            end = following.line
            break
    return lines[heading.line + 1 : end]


def scenario_section_apis(text: str, title: str) -> set[str]:
    """api-ссылки из конкретной секции сценария (по заголовку)."""
    return set(API_REF.findall("\n".join(scenario_section_lines(text, title))))


def scenario_call_apis(text: str, notation: str) -> set[str]:
    """api-ВЫЗОВЫ сценария — из call-несущих секций его нотации, не из «всего тела минус meta»
    (иначе ссылка в «Цель»/«Предусловия» ложно считается вызовом): yaml-graph — «Последовательность
    шагов»+«Ветвления»; sequence/workflow/bpmn — «Участники»; pull-rules — строки таблицы правил."""
    if notation in ("sequence", "workflow", "bpmn"):
        return scenario_section_apis(text, "Участники")
    if notation == "pull-rules":
        return {
            api
            for line in scenario_behavioral_lines(text)
            if line.lstrip().startswith("|")
            for api in API_REF.findall(line)
        }
    apis: set[str] = set()
    for title in YAML_GRAPH_CALL_SECTIONS:
        apis |= scenario_section_apis(text, title)
    return apis


def oe_id(title: str) -> str | None:
    match = re.match(r"^(OE-[A-Z]+)\b", title)
    return match.group(1) if match else None


def classify_function(lines: list[str], path: Path) -> tuple[str, list[str]]:
    """Classify the function from its explicit external initiator/channel field."""
    errors: list[str] = []
    boundary = ""
    for line in lines:
        parsed = field_start(line, (BOUNDARY_FIELD,))
        if parsed:
            boundary = clean(parsed[1])
            break
    if not boundary:
        errors.append(
            f"{path}: missing {BOUNDARY_FIELD!r}; cannot determine whether external I/O crosses the system boundary"
        )
        return "unknown", errors
    if re.match(r"^N/A\s*[—-]\s*internal-only$", boundary, re.I):
        return "internal", errors
    if re.match(r"^N/A\b", boundary, re.I):
        errors.append(f"{path}: {BOUNDARY_FIELD} uses N/A but must say 'N/A — internal-only'")
        return "unknown", errors
    return "external", errors


def parse_function(path: Path) -> tuple[str, list[Facet], list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = markdown_lines(text)
    headings = headings_in(lines)
    slug = slug_of(text, path)
    io_kind, errors = classify_function(lines, path)
    criticality = criticality_of(text, path, errors)
    oe_headings = [heading for heading in headings if heading.level == 3 and oe_id(heading.title)]
    present = [oe_id(heading.title) for heading in oe_headings]
    internal_markers = sum(INTERNAL_ONLY in line for line in lines)

    if io_kind == "internal":
        if internal_markers != 1:
            errors.append(f"{path}: internal-only marker occurs {internal_markers} times (expected 1)")
        if oe_headings:
            errors.append(f"{path}: internal-only function must not contain OE facet skeleton")
        return io_kind, [], errors

    if io_kind == "external" and internal_markers:
        errors.append(f"{path}: external-I/O function must not use '{INTERNAL_ONLY}'")

    # For an unclassified function, continue parsing any facets to report all actionable defects.
    for oe in EXPECTED:
        count = present.count(oe)
        if count != 1:
            errors.append(f"{path}: {oe} occurs {count} times (expected 1 for external I/O)")
    unexpected = sorted(set(present) - set(EXPECTED))
    if unexpected:
        errors.append(f"{path}: unexpected OE facets: {', '.join(unexpected)}")

    facets: list[Facet] = []
    for heading in oe_headings:
        oe = oe_id(heading.title)
        if oe not in EXPECTED:
            continue
        values = fields_in(section_lines(lines, heading, headings), FIELD_NAMES)
        for name in FIELD_NAMES:
            if not values.get(name):
                errors.append(f"{path}: {oe} has empty/template field {name}")

        # Дисциплина слоёв: требования не именуют код. Контракт/Основание не должны нести
        # код-артефакты; Основание должно быть каноничным (интервью/измерение/образец/vendor/гипотеза).
        for name in ("Контракт", "Основание"):
            leak = CODE_ARTIFACT.search(values.get(name, ""))
            if leak:
                errors.append(
                    f"{path}: {oe} {name} names a code artifact {leak.group(0)!r} "
                    f"(layer discipline — requirements are code-free)"
                )
        if re.match(r"^\s*код\b", values.get("Основание", ""), re.IGNORECASE):
            errors.append(
                f"{path}: {oe} Основание uses non-canonical 'код' form — "
                f"use интервью/измерение/образец/vendor/гипотеза"
            )

        status = values.get("Статус", "")
        if status == "APPLICABLE":
            if not re.search(r"\bAC-[A-Za-z0-9-]+\b", values.get("Проверка", "")):
                errors.append(f"{path}: {oe} APPLICABLE has no AC in Проверка")
            normalized = "APPLICABLE"
        elif re.match(r"^N/A\s*[—-]\s*\S", status):
            if not re.match(r"^N/A\b", values.get("Проверка", "")):
                errors.append(f"{path}: {oe} N/A must have Проверка: N/A")
            normalized = "N/A"
        elif re.match(r"^OPEN\s*[—-]\s*\S", status):
            errors.append(f"{path}: {oe} is OPEN (blocks spec_ready)")
            normalized = "OPEN"
        else:
            errors.append(f"{path}: {oe} invalid status {status!r}")
            normalized = "INVALID"
        facets.append(Facet(slug, oe, normalized, criticality, path))

    return io_kind, facets, errors


def refs_in(paths: list[Path], pattern: re.Pattern[str] = OE_REF) -> set:
    refs: set = set()
    for path in paths:
        text = "\n".join(markdown_lines(path.read_text(encoding="utf-8")))
        if pattern is OE_REF:
            refs.update((match.group(1), match.group("oe")) for match in pattern.finditer(text))
        else:
            refs.update(match.group(1) for match in pattern.finditer(text))
    return refs


def markdown_files(root: Path, relative: str) -> list[Path]:
    directory = root / relative
    return sorted(directory.rglob("*.md")) if directory.exists() else []


def paths_of_type(root: Path, relative: str, kind: str) -> list[Path]:
    result: list[Path] = []
    for path in markdown_files(root, relative):
        if artifact_type(path.read_text(encoding="utf-8")) == kind:
            result.append(path)
    return result


def validate_step_contract(text: str, path: Path) -> list[str]:
    """Validate the deterministic part of the industrial tc step contract."""
    errors: list[str] = []
    lines = markdown_lines(text)
    headings = headings_in(lines)
    steps_heading = next((h for h in headings if h.title == "Шаги выполнения"), None)
    if steps_heading is None:
        return [f"{path}: missing 'Шаги выполнения' section"]
    body = section_lines(lines, steps_heading, headings)
    starts = [
        index
        for index, line in enumerate(body)
        if re.match(r"^\s*\d+\.\s+\*\*Действие:\*\*\s*\S", line)
    ]
    if not starts:
        return [f"{path}: no executable steps with '**Действие:**'"]
    starts.append(len(body))
    for position, (start, end) in enumerate(zip(starts, starts[1:]), 1):
        block = "\n".join(body[start:end])
        action = re.search(r"\*\*Действие:\*\*\s*(.+)", block)
        test_data = re.search(r"\*\*Тестовые данные:\*\*\s*(.*)", block)
        expected = re.search(r"\*\*Ожидаемый результат:\*\*\s*(.*)", block)
        if not action or not clean(action.group(1)):
            errors.append(f"{path}: step {position} has empty action")
        if not test_data or not clean(test_data.group(1)):
            errors.append(f"{path}: step {position} has empty testData")
        if test_data and re.match(r"^N/A\s*$", test_data.group(1), re.I):
            errors.append(f"{path}: step {position} testData N/A has no reason")
        if not expected:
            errors.append(f"{path}: step {position} has no expectedResult")
        else:
            expected_value = clean(expected.group(1))
            tail = block[expected.end() :]
            if not expected_value:
                expected_value = " ".join(
                    clean(line)
                    for line in tail.splitlines()
                    if bullet_body(line) is not None and clean(line)
                )
            if not expected_value:
                errors.append(f"{path}: step {position} has empty expectedResult")
            elif GENERIC_EXPECTED.search(expected_value):
                errors.append(
                    f"{path}: step {position} expectedResult uses a generic phrase without an oracle"
                )
    return errors


def parse_test_cases(paths: list[Path]) -> tuple[list[TestCase], list[str]]:
    result: list[TestCase] = []
    errors: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        kind = artifact_type(text)
        criticality = criticality_of(text, path, errors)
        result.append(
            TestCase(
                slug=path.stem,
                kind=kind,
                criticality=criticality,
                path=path,
                function_refs=set(FN_REF.findall("\n".join(markdown_lines(text)))),
                oe_refs=refs_in([path]),
                scenario_refs=set(SCN_REF.findall("\n".join(markdown_lines(text)))),
                fault_refs={(m.group(1), m.group("fault")) for m in FAULT_REF.finditer("\n".join(markdown_lines(text)))},
            )
        )
        errors.extend(validate_step_contract(text, path))

        visible = "\n".join(markdown_lines(text))
        error_case = bool(
            re.search(r"(?im)^#.*(?:ошиб|отказ|сбо|error|failure)", visible)
            or re.search(r"(?im)^\s*-\s*Путь:.*(?:ошиб|отказ|сбо|error|failure)", visible)
            or any(fault != "FLT-000" for _, fault in result[-1].fault_refs)
        )
        if error_case:
            if not re.search(r"->\s*fn-[a-z0-9-]+/OE-EVIDENCE\b", visible):
                errors.append(f"{path}: error/failure tc has no OE-EVIDENCE reference")
            if not re.search(
                r"(?im)^\s*\d+\.\s+\*\*Действие:\*\*.*(?:лог|журнал)", visible
            ):
                errors.append(f"{path}: error/failure tc has no separate log-check step")
    return result, errors


def parse_fault_rows(text: str, path: Path) -> tuple[list[FaultRow], list[str]]:
    errors: list[str] = []
    rows: list[FaultRow] = []
    for line in markdown_lines(text):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8 or cells[0] in {"fault-id", "---"} or set(cells[0]) <= {"-", ":"}:
            continue
        if not re.fullmatch(r"FLT-[A-Z0-9-]+", cells[0]):
            continue
        rows.append(
            FaultRow(cells[0], cells[1], cells[2], cells[3], cells[4], cells[6], cells[7])
        )
    if not rows:
        errors.append(f"{path}: fault catalog has no FLT rows")
    ids = [row.fault_id for row in rows]
    duplicates = sorted({fault_id for fault_id in ids if ids.count(fault_id) > 1})
    if duplicates:
        errors.append(f"{path}: duplicate fault-id: {', '.join(duplicates)}")
    outcomes: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        key = (row.injection, row.mode, row.other_state)
        outcomes.setdefault(key, set()).add(clean(row.expected))
    for key, values in outcomes.items():
        if len(values) > 1:
            errors.append(
                f"{path}: same injection/mode/state has conflicting results: {' / '.join(key)} (O_T2)"
            )
    return rows, errors


def load_notations() -> frozenset[str]:
    """Допустимые notation — из открытого реестра (ADR-расширяемый), не из зашитого enum."""
    registry = (
        Path(__file__).resolve().parents[1] / "references" / "scenario-notation-registry.md"
    )
    try:
        values = NOTATION_HEADING.findall(registry.read_text(encoding="utf-8"))
    except OSError:
        return DEFAULT_NOTATIONS
    return frozenset(values) or DEFAULT_NOTATIONS


def resolve_sidecar(companion: Path, declared: str) -> tuple[Path | None, list[str]]:
    """Локальность+владение сайдкара: только basename вида `<slug>.*` рядом с компаньоном, без обхода
    директории (traversal / symlink наружу / Windows-drive). Возвращает РАЗРЕШЁННЫЙ путь для владения."""
    win = PureWindowsPath(declared)
    if (
        declared in ("", ".", "..")
        or "/" in declared or "\\" in declared
        or win.drive or win.root
        or declared != Path(declared).name
    ):
        return None, [f"{companion}: sidecar {declared!r} must be a local filename beside the companion (F2)"]
    if not declared.startswith(companion.stem + "."):
        return None, [f"{companion}: sidecar {declared!r} must share the companion slug ({companion.stem}.*) (F2)"]
    sidecar = companion.parent / declared
    if not sidecar.is_file():
        return None, [f"{companion}: declared sidecar {declared!r} is missing or not a regular file (F2)"]
    real = sidecar.resolve()
    if real.parent != companion.parent.resolve():
        return None, [f"{companion}: sidecar {declared!r} resolves outside the companion directory (F2)"]
    return real, []


def parse_sidecar(sidecar: Path, raw: str, sidecar_format: str) -> list[str]:
    """Парсимость СТРОГО по объявленному sidecar_format; расширение — лишь фолбэк при пустом формате."""
    fmt = sidecar_format.strip().lower()
    ext = sidecar.suffix.lower()
    try:
        if fmt.startswith(("openapi", "asyncapi")) or fmt in ("yaml", "yml") or (not fmt and ext in (".yaml", ".yml")):
            if yaml.safe_load(raw) is None:
                return [f"{sidecar}: sidecar parses to empty YAML (F2)"]
        elif "json-schema" in fmt or fmt == "json" or (not fmt and ext == ".json"):
            json.loads(raw)
        elif fmt.startswith(("bpmn", "dmn", "wsdl")) or fmt == "xml" or (not fmt and ext in (".bpmn", ".dmn", ".xml", ".wsdl")):
            minidom.parseString(raw)
        # прочие объявленные форматы (mermaid/plantuml/protobuf/graphql/avro/…): встроенного валидатора
        # нет — открытый список канона (patterns/sidecar-formats.md). Ограничиваемся структурной проверкой
        # (непустота + отсутствие огородок, уже в check_sidecar); F2 НЕ выдаём, иначе легитимный
        # открытый формат ложно блокируется.
    except (yaml.YAMLError, json.JSONDecodeError, ExpatError) as exc:
        return [f"{sidecar}: does not parse as declared {sidecar_format or ext!r} ({exc.__class__.__name__}) (F2)"]
    return []


def check_sidecar(sidecar: Path, sidecar_format: str) -> list[str]:
    """F2/F3 по РАЗРЕШЁННОМУ пути: непустота, отсутствие markdown-огородок, TODO, парсимость по формату."""
    try:
        raw = sidecar.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return [f"{sidecar}: sidecar unreadable ({exc.__class__.__name__}) (F2)"]
    if not raw.strip():
        return [f"{sidecar}: sidecar is empty (F2)"]
    errors: list[str] = []
    if CODE_FENCE.search(raw):
        errors.append(f"{sidecar}: machine sidecar must not contain markdown fences ``` (F2)")
    if MIGRATE_TODO.search(raw):
        errors.append(f"{sidecar}: open MIGRATE-TODO in sidecar — form incomplete (F3)")
    errors.extend(parse_sidecar(sidecar, raw, sidecar_format))
    return errors


def _companion_todo(text: str, path: Path) -> list[str]:
    # Сырой текст, НЕ markdown_lines: open TODO часто в <!-- ... -->, которые парсер иначе срезает.
    if MIGRATE_TODO.search(text):
        return [f"{path}: open MIGRATE-TODO in companion — form incomplete (F3)"]
    return []


SPEC_FORM_DIRS = (
    "02-specifications/02-scenarios",
    "02-specifications/03-algorithms",
    "02-specifications/04-apis",
    "02-specifications/05-data",
)


def validate_forms(root: Path) -> list[str]:
    """F1 membership + F2 парность/локальность/владение/парсимость сайдкара + F3 открытые MIGRATE-TODO."""
    errors: list[str] = []
    notations = load_notations()
    owner: dict[Path, Path] = {}  # resolved sidecar → компаньон (запрет двойного владения)
    declared: set[Path] = set()  # все объявленные сайдкары (для обратной проверки на сироты)

    def sidecar_common(path: Path, text: str) -> str:
        """Общая часть для всех типов: XOR парности, локальность/владение, парсимость, TODO компаньона."""
        sidecar = fm(text, "sidecar")
        fmt = fm(text, "sidecar_format")
        if bool(sidecar) != bool(fmt):
            errors.append(f"{path}: sidecar and sidecar_format must be declared together, not one alone (F1)")
        if sidecar:
            resolved, errs = resolve_sidecar(path, sidecar)
            errors.extend(errs)
            if resolved is not None:
                declared.add(resolved)
                if resolved in owner:
                    errors.append(f"{path}: sidecar {sidecar!r} already owned by {owner[resolved].name} (F2)")
                else:
                    owner[resolved] = path
                    errors.extend(check_sidecar(resolved, fmt))
        errors.extend(_companion_todo(text, path))
        return sidecar

    for path in markdown_files(root, "02-specifications/02-scenarios"):
        if not path.name.startswith("scn-"):
            continue
        text = path.read_text(encoding="utf-8")
        data, fm_err = frontmatter_parsed(text)
        if fm_err:
            errors.append(f"{path}: unreadable frontmatter — {fm_err} — form checks bypassed (F1)")
            continue
        if data.get("type") not in ("scenario", "scn"):
            errors.append(f"{path}: scn-* file has wrong/absent type — form checks bypassed (F1)")
            continue
        notation = fm(text, "notation")
        fmt = fm(text, "sidecar_format")
        sidecar = sidecar_common(path, text)
        if not notation:
            errors.append(f"{path}: scenario has no notation — form undefined (F1)")
        else:
            if notation not in notations:
                errors.append(f"{path}: notation {notation!r} not in scenario-notation-registry (F1)")
            if notation in NOTATIONS_NO_SIDECAR and sidecar:
                errors.append(f"{path}: notation {notation} is inline — must not declare a sidecar (F1)")
            if notation in NOTATION_SIDECAR_REQUIRED and not sidecar:
                errors.append(f"{path}: notation {notation} requires a sidecar as sole carrier (F1)")
            expected_fmt = NOTATION_FORMAT_PREFIX.get(notation)
            if sidecar and expected_fmt and not fmt.lower().startswith(expected_fmt):
                errors.append(
                    f"{path}: sidecar_format {fmt!r} incompatible with notation {notation} "
                    f"(expected {'/'.join(expected_fmt)}*) (F1)"
                )

    for path in markdown_files(root, "02-specifications/03-algorithms"):
        if not path.name.startswith("alg-"):
            continue
        text = path.read_text(encoding="utf-8")
        data, fm_err = frontmatter_parsed(text)
        if fm_err:
            errors.append(f"{path}: unreadable frontmatter — {fm_err} — form checks bypassed (F1)")
            continue
        if data.get("type") not in ("algorithm", "alg"):
            errors.append(f"{path}: alg-* file has wrong/absent type — form checks bypassed (F1)")
            continue
        form = fm(text, "form")
        fmt = fm(text, "sidecar_format")
        sidecar = sidecar_common(path, text)
        if not form:
            errors.append(f"{path}: algorithm has no form (procedural|decision-table) (F1)")
        else:
            if form not in ALG_FORMS:
                errors.append(f"{path}: form {form!r} not in {sorted(ALG_FORMS)} (F1)")
            if sidecar and form not in ALG_FORM_SIDECAR_OK:
                errors.append(f"{path}: form {form} is inline — must not declare a sidecar (F1)")
            expected_fmt = ALG_FORM_FORMAT_PREFIX.get(form)
            if sidecar and expected_fmt and not fmt.lower().startswith(expected_fmt):
                errors.append(
                    f"{path}: sidecar_format {fmt!r} incompatible with form {form} "
                    f"(expected {'/'.join(expected_fmt)}*) (F1)"
                )

    for relative in ("02-specifications/04-apis", "02-specifications/05-data"):
        for path in markdown_files(root, relative):
            text = path.read_text(encoding="utf-8")
            _, fm_err = frontmatter_parsed(text)
            if fm_err:
                errors.append(f"{path}: unreadable frontmatter — {fm_err} (F1)")
                continue
            sidecar_common(path, text)

    # Обратная сторона: любой не-.md рядом в слое спеки, не объявленный ни одним компаньоном — сирота.
    # Сравнение по РАЗРЕШЁННОМУ пути (declared хранит resolved), иначе symlink/относительность разойдутся.
    for relative in SPEC_FORM_DIRS:
        directory = root / relative
        if not directory.exists():
            continue
        for file in sorted(directory.rglob("*")):
            if file.is_file() and file.suffix.lower() != ".md" and file.resolve() not in declared:
                errors.append(f"{file}: machine sidecar without a companion declaring it (F2)")

    return errors


def validate_fault_catalogs(
    root: Path, catalogs: list[Path], tests: list[TestCase]
) -> tuple[list[str], int, int]:
    errors: list[str] = []
    tc_by_slug = {test.slug: test for test in tests}
    catalog_by_scenario: dict[str, list[Path]] = {}
    scenario_paths = markdown_files(root, "02-specifications/02-scenarios")
    api_paths = {
        path.stem: path for path in markdown_files(root, "02-specifications/04-apis")
    }
    steps_by_scenario: dict[str, dict[str, set[str]]] = {}
    notation_by_scenario: dict[str, str] = {}
    scenarios_with_api: dict[str, tuple[Path, set[str]]] = {}
    for path in scenario_paths:
        text = path.read_text(encoding="utf-8")
        slug = frontmatter_value(text, "slug") or path.stem
        notation = fm(text, "notation")
        notation_by_scenario[slug] = notation
        # api-вызовы notation-aware из конструкции нотации (scenario_call_apis): yaml-graph — шаги,
        # sequence/workflow/bpmn — «Участники», pull-rules — таблица правил. Ссылка в «Цель»/«Связи» не вызов.
        step_apis = scenario_api_steps(text)
        steps_by_scenario[slug] = step_apis
        referenced_apis = scenario_call_apis(text, notation)
        missing_apis = referenced_apis - set(api_paths)
        for api in sorted(missing_apis):
            errors.append(f"{path}: scenario references missing api {api}")
        external_apis = {
            api
            for api in referenced_apis
            if api in api_paths
            and frontmatter_value(api_paths[api].read_text(encoding="utf-8"), "scope") == "external"
        }
        if external_apis:
            scenarios_with_api[slug] = (path, external_apis)

    total_feasible = 0
    covered_feasible = 0
    known_fault_refs: set[tuple[str, str]] = set()
    for path in catalogs:
        text = path.read_text(encoding="utf-8")
        errors_local: list[str] = []
        criticality = criticality_of(text, path, errors_local)
        coverage = frontmatter_value(text, "coverage")
        if coverage not in CATALOG_COVERAGE_RANK:
            errors_local.append(f"{path}: invalid fault coverage {coverage!r}")
        elif CATALOG_COVERAGE_RANK[coverage] < CRITICALITY_MIN_COVERAGE[criticality]:
            errors_local.append(
                f"{path}: coverage {coverage} is below minimum for criticality {criticality}"
            )
        scenario_refs = set(SCN_REF.findall("\n".join(markdown_lines(text))))
        if len(scenario_refs) != 1:
            errors_local.append(f"{path}: fault catalog must reference exactly one scenario")
        for scenario in scenario_refs:
            catalog_by_scenario.setdefault(scenario, []).append(path)
        rows, row_errors = parse_fault_rows(text, path)
        errors_local.extend(row_errors)
        catalog_slug = frontmatter_value(text, "slug") or path.stem
        known_fault_refs.update((catalog_slug, row.fault_id) for row in rows)

        # O_T4/O_T1 — из ТОЧНЫХ api-ссылок точки инъекции (не подстрокой, не по всему каталогу):
        # substring ловил бы api-a в «-> api-a-v2», а упоминание в заголовке засчитывалось бы за вызов.
        injection_apis: set[str] = set()
        for row in rows:
            row_apis = set(API_REF.findall(row.injection))
            if len(row_apis) > 1:
                errors_local.append(
                    f"{path}: {row.fault_id} injection resolves to >1 api {sorted(row_apis)} — ambiguous (O_T4)"
                )
            injection_apis |= row_apis
        for scenario in scenario_refs:
            expected_apis = scenarios_with_api.get(scenario, (path, set()))[1]
            for api in sorted(expected_apis - injection_apis):
                errors_local.append(f"{path}: missing derived api reference {api}")
            for api in sorted(expected_apis):
                api_rows = [row for row in rows if api in set(API_REF.findall(row.injection))]
                modes = {row.mode for row in api_rows}
                for mode in ("unavailable", "tech-error"):
                    if mode not in modes:
                        errors_local.append(f"{path}: {api} has no mandatory mode {mode} (O_T1)")
                api_path = api_paths.get(api)
                if api_path:
                    business_codes, registry_errors = business_reject_codes(
                        api_path.read_text(encoding="utf-8"), api_path
                    )
                    errors_local.extend(registry_errors)
                    for code in sorted(business_codes):
                        if f"business-reject:{code}" not in modes:
                            errors_local.append(
                                f"{path}: {api} has no business-reject:{code} row (O_T1)"
                            )
                # Резолвинг fault→scn notation-aware. Точность «шаг N» применима ТОЛЬКО там, где у api
                # есть нумерованные шаги («Последовательность шагов»). api, вызываемый лишь в «Ветвления»
                # (нет номера шага) или в ненумерованных нотациях — достаточно, что строка инъектирует
                # реально вызываемый api (уже проверено через api_rows/expected), номер шага не требуем.
                valid_steps = steps_by_scenario.get(scenario, {}).get(api, set())
                if notation_by_scenario.get(scenario) == "yaml-graph" and valid_steps:
                    for row in api_rows:
                        match = re.search(r"\bшаг\s+(\d+)\b", row.injection, re.I)
                        if not match or match.group(1) not in valid_steps:
                            errors_local.append(
                                f"{path}: {row.fault_id} does not resolve to a scenario step for {api} (O_T4)"
                            )
            for api in sorted(injection_apis - expected_apis):
                errors_local.append(f"{path}: api {api} is not called by scenario {scenario} (O_T4)")

        for row in rows:
            if "TC-TODO" in row.expected or not clean(row.expected):
                errors_local.append(f"{path}: {row.fault_id} has no specified expected result")
            feasible = row.feasibility == "feasible"
            if feasible:
                total_feasible += 1
                refs = set(TC_INT_REF.findall(row.test))
                if not refs:
                    errors_local.append(f"{path}: feasible {row.fault_id} has no tc-int link (O_T6)")
                else:
                    covered_feasible += 1
                for tc_slug in refs:
                    tc = tc_by_slug.get(tc_slug)
                    if tc is None:
                        errors_local.append(f"{path}: {row.fault_id} references missing {tc_slug}")
                    elif (catalog_slug, row.fault_id) not in tc.fault_refs:
                        errors_local.append(
                            f"{path}: {row.fault_id} link is not reciprocated by {tc_slug}"
                        )
            elif not re.match(r"^infeasible\s*[—:-]\s*\S", row.feasibility, re.I):
                errors_local.append(f"{path}: {row.fault_id} infeasible status has no reason")

        source_dates: list[str] = []
        for scenario in scenario_refs:
            if scenario in scenarios_with_api:
                source_dates.append(dated(scenarios_with_api[scenario][0].read_text(encoding="utf-8"), "updated"))
        for api in injection_apis:
            matches = [p for p in markdown_files(root, "02-specifications/04-apis") if p.stem == api]
            source_dates.extend(dated(p.read_text(encoding="utf-8"), "updated") for p in matches)
        catalog_date = dated(text, "updated")
        if source_dates and catalog_date and any(d and d > catalog_date for d in source_dates):
            errors_local.append(f"{path}: catalog is older than a derived scn/api source (O_T5)")
        errors.extend(errors_local)

    for scenario in sorted(scenarios_with_api):
        count = len(catalog_by_scenario.get(scenario, []))
        if count != 1:
            errors.append(f"scenario {scenario} with api calls has {count} fault catalogs (expected 1)")
    for test in tests:
        for ref in sorted(test.fault_refs - known_fault_refs):
            errors.append(f"{test.path}: unresolved fault reference {ref[0]}/{ref[1]}")
    return errors, covered_feasible, total_feasible


def coverage(expected: set[tuple[str, str]], covered: set[tuple[str, str]], facets: dict[tuple[str, str], Facet]) -> tuple[int, int, int, int]:
    covered_expected = expected & covered
    total_weight = sum(facets[ref].weight for ref in expected)
    covered_weight = sum(facets[ref].weight for ref in covered_expected)
    return len(covered_expected), len(expected), covered_weight, total_weight


def percentage(part: int, total: int) -> str:
    # 0/0 — покрытие вакуумно (нечего покрывать), а не полно: честнее n/a, чем ложные 100%.
    return f"{part / total * 100:.2f}%" if total else "n/a"


def scenario_oe_coverage(root: Path) -> tuple[set[tuple[str, str]], dict[str, set[tuple[str, str]]]]:
    by_scenario: dict[str, set[tuple[str, str]]] = {}
    for path in markdown_files(root, "02-specifications/02-scenarios"):
        text = path.read_text(encoding="utf-8")
        slug_match = re.search(r"(?m)^slug:\s*(scn-[a-z0-9-]+)\s*$", without_comments(text))
        slug = slug_match.group(1) if slug_match else path.stem
        by_scenario[slug] = refs_in([path])
    union = set().union(*by_scenario.values()) if by_scenario else set()
    return union, by_scenario


def run(root: Path, scope: str) -> int:
    fn_files = markdown_files(root, "01-requirements/02-functions")
    if not fn_files:
        print(f"BLOCKER: no fn files under {root}/01-requirements/02-functions")
        return 2

    facets: list[Facet] = []
    errors: list[str] = []
    external_count = 0
    internal_count = 0
    function_criticalities: dict[str, str] = {}
    for path in fn_files:
        text = path.read_text(encoding="utf-8")
        function_criticalities[slug_of(text, path)] = frontmatter_value(text, "criticality")
        io_kind, parsed, parse_errors = parse_function(path)
        external_count += io_kind == "external"
        internal_count += io_kind == "internal"
        facets.extend(parsed)
        errors.extend(parse_errors)

    applicable = {facet.ref for facet in facets if facet.status == "APPLICABLE"}
    n_a = {facet.ref for facet in facets if facet.status == "N/A"}
    opened = {facet.ref for facet in facets if facet.status == "OPEN"}

    facets_by_ref = {facet.ref: facet for facet in facets}
    tc_acc_paths = paths_of_type(
        root, "01-requirements/08-test-cases", "test-acceptance"
    )
    tc_acc, tc_errors = parse_test_cases(tc_acc_paths)
    errors.extend(tc_errors)
    tc_refs = set().union(*(test.oe_refs for test in tc_acc)) if tc_acc else set()
    for test in tc_acc:
        for function in sorted(test.function_refs):
            function_criticality = function_criticalities.get(function)
            if function_criticality and test.criticality in CRITICALITY_RANK:
                if CRITICALITY_RANK[test.criticality] < CRITICALITY_RANK.get(function_criticality, 0):
                    errors.append(
                        f"{test.path}: criticality {test.criticality} is below {function} "
                        f"criticality {function_criticality}"
                    )
    for ref in sorted(applicable - tc_refs):
        errors.append(f"uncovered by tc-acc: {ref[0]}/{ref[1]}")

    tc_acc_count, tc_acc_total, tc_acc_weight, tc_acc_total_weight = coverage(
        applicable, tc_refs, facets_by_ref
    )

    unrealized: set[tuple[str, str]] = set()
    uncovered_by_tc_int: set[tuple[str, str]] = set()
    untested_oe_scenarios: set[str] = set()
    untraced: set[tuple[str, str]] = set()
    tc_int_count = tc_int_total = tc_int_weight = tc_int_total_weight = 0
    fault_covered = fault_total = 0
    if scope in ("spec", "code"):
        errors.extend(validate_forms(root))
        scn_refs, refs_by_scenario = scenario_oe_coverage(root)
        unrealized = applicable - scn_refs
        for ref in sorted(unrealized):
            errors.append(f"unrealized in scn: {ref[0]}/{ref[1]}")

        load_expected = {ref for ref in applicable if ref[1] == "OE-LOAD"}
        lp_refs = refs_in(markdown_files(root, "02-specifications/07-load-profiles"))
        for ref in sorted(load_expected - lp_refs):
            errors.append(f"OE-LOAD has no lp: {ref[0]}/{ref[1]}")

        delivery_expected = {ref for ref in applicable if ref[1] == "OE-DELIVERY"}
        api_refs = refs_in(markdown_files(root, "02-specifications/04-apis/external"))
        context_refs = refs_in(markdown_files(root, "01-requirements/05-landscape"))
        for ref in sorted(delivery_expected - api_refs):
            errors.append(f"OE-DELIVERY has no external api: {ref[0]}/{ref[1]}")
        for ref in sorted(delivery_expected - context_refs):
            errors.append(f"OE-DELIVERY has no context path: {ref[0]}/{ref[1]}")

        tc_int_paths = paths_of_type(
            root, "02-specifications/08-test-cases", "test-integration"
        )
        tc_int, tc_int_errors = parse_test_cases(tc_int_paths)
        errors.extend(tc_int_errors)
        for test in tc_int:
            for function in sorted(test.function_refs):
                function_criticality = function_criticalities.get(function)
                if function_criticality and test.criticality in CRITICALITY_RANK:
                    if CRITICALITY_RANK[test.criticality] < CRITICALITY_RANK.get(function_criticality, 0):
                        errors.append(
                            f"{test.path}: criticality {test.criticality} is below {function} "
                            f"criticality {function_criticality}"
                        )
        tc_int_scenarios = set().union(*(test.scenario_refs for test in tc_int)) if tc_int else set()
        untested_oe_scenarios = {
            scenario for scenario, refs in refs_by_scenario.items() if refs
        } - tc_int_scenarios
        for scenario in sorted(untested_oe_scenarios):
            errors.append(f"scn with OE mapping has no tc-int: {scenario}")
        tested_oe = set().union(
            *(refs_by_scenario.get(scenario, set()) for scenario in tc_int_scenarios)
        ) if tc_int_scenarios else set()
        uncovered_by_tc_int = applicable - tested_oe
        for ref in sorted(uncovered_by_tc_int):
            errors.append(f"uncovered by tc-int via scn: {ref[0]}/{ref[1]}")
        tc_int_count, tc_int_total, tc_int_weight, tc_int_total_weight = coverage(
            applicable, tested_oe, facets_by_ref
        )

        fault_catalogs = paths_of_type(
            root, "02-specifications/08-test-cases", "test-fault-catalog"
        )
        for path in fault_catalogs:
            text = path.read_text(encoding="utf-8")
            test_criticality = frontmatter_value(text, "criticality")
            for function in set(FN_REF.findall("\n".join(markdown_lines(text)))):
                function_criticality = function_criticalities.get(function)
                if (
                    test_criticality in CRITICALITY_RANK
                    and function_criticality in CRITICALITY_RANK
                    and CRITICALITY_RANK[test_criticality]
                    < CRITICALITY_RANK[function_criticality]
                ):
                    errors.append(
                        f"{path}: criticality {test_criticality} is below {function} "
                        f"criticality {function_criticality}"
                    )
        fault_errors, fault_covered, fault_total = validate_fault_catalogs(
            root, fault_catalogs, tc_int
        )
        errors.extend(fault_errors)

    if scope == "code":
        trace_refs = refs_in(markdown_files(root, "03-codemap/02-scenario-traces"))
        untraced = applicable - trace_refs
        for ref in sorted(untraced):
            errors.append(f"untraced in code: {ref[0]}/{ref[1]}")

    print(
        "OE metrics: "
        f"functions={len(fn_files)} external_io={external_count} internal_only={internal_count} "
        f"expected_facets={external_count * len(EXPECTED)} applicable={len(applicable)} "
        f"n_a_with_reason={len(n_a)} open={len(opened)} "
        f"tc_acc_coverage={tc_acc_count}/{tc_acc_total}({percentage(tc_acc_count, tc_acc_total)}) "
        f"tc_acc_weighted={tc_acc_weight}/{tc_acc_total_weight}({percentage(tc_acc_weight, tc_acc_total_weight)}) "
        f"uncovered_by_tc={len(applicable - tc_refs)} unrealized_in_spec={len(unrealized)} "
        f"uncovered_by_tc_int={len(uncovered_by_tc_int)} "
        f"tc_int_coverage={tc_int_count}/{tc_int_total}({percentage(tc_int_count, tc_int_total)}) "
        f"tc_int_weighted={tc_int_weight}/{tc_int_total_weight}({percentage(tc_int_weight, tc_int_total_weight)}) "
        f"fault_tc_coverage={fault_covered}/{fault_total}({percentage(fault_covered, fault_total)}) "
        f"untested_oe_scenarios={len(untested_oe_scenarios)} untraced_in_code={len(untraced)}"
    )
    for error in errors:
        print(f"BLOCKER: {error}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="masterspec factory root")
    parser.add_argument("--layer", choices=("req", "spec", "code"), default="req")
    args = parser.parse_args()
    return run(args.root, args.layer)


if __name__ == "__main__":
    sys.exit(main())
