from __future__ import annotations

import importlib.util
import io
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


if __name__ == "__main__":
    unittest.main()
