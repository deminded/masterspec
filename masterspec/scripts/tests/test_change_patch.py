from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "change-patch.py"
SPEC = importlib.util.spec_from_file_location("test_change_patch_module", SCRIPT)
assert SPEC and SPEC.loader
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
FIXTURE = SCRIPT.parents[2] / "masterspec-apply-from-openspec/examples/code-factory"
CMP = "02-specifications/01-components/cmp-quote-policy.md"
ADDED = "01-requirements/08-test-cases/tc-acc-quote-breakdown.md"


class ChangePatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.factory = self.root / "factory"
        shutil.copytree(FIXTURE / "before/masterspec", self.factory)
        self.change = self.factory / "changes/price"
        self.change.mkdir(parents=True)
        prepared = FIXTURE / "prepared/from-openspec-quote-breakdown"
        shutil.copy(prepared / "change.md", self.change / "change.md")
        shutil.copytree(prepared / "new", self.change / "new")
        self.scn = self.artifact("02-specifications/02-scenarios", "scn-price", "scenario", "-> cmp-quote-policy")
        self.tc = self.artifact("02-specifications/08-test-cases", "tc-int-price", "test-integration", "-> scn-price")
        self.isolated = self.artifact("02-specifications/03-algorithms", "alg-isolated", "algorithm", "No relation to this change.")
        self.other = self.artifact("02-specifications/02-scenarios", "scn-unrelated", "scenario",
                                   "-> fn-calculate-quote\n## Details\nOriginal.")
        self.base = PATCH.snapshot(self.factory, self.change)

    def artifact(self, folder, slug, kind, body, extra=""):
        path = self.factory / folder / (slug + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: {kind}\nslug: {slug}\nstatus: actual\nfactory: pricing\n"
                        f"{extra}---\n# {slug}\n{body}\n", encoding="utf-8")
        return path

    def edit(self, before, after):
        path = self.change / "change.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn(before, text)
        path.write_text(text.replace(before, after), encoding="utf-8")

    def edit_component(self):
        self.edit("разбивка результата по разделу «Результат» -> fn-calculate-quote.",
                  "разбивка результата по разделу «Результат» -> fn-calculate-quote. Пример: 12.04.")

    def tree(self):
        return {path.relative_to(self.factory).as_posix(): path.read_bytes()
                for path in self.factory.rglob("*") if path.is_file()
                and not path.is_relative_to(self.factory / "changes")}

    def test_after_edit_in_existing_change_rechecks_reverse_dependents_without_writing_factory(self):
        before = self.tree()
        self.edit_component()
        result = PATCH.plan(self.factory, self.change, self.base, ["cmp-quote-policy"])
        self.assertEqual(result["route"], "patch")
        self.assertEqual(result["write_artifacts"], [CMP])
        self.assertEqual(set(result["verify_artifacts"]), {CMP, self.scn.relative_to(self.factory).as_posix(),
                                                          self.tc.relative_to(self.factory).as_posix()})
        self.assertNotIn(self.other.relative_to(self.factory).as_posix(), result["verify_artifacts"])
        self.assertEqual(result["changed_change_files"], ["change.md"])
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.base["files"][CMP]["meta"]["status"], "actual")

    def test_existing_added_draft_can_be_refined_inside_new(self):
        path = self.change / "new" / Path(ADDED).name
        path.write_text(path.read_text(encoding="utf-8") + "\nУточнение существующего примера.\n", encoding="utf-8")
        result = PATCH.plan(self.factory, self.change, self.base)
        self.assertEqual(result["route"], "patch")
        self.assertEqual(result["write_artifacts"], [ADDED])
        self.assertFalse((self.factory / ADDED).exists())

    def test_requirement_proposal_can_be_refined_without_changing_accepted_requirement(self):
        self.edit("Налог равен итоговой сумме минус исходная базовая сумма.",
                  "Налог равен итоговой сумме минус исходная базовая сумма (например, 2.01).")
        before = self.tree()
        result = PATCH.plan(self.factory, self.change, self.base)
        self.assertEqual(result["route"], "patch")
        self.assertIn("01-requirements/02-functions/fn-calculate-quote.md", result["verify_artifacts"])
        self.assertEqual(self.tree(), before)

    def test_examples_in_after_do_not_create_graph_edges(self):
        self.edit("разбивка результата по разделу «Результат» -> fn-calculate-quote.",
                  "разбивка результата по разделу «Результат» -> fn-calculate-quote.\n"
                  "<!-- -> fn-ghost -->\n~~~text\n-> api-missing\n-> alg-isolated\n~~~")
        result = PATCH.plan(self.factory, self.change, self.base)
        self.assertEqual(result["route"], "patch")
        self.assertNotIn(self.isolated.relative_to(self.factory).as_posix(), result["read_only_context"])

    def test_whole_requirement_specification_scope_escalates_to_full(self):
        self.isolated.write_text(self.isolated.read_text(encoding="utf-8") + "\n-> fn-calculate-quote\n", encoding="utf-8")
        base = PATCH.snapshot(self.factory, self.change)
        self.edit("Налог равен итоговой сумме минус исходная базовая сумма.",
                  "Налог равен итоговой сумме минус исходная базовая сумма (пример: 2.01).")
        result = PATCH.plan(self.factory, self.change, base)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["coverage"]["verified"], result["coverage"]["total"])

    def test_other_changed_proposals_cannot_be_hidden_by_target(self):
        self.edit_component()
        path = self.change / "new" / Path(ADDED).name
        path.write_text(path.read_text(encoding="utf-8") + "\nПример.\n", encoding="utf-8")
        result = PATCH.plan(self.factory, self.change, self.base, ["cmp-quote-policy"])
        self.assertIn(ADDED, result["changed_files"])

    def test_goal_acceptance_and_nonpayload_text_changes_force_full(self):
        for before, after in (("Сохранять копейки", "Изменить округление"),
                              ("- [ ] AC-01 отражает новый итог;", "- [ ] Другой критерий;"),
                              ("логический выход", "другая цель блока")):
            with self.subTest(before=before):
                text = (self.change / "change.md").read_text(encoding="utf-8")
                self.edit(before, after)
                self.edit_component()
                self.assertEqual(PATCH.plan(self.factory, self.change, self.base)["route"], "full")
                (self.change / "change.md").write_text(text, encoding="utf-8")

    def test_new_write_target_requires_full_change_review(self):
        path = self.other.relative_to(self.factory).as_posix()
        self.edit("\n### 2.2. ADDED", f"\n| 4 | scenario | scn-unrelated | {path} | Detail |\n\n### 2.2. ADDED")
        self.edit("\n## 5. Файлы", f"\n### 4.7. scn-unrelated — clarification\n"
                  f"**Файл**: `{path}`\n**Раздел**: `## Details`\n**Тип правки**: modify-bullet\n"
                  "ДО:\n```\nOriginal.\n```\nПОСЛЕ:\n```\nClarified.\n```\n\n## 5. Файлы")
        self.assertEqual(PATCH.plan(self.factory, self.change, self.base)["route"], "full")

    def test_staged_sidecar_replacement_rechecks_owner_and_consumers(self):
        api = self.artifact("02-specifications/04-apis/internal", "api-price", "api", "-> fn-calculate-quote",
                            "scope: internal\ncontract_origin: authored\nsidecar: api-price.yaml\nsidecar_format: openapi-3.1\n")
        machine = api.with_suffix(".yaml")
        machine.write_text("openapi: 3.1.0\n", encoding="utf-8")
        staged = self.change / "new/api-price.yaml"
        staged.write_text("openapi: 3.1.0\ndescription: Before clarification\n", encoding="utf-8")
        target = machine.relative_to(self.factory).as_posix()
        self.edit("\n### 2.2. ADDED", f"\n| 4 | api | api-price | {target} | Contract |\n\n### 2.2. ADDED")
        self.edit("\n## 6. REMOVED", "\n- `new/api-price.yaml` — replacement.\n\n## 6. REMOVED")
        self.scn.write_text(self.scn.read_text(encoding="utf-8") + "\n-> api-price\n", encoding="utf-8")
        base = PATCH.snapshot(self.factory, self.change)
        before = self.tree()
        staged.write_text("openapi: 3.1.0\ndescription: After clarification\n", encoding="utf-8")
        result = PATCH.plan(self.factory, self.change, base)
        self.assertEqual(result["route"], "patch")
        self.assertIn(api.relative_to(self.factory).as_posix(), result["write_artifacts"])
        self.assertIn(self.tc.relative_to(self.factory).as_posix(), result["verify_artifacts"])
        self.assertEqual(self.tree(), before)

    def test_imported_sidecar_in_added_pair_cannot_be_changed_through_patch(self):
        companion = self.change / "new/api-imported.md"
        companion.write_text("---\ntype: api\nslug: api-imported\nstatus: draft\nfactory: pricing\n"
                             "scope: internal\ncontract_origin: imported\nsidecar: api-imported.yaml\n"
                             "sidecar_format: openapi-3.1\n---\n# Imported\n", encoding="utf-8")
        machine = self.change / "new/api-imported.yaml"
        machine.write_text("openapi: 3.1.0\n", encoding="utf-8")
        self.edit("\n### 2.3. REMOVED", "\n| 2 | api | api-imported | 02-specifications/04-apis/internal/api-imported.md | Contract |\n\n### 2.3. REMOVED")
        self.edit("\n## 6. REMOVED", "\n- `new/api-imported.md` — companion.\n"
                  "- `new/api-imported.yaml` — machine contract.\n\n## 6. REMOVED")
        base = PATCH.snapshot(self.factory, self.change)
        machine.write_text("openapi: 3.1.0\ndescription: Changed\n", encoding="utf-8")
        self.assertEqual(PATCH.plan(self.factory, self.change, base)["route"], "full")

    def test_factory_drift_forces_full_review_even_when_diff_still_applies(self):
        self.other.write_text(self.other.read_text(encoding="utf-8") + "\nNew source fact.\n", encoding="utf-8")
        self.edit_component()
        result = PATCH.plan(self.factory, self.change, self.base)
        self.assertEqual(result["route"], "full")
        self.assertIn("factory baseline or rules changed; recheck the whole change", result["reasons"])

    def test_review_status_can_return_to_draft_but_approved_or_applied_cannot_use_patch(self):
        self.edit("**Статус**: На согласовании", "**Статус**: Черновик")
        self.edit_component()
        self.assertEqual(PATCH.plan(self.factory, self.change, self.base)["route"], "patch")
        for status in ("Согласовано", "В реализации", "Реализовано", "Архивировано"):
            with self.subTest(status=status):
                path = self.change / "change.md"
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace("**Статус**: Черновик", "**Статус**: " + status), encoding="utf-8")
                with self.assertRaises(ValueError):
                    PATCH.plan(self.factory, self.change, self.base)
                path.write_text(text, encoding="utf-8")

    def test_baseline_is_pinned_to_one_change(self):
        another = self.factory / "changes/another"
        shutil.copytree(self.change, another)
        with self.assertRaisesRegex(ValueError, "another change"):
            PATCH.plan(self.factory, another, self.base)

    def test_openspec_layout_uses_sibling_changes_and_still_preserves_factory(self):
        specs = self.root / "openspec/specs"
        shutil.copytree(self.factory, specs, ignore=shutil.ignore_patterns("changes"))
        change = specs.parent / "changes/price"
        shutil.copytree(self.change, change)
        baseline = PATCH.snapshot(specs, change)
        path = change / "new" / Path(ADDED).name
        path.write_text(path.read_text(encoding="utf-8") + "\nУточнение.\n", encoding="utf-8")
        self.assertEqual(PATCH.plan(specs, change, baseline)["route"], "patch")
        self.assertFalse((specs / "changes").exists())

    def test_native_import_metadata_and_undeclared_staging_files_are_not_ignored(self):
        meta = self.change / "import-map.json"
        meta.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dedicated import"):
            PATCH.plan(self.factory, self.change, self.base)
        meta.unlink()
        (self.change / "new/implementation.py").write_text("code", encoding="utf-8")
        with self.assertRaises(ValueError):
            PATCH.plan(self.factory, self.change, self.base)

    def test_codegen_and_design_files_are_not_read(self):
        (self.change / "design.md").write_bytes(b"\xff private implementation")
        code = self.factory / "03-codemap"
        code.mkdir()
        (code / "trace.md").write_bytes(b"\xff private implementation")
        self.assertEqual(PATCH.plan(self.factory, self.change, self.base)["route"], "noop")

    def test_cli_returns_full_for_missing_baseline_instead_of_using_current_tree_as_before(self):
        baseline = self.change / ".verification/baseline.json"
        command = [sys.executable, str(SCRIPT), "plan", str(self.factory), "--change", str(self.change),
                   "--baseline", str(baseline)]
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["route"], "full")
        capture = subprocess.run([sys.executable, str(SCRIPT), "snapshot", str(self.factory),
                                  "--change", str(self.change), "--out", str(baseline)],
                                 capture_output=True, text=True)
        self.assertEqual(capture.returncode, 0, capture.stderr)
        self.edit_component()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["route"], "patch")


if __name__ == "__main__":
    unittest.main()
