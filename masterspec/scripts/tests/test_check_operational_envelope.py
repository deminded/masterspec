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


if __name__ == "__main__":
    unittest.main()
