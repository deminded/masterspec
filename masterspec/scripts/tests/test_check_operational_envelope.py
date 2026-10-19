from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "check-operational-envelope.py"
SPEC = importlib.util.spec_from_file_location("check_operational_envelope", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


class OperationalEnvelopeCheckerTest(unittest.TestCase):
    EXAMPLE = SCRIPT.parents[1] / "examples" / "operational-envelope-factory"
    FUNCTION = Path("01-requirements/02-functions/fn-send-notification.md")

    def test_decision_record_beside_function_is_reported_and_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            path = root / self.FUNCTION.parent / "dr-channel-ownership.md"
            path.write_text("---\ntype: decision-record\n---\n# Решение\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = CHECKER.run(root, "req")
            self.assertEqual(result, 0, output.getvalue())
            self.assertNotIn("BLOCKER:", output.getvalue())
            self.assertIn(
                f"{path}: пропущен: decision-record рядом с владельцем", output.getvalue()
            )
            self.assertIn("functions=2 external_io=1 internal_only=1", output.getvalue())

    def test_unknown_file_in_functions_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            path = root / self.FUNCTION.parent / "notes.md"
            # Даже тело корректной internal-only функции не легализует неизвестный артефакт.
            path.write_text(
                "# Заметки\n- **Внешний инициатор/канал:** N/A — internal-only\n"
                "criticality: low\nOE: N/A — internal-only\n", encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = CHECKER.run(root, "req")
            self.assertEqual(result, 1, output.getvalue())
            self.assertTrue(
                any(str(path) in line and line.startswith("BLOCKER:")
                    for line in output.getvalue().splitlines()), output.getvalue(),
            )

    def test_real_function_without_oe_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            path = root / self.FUNCTION.parent / "fn-empty.md"
            path.write_text(
                "---\ntype: function\ncriticality: low\n---\n"
                "- **Внешний инициатор/канал:** внешний клиент\n", encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = CHECKER.run(root, "req")
            self.assertEqual(result, 1, output.getvalue())
            blockers = [line for line in output.getvalue().splitlines()
                        if line.startswith("BLOCKER:") and str(path) in line]
            for facet in CHECKER.EXPECTED:
                self.assertTrue(any(facet in line for line in blockers), blockers)

    def test_function_identity_by_type_alias_slug_or_filename(self) -> None:
        identities = (
            ("function", "notes", "notes"), ("fn", "notes", "notes"),
            ('"function"', "notes", "notes"),
            ("", "fn-extra", "notes"), ("", "", "fn-extra"),
        )
        for kind, slug, filename in identities:
            with self.subTest(kind=kind, slug=slug, filename=filename):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / self.FUNCTION.parent / f"block/{filename}.md"
                    path.parent.mkdir(parents=True)
                    path.write_text(
                        f"---\ntype: {kind}\nslug: {slug}\ncriticality: low\n---\n"
                        "- **Внешний инициатор/канал:** N/A — internal-only\n"
                        "OE: N/A — internal-only\n", encoding="utf-8",
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = CHECKER.run(root, "req")
                    self.assertEqual(result, 0, output.getvalue())
                    self.assertIn("functions=1", output.getvalue())

    def test_decision_record_identity_is_shared_by_all_markdown_walks(self) -> None:
        identities = (
            ("decision-record", "notes", "notes"), ("dr", "notes", "notes"),
            ('"dr"', "notes", "notes"),
            ("", "dr-choice", "notes"), ("", "", "dr-choice"),
        )
        relatives = (
            "01-requirements/02-functions/block", "01-requirements/05-landscape",
            "01-requirements/08-test-cases", "02-specifications/01-components",
            *CHECKER.SPEC_FORM_DIRS, "02-specifications/07-load-profiles",
            "02-specifications/08-test-cases", "03-codemap/02-scenario-traces",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in relatives:
                for kind, slug, filename in identities:
                    with self.subTest(relative=relative, kind=kind, slug=slug, filename=filename):
                        path = root / relative / f"{filename}.md"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(
                            f"---\ntype: {kind}\nslug: {slug}\n---\n# Решение\n",
                            encoding="utf-8",
                        )
                        output = io.StringIO()
                        with redirect_stdout(output):
                            paths = CHECKER.markdown_files(root, relative)
                        self.assertEqual(paths, [])
                        self.assertIn("пропущен: decision-record рядом с владельцем", output.getvalue())
                        path.unlink()

    def test_decision_record_beside_scenario_does_not_trigger_fault_or_oe_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            path = root / "02-specifications/02-scenarios/dr-channel.md"
            path.write_text(
                "---\ntype: decision-record\nnotation: yaml-graph\n---\n"
                "## Последовательность шагов\n1. Обсуждался -> api-missing\n"
                "## Реализация контракта живой эксплуатации\n-> fn-other/OE-LOAD\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = CHECKER.run(root, "spec")
            self.assertEqual(result, 0, output.getvalue())
            self.assertIn("пропущен: decision-record рядом с владельцем", output.getvalue())

    def test_decision_record_references_cannot_supply_coverage(self) -> None:
        relatives = (
            "02-specifications/02-scenarios", "02-specifications/07-load-profiles",
            "02-specifications/04-apis/external", "01-requirements/05-landscape",
            "03-codemap/02-scenario-traces",
        )
        for relative in relatives:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory) / "factory"
                    shutil.copytree(self.EXAMPLE, root)
                    # Ссылки бывшего владельца остались только в решении: покрытие утрачено.
                    owner = next((root / relative).glob("*.md"))
                    text = owner.read_text(encoding="utf-8")
                    owner.unlink()
                    (owner.parent / "dr-choice.md").write_text(
                        "---\ntype: dr\n---\n" + text.split("---\n", 2)[-1], encoding="utf-8",
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = CHECKER.run(root, "code")
                    self.assertEqual(result, 1, output.getvalue())
                    expected = {
                        "02-scenarios": "unrealized in scn:",
                        "07-load-profiles": "OE-LOAD has no lp:",
                        "external": "OE-DELIVERY has no external api:",
                        "05-landscape": "OE-DELIVERY has no context path:",
                        "02-scenario-traces": "untraced in code:",
                    }[Path(relative).name]
                    self.assertIn(expected, output.getvalue())

    def test_removed_acceptance_definition_blocks_and_reduces_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            before = io.StringIO()
            with redirect_stdout(before):
                self.assertEqual(CHECKER.run(root, "spec"), 0)
            path = root / self.FUNCTION
            text = path.read_text(encoding="utf-8")
            path.write_text(
                "\n".join(line for line in text.splitlines() if not line.startswith("- AC-04:")) + "\n",
                encoding="utf-8",
            )
            after = io.StringIO()
            with redirect_stdout(after):
                self.assertEqual(CHECKER.run(root, "spec"), 1)
            report = after.getvalue()
            self.assertIn("OE-RESILIENCE unresolved AC AC-04", report)
            self.assertIn("tc_acc_coverage=6/7(85.71%)", report)
            self.assertIn("tc_acc_weighted=18/21(85.71%)", report)
            self.assertIn("tc_int_coverage=6/7(85.71%)", report)
            self.assertIn("uncovered_by_tc=1", report)
            self.assertIn("uncovered_by_tc_int=1", report)

    def test_acceptance_references_must_all_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fn-send-notification.md"
            text = (self.EXAMPLE / self.FUNCTION).read_text(encoding="utf-8")
            path.write_text(text.replace("Проверка:** AC-01", "Проверка:** AC-01, AC-99", 1), encoding="utf-8")
            _, facets, errors = CHECKER.parse_function(path)
            self.assertTrue(any("OE-LOAD unresolved AC AC-99" in error for error in errors), errors)
            load = next(facet for facet in facets if facet.oe == "OE-LOAD")
            self.assertEqual(load.status, "APPLICABLE")
            self.assertFalse(load.acceptance_resolved)

    def test_incidental_mentions_are_not_acceptance_definitions(self) -> None:
        text = (self.EXAMPLE / self.FUNCTION).read_text(encoding="utf-8")
        actual = "- AC-04: повтор не создаёт дубль, временный отказ соблюдает backoff."
        mentions = (
            "<!-- AC-04: скрытый текст. -->",
            "```text\nAC-04: пример, не критерий.\n```",
            "~~~text\nAC-04: пример, не критерий.\n~~~",
            "- См. AC-04: ссылка на отсутствующий критерий.",
            "- Проверка: AC-04",
            "- -> fn-other/AC-04: чужой критерий.",
            "## Связи\n- AC-04: текст вне раздела приёмки.",
            "> AC-04: цитата не определяет критерий функции.",
            "- AC-04: TODO",
            "### AC-04\n\n## Связи\n- Контракт функции.",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fn-send-notification.md"
            for mention in mentions:
                with self.subTest(mention=mention):
                    path.write_text(text.replace(actual, mention), encoding="utf-8")
                    _, _, errors = CHECKER.parse_function(path)
                    self.assertTrue(any("unresolved AC AC-04" in error for error in errors), errors)

    def test_acceptance_definition_in_another_function_does_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            path = root / self.FUNCTION
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("- AC-04:", "- AC-40:"), encoding="utf-8")
            other = root / "01-requirements/02-functions/fn-calculate-checksum.md"
            other.write_text(other.read_text(encoding="utf-8").replace("AC-01", "AC-04"), encoding="utf-8")
            report = io.StringIO()
            with redirect_stdout(report):
                self.assertEqual(CHECKER.run(root, "req"), 1)
            self.assertIn("OE-RESILIENCE unresolved AC AC-04", report.getvalue())

    def test_alternate_acceptance_ids_and_headings_remain_valid(self) -> None:
        text = (self.EXAMPLE / self.FUNCTION).read_text(encoding="utf-8")
        variants = (
            ("## Критерии приёмки", "- AC-01: проверяемый результат."),
            ("## Критерии приемки", "* **AC-01**: проверяемый результат."),
            ("## **Критерии приёмки**", "+ `AC-01`: проверяемый результат."),
            ("## 6. Критерии приёмки", "1. AC-01. Проверяемый результат."),
            ("## Критерии приёмки (AC)", "- AC-01:\n  проверяемый результат."),
            ("## Acceptance criteria", "### AC-01\nПроверяемый результат."),
            ("## Критерии приёмки", "### AC-01 — Проверяемый результат"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fn-send-notification.md"
            for criterion in ("AC-01", "A6", "AC-sprint-integration"):
                for title, definition in variants:
                    with self.subTest(criterion=criterion, title=title, definition=definition):
                        candidate = text.replace("## Критерии приёмки", title)
                        candidate = candidate.replace(
                            "- AC-01: peak/backlog и оба класса входа обработаны без потери.", definition
                        ).replace("AC-01", criterion)
                        path.write_text(candidate, encoding="utf-8")
                        _, _, errors = CHECKER.parse_function(path)
                        self.assertEqual(errors, [])

    def test_criterion_prefix_does_not_resolve_missing_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fn-send-notification.md"
            text = (self.EXAMPLE / self.FUNCTION).read_text(encoding="utf-8")
            path.write_text(text.replace("- AC-04:", "- AC-04-extra:"), encoding="utf-8")
            _, _, errors = CHECKER.parse_function(path)
            self.assertTrue(any("unresolved AC AC-04" in error for error in errors), errors)

    def test_qualified_acceptance_reference_must_use_owning_function(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fn-send-notification.md"
            text = (self.EXAMPLE / self.FUNCTION).read_text(encoding="utf-8")
            for owner, resolved in (("fn-other", False), ("fn-send-notification", True)):
                with self.subTest(owner=owner):
                    path.write_text(
                        text.replace("Проверка:** AC-01", f"Проверка:** -> {owner}/AC-01", 1),
                        encoding="utf-8",
                    )
                    _, facets, errors = CHECKER.parse_function(path)
                    load = next(facet for facet in facets if facet.oe == "OE-LOAD")
                    self.assertEqual(load.acceptance_resolved, resolved)
                    self.assertEqual(any("belongs to another function" in error for error in errors), not resolved)

    def _test_case_errors(self, directory: str, title: str, extra: str = "") -> list[str]:
        path = Path(directory) / "tc-acc-demo.md"
        path.write_text(
            "---\ntype: test-acceptance\ncriticality: low\n---\n"
            f"# Приёмочный тест: {title}\n{extra}\n"
            "## Шаги выполнения\n"
            "1. **Действие:** Подайте заявку.\n"
            "   **Тестовые данные:** одна заявка.\n"
            "   **Ожидаемый результат:** показан заданный статус.\n",
            encoding="utf-8",
        )
        return CHECKER.parse_test_cases([path])[1]

    def test_explicit_absence_of_failure_does_not_require_error_oracles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for title in (
                "Длинное сообщение получает ноту длины без отказа",
                "Предупреждение не превращается в отказ",
                "Приём сообщения без ошибок",
                "Submission without failure", "No errors on submission", "Сбор данных",
            ):
                with self.subTest(title=title):
                    self.assertEqual(self._test_case_errors(directory, title), [])

    def test_actual_failure_still_requires_evidence_and_log_oracles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for title in (
                "Отказ без потери данных", "Обработка сбоя", "Ошибка валидации",
                "Failure without data loss", "Submission error",
                "Без ошибок на входе, но отказ канала", "Отказ канала без ошибок в журнале",
            ):
                with self.subTest(title=title):
                    errors = self._test_case_errors(directory, title)
                    self.assertTrue(any("no OE-EVIDENCE reference" in error for error in errors), errors)
                    self.assertTrue(any("no separate log-check step" in error for error in errors), errors)

    def test_explicit_not_failure_labels_do_not_require_error_oracles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for title in (
                "Нота длины, не отказ", "Предупреждение — не ошибка", "Задержка — не сбой",
            ):
                with self.subTest(title=title):
                    self.assertEqual(self._test_case_errors(directory, title), [])

    def test_not_failure_labels_do_not_hide_actual_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for title in (
                "Не отказ, а ошибка", "Ошибка валидации, не отказ канала",
                "Не ошибка, а сбой", "Не только отказ, но и предупреждение",
                "Отказ не зарегистрирован",
            ):
                with self.subTest(title=title):
                    errors = self._test_case_errors(directory, title)
                    self.assertTrue(any("no OE-EVIDENCE reference" in error for error in errors), errors)
                    self.assertTrue(any("no separate log-check step" in error for error in errors), errors)

    def test_not_failure_label_cannot_hide_fault_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = self._test_case_errors(
                directory, "Предупреждение, не отказ", "- Каталог: -> tc-flt-demo/FLT-001"
            )
            self.assertTrue(any("no OE-EVIDENCE reference" in error for error in errors), errors)
            self.assertTrue(any("no separate log-check step" in error for error in errors), errors)

    def test_positive_title_cannot_hide_fault_reference_or_failure_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for extra in (
                "- Каталог: -> tc-flt-demo/FLT-001",
                "- Путь: отказ канала", "* **Путь:** ошибка валидации",
            ):
                with self.subTest(extra=extra):
                    errors = self._test_case_errors(directory, "Сообщение без отказа", extra)
                    self.assertTrue(any("no OE-EVIDENCE reference" in error for error in errors), errors)
                    self.assertTrue(any("no separate log-check step" in error for error in errors), errors)

    def test_refs_ignore_html_comments_and_fenced_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refs.md"
            path.write_text(
                "<!-- -> fn-comment/OE-LOAD -->\n"
                "```text\n-> fn-code/OE-INPUT\n```\n"
                "-> fn-real/OE-EVIDENCE\n",
                encoding="utf-8",
            )
            self.assertEqual(CHECKER.refs_in([path]), {("fn-real", "OE-EVIDENCE")})

    def test_commonmark_list_markers_and_bold_colon_variants(self) -> None:
        example = SCRIPT.parents[1] / "examples" / "operational-envelope-factory"
        path = example / "01-requirements" / "02-functions" / "fn-send-notification.md"
        io_kind, facets, errors = CHECKER.parse_function(path)
        self.assertEqual(io_kind, "external")
        self.assertEqual(len(facets), 8)
        self.assertEqual(errors, [])

    def test_internal_only_has_no_facet_skeleton(self) -> None:
        example = SCRIPT.parents[1] / "examples" / "operational-envelope-factory"
        path = example / "01-requirements" / "02-functions" / "fn-calculate-checksum.md"
        io_kind, facets, errors = CHECKER.parse_function(path)
        self.assertEqual(io_kind, "internal")
        self.assertEqual(facets, [])
        self.assertEqual(errors, [])

    def test_weighted_coverage_prioritizes_high_criticality(self) -> None:
        high = CHECKER.Facet(
            "fn-high", "OE-EVIDENCE", "APPLICABLE", "high", Path("fn-high.md")
        )
        low = CHECKER.Facet(
            "fn-low", "OE-EVIDENCE", "APPLICABLE", "low", Path("fn-low.md")
        )
        facets = {high.ref: high, low.ref: low}
        self.assertEqual(
            CHECKER.coverage(set(facets), {high.ref}, facets),
            (1, 2, 5, 6),
        )

    def test_business_reject_registry_is_machine_readable(self) -> None:
        codes, errors = CHECKER.business_reject_codes(
            "## Business-reject codes\n- **Business-reject codes:** `LIMIT`, `DENIED`\n",
            Path("api-demo.md"),
        )
        self.assertEqual(codes, {"LIMIT", "DENIED"})
        self.assertEqual(errors, [])

    def test_full_example_passes_tc_and_fault_catalog_gates(self) -> None:
        example = SCRIPT.parents[1] / "examples" / "operational-envelope-factory"
        output = io.StringIO()
        with redirect_stdout(output):
            result = CHECKER.run(example, "spec")
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("tc_acc_weighted=21/21(100.00%)", output.getvalue())
        self.assertIn("fault_tc_coverage=3/3(100.00%)", output.getvalue())

    def test_code_artifact_detects_code_not_prose(self) -> None:
        # Дисциплина слоёв: требования code-free — ловим код, не трогаем прозу/markdown.
        for code in ("код: `commands.py`", "`_RE`", "SEND_INTERVAL_SECONDS", "_unwrap"):
            self.assertTrue(CHECKER.CODE_ARTIFACT.search(code), code)
        for clean in ("формат `_italic_` и `*bold*`", "измерение — грамматика зафиксирована",
                      "-> rules-control", "AC-01, AC-02"):
            self.assertIsNone(CHECKER.CODE_ARTIFACT.search(clean), clean)

    def test_percentage_reports_n_a_for_empty_denominator(self) -> None:
        # 0/0 — вакуумное покрытие, не полное: n/a, а не ложные 100%.
        self.assertEqual(CHECKER.percentage(0, 0), "n/a")
        self.assertEqual(CHECKER.percentage(21, 21), "100.00%")
        self.assertEqual(CHECKER.percentage(1, 4), "25.00%")


class DiagramFormDetectorTest(unittest.TestCase):
    def diagram(self, directory: str, fields: str = "", kind: str = "component-diagram") -> Path:
        root = Path(directory)
        companion = root / "02-specifications" / "06-diagrams" / "cd-x.md"
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_text(f"---\ntype: {kind}\nslug: cd-x\n{fields}---\n# Diagram\n", encoding="utf-8")
        return companion

    def test_diagram_pair_accepts_mermaid_and_type_alias(self) -> None:
        for kind in ("component-diagram", "cd"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                companion = self.diagram(directory, "sidecar: cd-x.mmd\nsidecar_format: mermaid\n", kind)
                companion.with_suffix(".mmd").write_text(
                    'C4Component\nComponent(sender, "Sender")\n', encoding="utf-8")
                self.assertEqual(CHECKER.validate_forms(Path(directory)), [])

    def test_inline_diagram_does_not_require_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            companion = self.diagram(directory)
            with companion.open("a", encoding="utf-8") as stream:
                stream.write("\n```mermaid\nflowchart LR\n  A --> B\n```\n")
            self.assertEqual(CHECKER.validate_forms(Path(directory)), [])

    def test_declared_diagram_sidecar_missing_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.diagram(directory, "sidecar: cd-x.mmd\nsidecar_format: mermaid\n")
            errors = CHECKER.validate_forms(Path(directory))
            self.assertTrue(any("missing or not a regular file (F2)" in error for error in errors), errors)

    def test_diagram_sidecar_fields_must_be_declared_together(self) -> None:
        for fields in ("sidecar: cd-x.mmd\n", "sidecar_format: mermaid\n"):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as directory:
                companion = self.diagram(directory, fields)
                companion.with_suffix(".mmd").write_text("C4Component\n", encoding="utf-8")
                errors = CHECKER.validate_forms(Path(directory))
                self.assertTrue(any("declared together" in error and "F1" in error for error in errors), errors)

    def test_structurally_invalid_diagram_sidecars_are_blockers(self) -> None:
        cases = (
            ("\n  \n", "empty (F2)"),
            ("```mermaid\nC4Component\n```\n", "markdown fences"),
            ("C4Component\n%% MIGRATE-TODO: add components\n", "open MIGRATE-TODO in sidecar"),
        )
        for content, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                companion = self.diagram(directory, "sidecar: cd-x.mmd\nsidecar_format: mermaid\n")
                companion.with_suffix(".mmd").write_text(content, encoding="utf-8")
                errors = CHECKER.validate_forms(Path(directory))
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_orphan_diagram_sidecar_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            companion = self.diagram(directory)
            companion.with_suffix(".mmd").write_text("C4Component\n", encoding="utf-8")
            errors = CHECKER.validate_forms(Path(directory))
            self.assertTrue(any("without a companion declaring it (F2)" in error for error in errors), errors)

    def test_diagram_sidecar_uses_declared_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            companion = self.diagram(directory, "sidecar: cd-x.yaml\nsidecar_format: yaml\n")
            companion.with_suffix(".yaml").write_text("nodes: [broken\n", encoding="utf-8")
            errors = CHECKER.validate_forms(Path(directory))
            self.assertTrue(any("does not parse as declared 'yaml'" in error for error in errors), errors)

    def test_diagram_malformed_frontmatter_cannot_bypass_pair_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.diagram(directory, "sidecar: [broken\n")
            errors = CHECKER.validate_forms(Path(directory))
            self.assertTrue(any("unreadable frontmatter" in error and "F1" in error for error in errors), errors)

    def test_diagram_companion_open_migrate_todo_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            companion = self.diagram(directory)
            with companion.open("a", encoding="utf-8") as stream:
                stream.write("<!-- MIGRATE-TODO: finish diagram -->\n")
            errors = CHECKER.validate_forms(Path(directory))
            self.assertTrue(any("open MIGRATE-TODO in companion" in error for error in errors), errors)


class FormDetectorTest(unittest.TestCase):
    """F1 membership + F2 pairing/locality/parse + F3 open MIGRATE-TODO + F4 notation-aware fault."""

    def _scn(self, d: str, extra: str = "", body: str = "1. do -> api-y\n") -> Path:
        root = Path(d)
        scn = root / "02-specifications" / "02-scenarios" / "scn-x.md"
        scn.parent.mkdir(parents=True, exist_ok=True)
        scn.write_text(f"---\ntype: scenario\nslug: scn-x\n{extra}---\n# scn\n{body}", encoding="utf-8")
        return root

    def _sc(self, d: str, name: str, content: str, fmt: str) -> list:
        path = Path(d) / name
        path.write_text(content, encoding="utf-8")
        return CHECKER.check_sidecar(path, fmt)

    # ---- load_notations ----
    def test_load_notations_from_registry(self) -> None:
        self.assertLessEqual(
            {"yaml-graph", "sequence", "workflow", "bpmn", "pull-rules"}, set(CHECKER.load_notations())
        )

    # ---- F2: resolve_sidecar (locality / ownership) ----
    def test_sidecar_missing_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "api-x.md"
            comp.write_text("---\ntype: api\n---\n", encoding="utf-8")
            resolved, errs = CHECKER.resolve_sidecar(comp, "api-x.openapi.yaml")
            self.assertIsNone(resolved)
            self.assertTrue(any("missing" in e for e in errs))

    def test_sidecar_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "api-x.md"
            comp.write_text("x", encoding="utf-8")
            for bad in ("../shared.yaml", "/abs/x.yaml", "sub/x.yaml"):
                resolved, errs = CHECKER.resolve_sidecar(comp, bad)
                self.assertIsNone(resolved, bad)
                self.assertTrue(any("local filename" in e for e in errs), bad)

    def test_sidecar_directory_not_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "api-x.md"
            comp.write_text("x", encoding="utf-8")
            (Path(d) / "api-x.openapi.yaml").mkdir()
            resolved, errs = CHECKER.resolve_sidecar(comp, "api-x.openapi.yaml")
            self.assertIsNone(resolved)
            self.assertTrue(any("not a regular file" in e for e in errs))

    # ---- F2: check_sidecar / parse_sidecar ----
    def test_sidecar_empty_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("empty" in e for e in self._sc(d, "x.openapi.yaml", "\n  \n", "openapi-3.1")))

    def test_sidecar_empty_yaml_document_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(
                any("empty YAML" in e for e in self._sc(d, "x.openapi.yaml", "# just a comment\n", "openapi-3.1"))
            )

    def test_sidecar_malformed_yaml_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(
                any("does not parse" in e for e in self._sc(d, "x.openapi.yaml", "a: [unterminated\n", "openapi-3.1"))
            )

    def test_sidecar_malformed_json_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(
                any("does not parse" in e for e in self._sc(d, "x.schema.json", "{bad}", "json-schema-2020-12"))
            )

    def test_sidecar_invalid_xml_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("does not parse" in e for e in self._sc(d, "x.bpmn", "<a><b></a>", "bpmn-2.0")))

    def test_sidecar_format_wins_over_extension(self) -> None:
        # #1: bpmn-2.0 объявлен, но файл .yaml с не-XML — формат главнее расширения → F2.
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("does not parse" in e for e in self._sc(d, "x.yaml", "not: xml\n", "bpmn-2.0")))

    def test_sidecar_open_format_passes_lightweight(self) -> None:
        # #3 (round 2): открытый формат канона без встроенного валидатора (protobuf/graphql/avro/…)
        # не блокируется F2 — только структурная проверка (непустота, без огородок).
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._sc(d, "x.proto", 'syntax = "proto3";\n', "protobuf"), [])

    def test_sidecar_fences_and_todo_are_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            errs = self._sc(
                d, "x.openapi.yaml", "```yaml\nopenapi: 3.1.0\n```\n# MIGRATE-TODO: fill\n", "openapi-3.1"
            )
            self.assertTrue(any("markdown fences" in e for e in errs))
            self.assertTrue(any("MIGRATE-TODO" in e and "F3" in e for e in errs))

    def test_sidecar_valid_bpmn_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            errs = self._sc(
                d, "x.bpmn", "<?xml version='1.0'?><definitions><process id='p'/></definitions>\n", "bpmn-2.0"
            )
            self.assertEqual(errs, [])

    # ---- F1: validate_forms ----
    def test_form_missing_notation_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("no notation" in e for e in CHECKER.validate_forms(self._scn(d))))

    def test_form_unknown_notation_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(
                any("not in scenario-notation-registry" in e for e in CHECKER.validate_forms(self._scn(d, "notation: doodle\n")))
            )

    def test_form_quoted_notation_accepted(self) -> None:
        # #5: фронтматтер как YAML — quoted-значение не должно давать ложный F1.
        with tempfile.TemporaryDirectory() as d:
            errs = CHECKER.validate_forms(self._scn(d, 'notation: "yaml-graph"\n'))
            self.assertFalse(any("F1" in e for e in errs), errs)

    def test_form_wrong_type_is_blocker(self) -> None:
        # #4: scn-* с неверным type не должен молча пропускать проверку формы.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "02-specifications" / "02-scenarios" / "scn-x.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\ntype: note\nslug: scn-x\nnotation: yaml-graph\n---\n# x\n", encoding="utf-8")
            self.assertTrue(any("wrong/absent type" in e for e in CHECKER.validate_forms(root)))

    def test_form_sidecar_without_format_is_blocker(self) -> None:
        # #2: XOR — sidecar без sidecar_format.
        with tempfile.TemporaryDirectory() as d:
            root = self._scn(d, "notation: bpmn\nsidecar: scn-x.bpmn\n")
            (root / "02-specifications" / "02-scenarios" / "scn-x.bpmn").write_text("<a/>", encoding="utf-8")
            self.assertTrue(any("declared together" in e for e in CHECKER.validate_forms(root)))

    def test_form_inline_notation_must_not_have_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._scn(d, "notation: yaml-graph\nsidecar: scn-x.mmd\nsidecar_format: mermaid\n")
            (root / "02-specifications" / "02-scenarios" / "scn-x.mmd").write_text("sequenceDiagram\n", encoding="utf-8")
            self.assertTrue(any("must not declare a sidecar" in e for e in CHECKER.validate_forms(root)))

    def test_form_bpmn_requires_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("requires a sidecar" in e for e in CHECKER.validate_forms(self._scn(d, "notation: bpmn\n"))))

    def test_form_companion_open_todo_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._scn(d, "notation: yaml-graph\n", "# scn\n<!-- MIGRATE-TODO: fix -->\n")
            self.assertTrue(any("open MIGRATE-TODO in companion" in e for e in CHECKER.validate_forms(root)))

    def test_form_orphan_sidecar_is_blocker(self) -> None:
        # #3: не-.md рядом в слое спеки, не объявленный ни одним компаньоном.
        with tempfile.TemporaryDirectory() as d:
            root = self._scn(d, "notation: yaml-graph\n")
            (root / "02-specifications" / "02-scenarios" / "orphan.bpmn").write_text("<a/>", encoding="utf-8")
            self.assertTrue(any("without a companion" in e for e in CHECKER.validate_forms(root)))

    def test_form_valid_yamlgraph_scenario_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(CHECKER.validate_forms(self._scn(d, "notation: yaml-graph\n")), [])

    def test_sidecar_windows_drive_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "api-x.md"
            comp.write_text("x", encoding="utf-8")
            resolved, _ = CHECKER.resolve_sidecar(comp, "C:api-x.yaml")
            self.assertIsNone(resolved)

    def test_sidecar_wrong_slug_rejected(self) -> None:
        # #2 (round 2): сайдкар обязан носить slug компаньона (инвариант «один slug, рядом»).
        with tempfile.TemporaryDirectory() as d:
            comp = Path(d) / "api-x.md"
            comp.write_text("x", encoding="utf-8")
            (Path(d) / "unrelated.yaml").write_text("a: 1\n", encoding="utf-8")
            resolved, errs = CHECKER.resolve_sidecar(comp, "unrelated.yaml")
            self.assertIsNone(resolved)
            self.assertTrue(any("share the companion slug" in e for e in errs))

    def test_form_broken_frontmatter_is_blocker(self) -> None:
        # #1 (round 2): битый YAML-фронтматтер не должен молча трактоваться как пустой и обходить F1.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "02-specifications" / "05-data" / "data-x.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\ntype: data-schema\nsidecar: [broken\n---\n# x\n", encoding="utf-8")
            self.assertTrue(any("unreadable frontmatter" in e for e in CHECKER.validate_forms(root)))

    def test_form_notation_format_mismatch_is_blocker(self) -> None:
        # #4 (round 2): sidecar_format обязан соответствовать нотации.
        with tempfile.TemporaryDirectory() as d:
            root = self._scn(d, "notation: sequence\nsidecar: scn-x.bpmn\nsidecar_format: bpmn-2.0\n")
            (root / "02-specifications" / "02-scenarios" / "scn-x.bpmn").write_text("<a/>\n", encoding="utf-8")
            self.assertTrue(any("incompatible with notation" in e for e in CHECKER.validate_forms(root)))

    # ---- F4: notation-aware fault contour ----
    def _fault_dir(self, d, scn_fm, scn_body, apis, rows):
        root = Path(d)
        scn = root / "02-specifications" / "02-scenarios" / "scn-x.md"
        scn.parent.mkdir(parents=True, exist_ok=True)
        scn.write_text(
            f"---\ntype: scenario\nslug: scn-x\n{scn_fm}updated: 2026-07-13\n---\n# scn\n{scn_body}\n",
            encoding="utf-8",
        )
        for api in apis:
            p = root / "02-specifications" / "04-apis" / "external" / f"{api}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                f"---\ntype: api\nslug: {api}\nscope: external\ncriticality: low\nupdated: 2026-07-13\n---\n"
                "# api\n- **Business-reject codes:** N/A — none\n",
                encoding="utf-8",
            )
        cat = root / "02-specifications" / "08-test-cases" / "tc-flt-x.md"
        cat.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "---\ntype: test-fault-catalog\nslug: tc-flt-x\ncriticality: low\n"
            "coverage: single-fault\nupdated: 2026-07-13\n---\n"
            "# cat\n- Сценарий: -> scn-x\n\n"
            "| fault-id | inj | mode | other | expected | src | feas | tc |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        body = "".join(
            f"| {fid} | {inj} | {mode} | healthy | ok | -> scn-x | infeasible — scope | — |\n"
            for fid, inj, mode in rows
        )
        cat.write_text(header + body, encoding="utf-8")
        return root, cat

    def test_fault_sequence_resolves_without_numbered_step(self) -> None:
        # F4: sequence-сценарий (api в «Участники», без «шаг N») — воспроизводит баг 14.07.
        with tempfile.TemporaryDirectory() as d:
            root, cat = self._fault_dir(
                d, "notation: sequence\n", "## Участники\n- канал -> cmp-c/cap-send -> api-y",
                ["api-y"], [("FLT-001", "-> api-y", "unavailable"), ("FLT-002", "-> api-y", "tech-error")],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [cat], [])
            self.assertFalse(any("O_T4" in e for e in errors), errors)

    def test_fault_yamlgraph_without_step_still_blocks(self) -> None:
        # F4-контраст: у yaml-graph точность «шаг N» остаётся обязательной.
        with tempfile.TemporaryDirectory() as d:
            root, cat = self._fault_dir(
                d, "notation: yaml-graph\n", "## Последовательность шагов\n1. do -> api-y",
                ["api-y"], [("FLT-001", "-> api-y", "unavailable"), ("FLT-002", "-> api-y", "tech-error")],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [cat], [])
            self.assertTrue(any("does not resolve to a scenario step" in e for e in errors), errors)

    def test_fault_yamlgraph_api_only_in_meta_section_not_demanded(self) -> None:
        # #6: -> api-y как нумерованный пункт ТОЛЬКО в мета-секции «Проверка» — не вызов, каталог не требуется.
        with tempfile.TemporaryDirectory() as d:
            root, _ = self._fault_dir(
                d, "notation: yaml-graph\n",
                "## Последовательность шагов\n1. noop -> cmp-c/cap-x\n## Проверка\n1. check -> api-y",
                ["api-y"], [],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [], [])
            self.assertEqual(errors, [], errors)

    def test_fault_api_prefix_not_confused(self) -> None:
        # #7: injection -> api-a-v2 НЕ должен закрывать обязательные модусы api-a (был substring-баг).
        with tempfile.TemporaryDirectory() as d:
            root, cat = self._fault_dir(
                d, "notation: yaml-graph\n", "## Последовательность шагов\n1. a -> api-a\n2. b -> api-a-v2",
                ["api-a", "api-a-v2"],
                [("FLT-001", "шаг 2 → -> api-a-v2", "unavailable"), ("FLT-002", "шаг 2 → -> api-a-v2", "tech-error")],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [cat], [])
            self.assertTrue(any("api-a has no mandatory mode" in e for e in errors), errors)

    def test_fault_yamlgraph_api_only_in_precondition_ignored(self) -> None:
        # #8 (round 3): -> api-y нумерованным пунктом только в «Предусловия» — не вызов, каталог не нужен.
        with tempfile.TemporaryDirectory() as d:
            root, _ = self._fault_dir(
                d, "notation: yaml-graph\n",
                "## Предусловия\n1. дано -> api-y\n## Последовательность шагов\n1. noop -> cmp-c/cap-x",
                ["api-y"], [],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [], [])
            self.assertEqual(errors, [], errors)

    def test_fault_yamlgraph_branch_only_api_covered(self) -> None:
        # #round4: api вызывается только в «Ветвления» (номера шага нет) — точность «шаг N» неприменима;
        # покрытый каталогом api не должен ложно валиться O_T4.
        with tempfile.TemporaryDirectory() as d:
            root, cat = self._fault_dir(
                d, "notation: yaml-graph\n",
                "## Последовательность шагов\n1. start -> cmp-c/cap-x\n## Ветвления\n1. при ошибке -> api-y",
                ["api-y"], [("FLT-001", "ветка -> api-y", "unavailable"), ("FLT-002", "ветка -> api-y", "tech-error")],
            )
            errors, _, _ = CHECKER.validate_fault_catalogs(root, [cat], [])
            self.assertFalse(any("O_T4" in e for e in errors), errors)

    # ---- F2 (round 3): generic-формат парсится, non-UTF-8 не роняет gate ----
    def test_sidecar_generic_yaml_malformed_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("does not parse" in e for e in self._sc(d, "x.txt", "a: [broken\n", "yaml")))

    def test_sidecar_generic_xml_malformed_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(any("does not parse" in e for e in self._sc(d, "x.txt", "<a><b></a>", "xml")))

    # ---- schema-first (2026-07-14): семантический минимум, type-aware F1, contract_origin ----
    def test_sidecar_valid_yaml_but_not_openapi_is_blocker(self) -> None:
        # Парсимости мало: «foo: bar» — валидный YAML, но не OpenAPI. Пустышка не должна зеленеть.
        with tempfile.TemporaryDirectory() as d:
            errors = self._sc(d, "x.openapi.yaml", "foo: bar\n", "openapi-3.1")
            self.assertTrue(any("missing root keys" in e for e in errors), errors)

    def test_sidecar_valid_openapi_minimum_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            body = "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\npaths: {}\n"
            self.assertEqual([], self._sc(d, "x.openapi.yaml", body, "openapi-3.1"))

    def test_sidecar_empty_json_object_is_not_a_schema(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            errors = self._sc(d, "x.schema.json", "{}", "json-schema-2020-12")
            self.assertTrue(any("not a schema" in e for e in errors), errors)

    def test_local_dr_beside_contract_is_not_required_to_have_sidecar(self) -> None:
        # Регресс schema-first: F1 «no sidecar» должен бить по контрактам, а не по любому .md
        # в каталоге контрактов. Локальный dr- рядом с api — канон (meta_model §6.1.2).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            apis = root / "02-specifications" / "04-apis" / "external"
            apis.mkdir(parents=True)
            (apis / "dr-retry.md").write_text(
                "---\ntype: dr\nslug: dr-retry\nfactory: f\nstatus: accepted\n"
                "updated: 2026-07-14\nabout: api-x\n---\n# DR\n",
                encoding="utf-8",
            )
            errors = CHECKER.validate_forms(root)
            self.assertFalse(any("has no sidecar" in e for e in errors), errors)

    def test_api_without_contract_origin_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            apis = root / "02-specifications" / "04-apis" / "external"
            apis.mkdir(parents=True)
            (apis / "api-x.openapi.yaml").write_text(
                "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\npaths: {}\n", encoding="utf-8"
            )
            (apis / "api-x.md").write_text(
                "---\ntype: api\nslug: api-x\nscope: external\nfactory: f\nstatus: draft\n"
                "updated: 2026-07-14\nsidecar_format: openapi-3.1\nsidecar: api-x.openapi.yaml\n---\n# API\n",
                encoding="utf-8",
            )
            errors = CHECKER.validate_forms(root)
            self.assertTrue(any("no contract_origin" in e for e in errors), errors)

    def test_imported_without_contract_source_is_blocker(self) -> None:
        # imported без {uri, revision, sha256}: «as-is» невоспроизводим, ре-импорт неотличим от подмены.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            apis = root / "02-specifications" / "04-apis" / "external"
            apis.mkdir(parents=True)
            (apis / "api-x.openapi.yaml").write_text(
                "openapi: 3.1.0\ninfo:\n  title: t\n  version: '1'\npaths: {}\n", encoding="utf-8"
            )
            (apis / "api-x.md").write_text(
                "---\ntype: api\nslug: api-x\nscope: external\nfactory: f\nstatus: draft\n"
                "updated: 2026-07-14\nsidecar_format: openapi-3.1\nsidecar: api-x.openapi.yaml\n"
                "contract_origin: imported\n---\n# API\n",
                encoding="utf-8",
            )
            errors = CHECKER.validate_forms(root)
            self.assertTrue(any("contract_source" in e for e in errors), errors)

    def test_sidecar_non_utf8_is_blocker(self) -> None:
        # #3b (round 3): бинарный/не-UTF-8 сайдкар — диагностический F2, а не падение всего gate.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.openapi.yaml"
            p.write_bytes(b"\xff\xfe\x00bad")
            self.assertTrue(any("unreadable" in e for e in CHECKER.check_sidecar(p, "openapi-3.1")))


class ExternalDeliveryOwnershipTest(unittest.TestCase):
    EXAMPLE = OperationalEnvelopeCheckerTest.EXAMPLE
    FUNCTION = OperationalEnvelopeCheckerTest.FUNCTION
    DECISION_SLUG = "dr-fn-send-notification-delivery"
    DELIVERY_REF = "-> fn-send-notification/OE-DELIVERY"

    def _decision(self, root: Path) -> Path:
        path = root / self.FUNCTION.parent / f"{self.DECISION_SLUG}.md"
        path.write_text(
            f"---\ntype: decision-record\nslug: {self.DECISION_SLUG}\n"
            "about: fn-send-notification\nstatus: accepted\n---\n"
            "# Внешняя поставка интерфейса доставки\n\n## Выбор\n"
            "Внешний цикл заказчика поставляет интерфейс и доставляет уведомление после "
            "экспорта. Фабрика сохраняет историю принятия и наблюдаемый конечный статус; "
            "заказчик подтверждает конечную доставку в согласованное окно.\n",
            encoding="utf-8",
        )
        return path

    def _ownership(self, root: Path, fields: str) -> None:
        path = root / self.FUNCTION
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "### OE-DELIVERY — сквозной путь результата\n",
            "### OE-DELIVERY — сквозной путь результата\n" + fields,
        )
        path.write_text(text, encoding="utf-8")

    def _external_factory(self, root: Path) -> Path:
        shutil.copytree(self.EXAMPLE, root)
        self._ownership(root, "- **delivery_owner:** external\n"
                        f"- **delivery_decision:** -> {self.DECISION_SLUG}\n")
        decision = self._decision(root)
        # Интерфейс поставляет внешний цикл, поэтому сценарий не вызывает собственный API.
        for path in (root / "02-specifications/04-apis/external").glob("api-notification-channel.*"):
            path.unlink()
        scenario = root / "02-specifications/02-scenarios/scn-send-notification.md"
        scenario.write_text(
            scenario.read_text(encoding="utf-8").replace("-> api-notification-channel", "внешний цикл заказчика"),
            encoding="utf-8",
        )
        tests = root / "02-specifications/08-test-cases"
        (tests / "tc-flt-send-notification.md").unlink()
        integration = tests / "tc-int-send-notification.md"
        text = integration.read_text(encoding="utf-8")
        for fault in ("FLT-000", "FLT-001", "FLT-002"):
            text = text.replace(f"-> tc-flt-send-notification/{fault}", "внешний цикл")
        integration.write_text(text, encoding="utf-8")
        return decision

    def _run(self, root: Path, layer: str = "spec") -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = CHECKER.run(root, layer)
        return result, output.getvalue()

    def test_external_delivery_without_own_api_keeps_full_weighted_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            self._external_factory(root)
            for layer in ("req", "spec", "code"):
                with self.subTest(layer=layer):
                    result, output = self._run(root, layer)
                    self.assertEqual(result, 0, output)
                    self.assertIn("applicable=7", output)
                    self.assertIn("tc_acc_weighted=21/21(100.00%)", output)
                    if layer != "req":
                        self.assertIn("tc_int_weighted=21/21(100.00%)", output)
                    self.assertNotIn("OE-DELIVERY has no external api:", output)

    def test_factory_delivery_still_requires_api_by_default_and_explicitly(self) -> None:
        for fields in ("", "- **delivery_owner:** factory\n"):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                shutil.copytree(self.EXAMPLE, root)
                self._ownership(root, fields)
                (root / "02-specifications/04-apis/external/api-notification-channel.md").unlink()
                result, output = self._run(root)
                self.assertEqual(result, 1, output)
                self.assertIn("OE-DELIVERY has no external api:", output)

    def test_external_decision_must_be_present_accepted_and_owned_by_function(self) -> None:
        mutations = {
            "missing": None,
            "unaccepted": ("status: accepted", "status: draft"),
            "superseded": ("status: accepted", "status: superseded"),
            "wrong owner": ("about: fn-send-notification", "about: fn-calculate-checksum"),
            "missing owner": ("about: fn-send-notification\n", ""),
            "invalid yaml": ("status: accepted", "status: ["),
            "empty choice": ("## Выбор\n", "## Обсуждение\n"),
            "template choice": ("## Выбор\n", "## Выбор\nTODO\n"),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                decision = self._external_factory(root)
                if mutation is None:
                    decision.unlink()
                else:
                    decision.write_text(
                        decision.read_text(encoding="utf-8").replace(*mutation), encoding="utf-8"
                    )
                result, output = self._run(root)
                self.assertEqual(result, 1, output)
                self.assertIn("delivery_decision", output)
                self.assertIn("OE-DELIVERY has no external api:", output)

    def test_delivery_decision_must_resolve_uniquely_beside_owning_function(self) -> None:
        for mode in ("duplicate", "other directory"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                decision = self._external_factory(root)
                target = decision.parent / "dr-duplicate.md" if mode == "duplicate" else root / decision.name
                target.write_text(decision.read_text(encoding="utf-8"), encoding="utf-8")
                if mode == "other directory":
                    decision.unlink()
                result, output = self._run(root)
                self.assertEqual(result, 1, output)
                self.assertIn("must resolve to exactly one local decision-record", output)

    def test_delivery_fields_reject_unknown_owner_incomplete_and_unsafe_references(self) -> None:
        fields = (
            "- **delivery_owner:** unknown\n",
            "- **delivery_owner:** external\n",
            f"- **delivery_decision:** -> {self.DECISION_SLUG}\n",
            "- **delivery_owner:** factory\n" + f"- **delivery_decision:** -> {self.DECISION_SLUG}\n",
            "- **delivery_owner:** external\n- **delivery_decision:** -> ../dr-elsewhere\n",
            "- **delivery_owner:** external\n" + f"- **delivery_decision:** -> {self.DECISION_SLUG}, -> dr-other\n",
        )
        for extra in fields:
            with self.subTest(fields=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                shutil.copytree(self.EXAMPLE, root)
                self._decision(root)
                self._ownership(root, extra)
                _, _, errors = CHECKER.parse_function(root / self.FUNCTION)
                self.assertTrue(any("delivery_" in error for error in errors), errors)

    def test_ownership_fields_are_limited_to_applicable_delivery_facet(self) -> None:
        for target in ("OE-LOAD", "OE-CONTROL"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                self._external_factory(root)
                path = root / self.FUNCTION
                text = path.read_text(encoding="utf-8")
                fields = "- **delivery_owner:** external\n" + f"- **delivery_decision:** -> {self.DECISION_SLUG}\n"
                text = text.replace(fields, "")
                marker = next(line for line in text.splitlines() if line.startswith(f"### {target}"))
                path.write_text(text.replace(marker + "\n", marker + "\n" + fields), encoding="utf-8")
                _, _, errors = CHECKER.parse_function(path)
                self.assertTrue(any("fields require APPLICABLE OE-DELIVERY" in e for e in errors), errors)

    def test_external_ownership_preserves_all_other_delivery_coverage_obligations(self) -> None:
        cases = (
            ("01-requirements/08-test-cases/tc-acc-send-notification.md", self.DELIVERY_REF,
             "uncovered by tc-acc: fn-send-notification/OE-DELIVERY"),
            ("01-requirements/05-landscape/context-oe-example.md", self.DELIVERY_REF,
             "OE-DELIVERY has no context path: fn-send-notification/OE-DELIVERY"),
            ("02-specifications/02-scenarios/scn-send-notification.md", self.DELIVERY_REF,
             "unrealized in scn: fn-send-notification/OE-DELIVERY"),
            ("02-specifications/08-test-cases/tc-int-send-notification.md", "-> scn-send-notification",
             "uncovered by tc-int via scn: fn-send-notification/OE-DELIVERY"),
            ("03-codemap/02-scenario-traces/trace-send-notification.md", self.DELIVERY_REF,
             "untraced in code: fn-send-notification/OE-DELIVERY"),
        )
        for relative, reference, blocker in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                self._external_factory(root)
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8").replace(reference, "внешний цикл"), encoding="utf-8")
                # Принятое решение не может подменить context/scn/test/trace ссылками из своего тела.
                decision = root / self.FUNCTION.parent / f"{self.DECISION_SLUG}.md"
                decision.write_text(
                    decision.read_text(encoding="utf-8") + f"\n## Связи\n{reference}\n", encoding="utf-8"
                )
                result, output = self._run(root, "code")
                self.assertEqual(result, 1, output)
                self.assertIn(blocker, output)

    def test_external_ownership_does_not_waive_acceptance_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            self._external_factory(root)
            path = root / self.FUNCTION
            text = path.read_text(encoding="utf-8")
            path.write_text("\n".join(line for line in text.splitlines() if not line.startswith("- AC-02:")) + "\n", encoding="utf-8")
            result, output = self._run(root)
            self.assertEqual(result, 1, output)
            self.assertIn("OE-DELIVERY unresolved AC AC-02", output)
            self.assertIn("uncovered by tc-int via scn: fn-send-notification/OE-DELIVERY", output)

    def test_external_ownership_keeps_fault_obligations_for_actual_api_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(self.EXAMPLE, root)
            self._ownership(root, "- **delivery_owner:** external\n"
                            f"- **delivery_decision:** -> {self.DECISION_SLUG}\n")
            self._decision(root)
            result, output = self._run(root)
            self.assertEqual(result, 0, output)
            catalog = root / "02-specifications/08-test-cases/tc-flt-send-notification.md"
            text = catalog.read_text(encoding="utf-8")
            catalog.write_text(
                "\n".join(line for line in text.splitlines() if not line.startswith("| FLT-001 |")) + "\n",
                encoding="utf-8",
            )
            result, output = self._run(root)
            self.assertEqual(result, 1, output)
            self.assertIn("has no mandatory mode unavailable (O_T1)", output)

    def test_external_decision_choice_cannot_be_only_comment_code_or_heading(self) -> None:
        choices = ("<!-- external supplier -->", "```text\nexternal supplier\n```", "### Внешний поставщик")
        for choice in choices:
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "factory"
                decision = self._external_factory(root)
                metadata = decision.read_text(encoding="utf-8").split("## Выбор\n", 1)[0]
                decision.write_text(metadata + "## Выбор\n" + choice + "\n", encoding="utf-8")
                result, output = self._run(root)
                self.assertEqual(result, 1, output)
                self.assertIn("needs one non-template Выбор section", output)


if __name__ == "__main__":
    unittest.main()
