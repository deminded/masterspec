"""Bounded draft projection: real fixture, conflicts and protected input trees."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "masterspec-apply-from-openspec/scripts"
FIXTURE = ROOT / "masterspec-apply-from-openspec/examples/code-factory"
sys.path.insert(0, str(SCRIPTS))
import prepare_workspace as helper
sys.path.pop(0)
FN = "01-requirements/02-functions/fn-calculate-quote.md"
CMP = "02-specifications/01-components/cmp-quote-policy.md"
ADDED = "01-requirements/08-test-cases/tc-acc-quote-breakdown.md"


def tree(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*")
            if p.is_file() and ".work" not in p.relative_to(path).parts}


class PrepareWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(FIXTURE / "before", self.root)
        self.factory = self.root / "masterspec"
        self.source = self.root / "openspec/changes/quote-breakdown"
        self.specs = self.root / "openspec/specs"
        self.change = self.factory / "changes/from-openspec-quote-breakdown"
        shutil.copytree(FIXTURE / "prepared/from-openspec-quote-breakdown", self.change)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def init(self, run="test"):
        result = helper.init_workspace(self.change, self.factory, self.source, self.specs, run)
        self.workspace = Path(result["workspace"])
        return result

    def project(self):
        return helper.project_workspace(self.workspace)

    def update_change(self, transform):
        path = self.change / "change.md"
        self.write(path, transform(path.read_text(encoding="utf-8")))

    def assert_no_projection(self):
        for name in ("baseline", "after", "projection.json"):
            self.assertFalse((self.workspace.parent / name).exists(), name)

    def add_sidecar_change(self, origin):
        companion = "02-specifications/04-apis/external/api-price.md"
        machine = "02-specifications/04-apis/external/api-price.openapi.yaml"
        self.write(self.factory / companion, "---\ntype: api\nslug: api-price\nscope: external\n"
                   "description: contains---delimiter\n"
                   f"contract_origin: {origin}\nsidecar: api-price.openapi.yaml\nsidecar_format: openapi-3.1\n"
                   "---\n# Price API\n")
        self.write(self.factory / machine, "openapi: 3.0.0\n")
        self.write(self.change / "new/api-price.openapi.yaml", "openapi: 3.1.0\n")
        self.update_change(lambda text: text.replace("\n### 2.2. ADDED", f"\n| 4 | api | api-price | {machine} | Updated contract |\n\n### 2.2. ADDED")
                           .replace("## 6. REMOVED", "- `new/api-price.openapi.yaml` — replacement.\n\n## 6. REMOVED"))
        map_path = self.change / "import-map.json"
        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        mapping["target_files"].extend({"path": name, "sha256": helper.digest((self.factory / name).read_bytes())}
                                       for name in (companion, machine))
        self.write(map_path, json.dumps(mapping, ensure_ascii=False))
        return machine

    def test_public_fixture_projects_without_touching_source_code_or_lifecycle(self):
        self.write(self.factory / "03-codemap/trace-private.md", "PROTECTED CODE\n")
        self.write(self.factory / "01-requirements/hidden.py", "DO NOT COPY CODE\n")
        originals = tree(self.root)
        result = self.init()
        self.assertEqual(result["write_roots"], [str(self.workspace.parent)])
        self.assertTrue((self.workspace.parent / "logs").is_dir())
        report = self.project()
        self.assertEqual(report["result"], "draft-projection")
        self.assertFalse(report["production_apply"])
        self.assertFalse(report["approval"])
        self.assertEqual(tree(self.root), originals)
        self.assertEqual(tree(Path(report["baseline"])), helper.spec_slice(self.factory))
        after = tree(Path(report["after"]))
        expected = tree(FIXTURE / "after/masterspec")
        for name in (FN, CMP, "01-requirements/08-test-cases/tc-acc-taxed-quote.md"):
            self.assertEqual(after[name], expected[name], name)
        self.assertEqual(after[ADDED], (self.change / "new" / Path(ADDED).name).read_bytes())
        self.assertIn(b"status: draft", after[ADDED])
        self.assertEqual(after["00-masterspec-index.md"], (self.factory / "00-masterspec-index.md").read_bytes())
        self.assertNotIn("03-codemap/trace-private.md", after)
        self.assertNotIn("01-requirements/hidden.py", after)
        self.assertIn("change.md", report["draft_files"])
        self.assertEqual(len(report["changed_files"]), 4)
        before_second = tree(self.workspace.parent)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.project()
        self.assertEqual(tree(self.workspace.parent), before_second)

    def test_init_before_inventory_and_matching_origin_continuation(self):
        self.change = self.factory / "changes/early-prepare"
        self.init("first")
        self.assertFalse((self.change / "source-inventory.json").exists())
        self.write(self.workspace.parent / "logs/first.txt", "CLI output\n")
        second = self.init("second")
        self.assertEqual(second["result"], "workspace-created")
        self.assertEqual((self.change / ".work/first/logs/first.txt").read_text(), "CLI output\n")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.init("second")
        other_source = self.root / "openspec/changes/other"
        shutil.copytree(self.source, other_source)
        with self.assertRaisesRegex(ValueError, "different provenance"):
            helper.init_workspace(self.change, self.factory, other_source, self.specs, "third")

    def test_matching_workspace_allows_new_logs_after_source_change_but_projection_stays_stale(self):
        self.init("first")
        source_file = self.source / "specs/pricing/quotes/spec.md"
        source_file.write_bytes(source_file.read_bytes() + b"\nSource updated\n")
        self.init("second")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.project()
        self.assert_no_projection()

    def test_occupied_unknown_destination_and_unsafe_runs_are_rejected(self):
        destination = self.factory / "changes/unknown"
        self.write(destination / "do-not-overwrite.md", "private\n")
        with self.assertRaisesRegex(ValueError, "no matching"):
            helper.init_workspace(destination, self.factory, self.source, self.specs, "x")
        for run in ("../escape", "..", "NUL", "C:run", "a/b"):
            with self.subTest(run=run), self.assertRaises(ValueError):
                self.init(run)
        with self.assertRaises(ValueError):
            helper.init_workspace(self.factory, self.factory, self.source, self.specs)
        with self.assertRaises(ValueError):
            helper.init_workspace(self.source / "output", self.factory, self.source, self.specs)

    def test_init_cannot_write_into_factory_code_metadata_or_nested_changes(self):
        paths = [self.factory / relative for relative in
                 (".git/unexpected", "03-codemap/unexpected", "src/unexpected",
                  "01-requirements/unexpected", "changes/first/second", "changes/archive")]
        paths.extend((self.root / ".git/unexpected", self.root / "other/.work/unexpected"))
        for destination in paths:
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                helper.init_workspace(destination, self.factory, self.source, self.specs)
            self.assertFalse(destination.exists())

    def test_blocked_draft_can_be_examined_without_becoming_ready(self):
        path = self.change / "import-map.json"
        mapping = json.loads(path.read_text(encoding="utf-8"))
        mapping["bindings"][0].update(disposition="blocked", reason="Owner must choose a scope.")
        self.write(path, json.dumps(mapping, ensure_ascii=False))
        self.update_change(lambda text: text.replace("На согласовании", "Заблокировано"))
        before = tree(self.root)
        self.init()
        report = self.project()
        self.assertTrue(report["semantic_blockers"])
        self.assertFalse(report["approval"])
        self.assertEqual(before, tree(self.root))

    def test_stale_source_or_factory_blocks_without_partial_output(self):
        for target in (self.source / "specs/pricing/quotes/spec.md", self.factory / FN):
            with self.subTest(target=target):
                self.init("source" if target.is_relative_to(self.source) else "factory")
                old = target.read_bytes()
                target.write_bytes(old + b"\nExternal update\n")
                with self.assertRaisesRegex(ValueError, "stale"):
                    self.project()
                self.assert_no_projection()
                target.write_bytes(old)

    def test_late_diff_conflict_does_not_materialize_earlier_successes(self):
        self.update_change(lambda text: text.replace("- **Выход (логически):** итоговая сумма.", "Missing exact BEFORE"))
        self.init()
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, "BEFORE must match exactly once"):
            self.project()
        self.assert_no_projection()
        self.assertEqual(tree(self.root), before)

    def test_unsupported_operation_and_modified_scope_are_fail_closed(self):
        original = (self.change / "change.md").read_text(encoding="utf-8")
        for name, text in (("operation", original.replace("modify-bullet", "set-frontmatter", 1)),
                           ("scope", original.replace(FN, "03-codemap/trace-private.md"))):
            with self.subTest(name=name):
                self.write(self.change / "change.md", text)
                self.init(name)
                with self.assertRaises(ValueError):
                    self.project()
                self.assert_no_projection()

    def test_removed_artifact_is_removed_only_from_after_copy(self):
        row = f"| 3 | component | cmp-quote-policy | {CMP} | Состав выхода возможности |\n"
        def remove_component(text):
            text = text.replace(row, "")
            text = text.replace("### 2.3. REMOVED\nНет изменений.",
                                "### 2.3. REMOVED\n| # | Тип | Slug | Путь | Описание |\n"
                                "|---|---|---|---|---|\n" + row)
            left, right = text.index("### 4.6."), text.index("## 5.")
            return text[:left] + text[right:]
        self.update_change(remove_component)
        self.init()
        report = self.project()
        self.assertNotIn(CMP, tree(Path(report["after"])))
        self.assertIn(CMP, tree(Path(report["baseline"])))
        self.assertTrue((self.factory / CMP).is_file())

    def test_colocated_native_specs_are_excluded_from_both_slices(self):
        destination = self.root / "openspec/changes/from-openspec-quote-breakdown"
        shutil.copytree(self.change, destination)
        for entry in self.factory.iterdir():
            if entry.name != "changes":
                if entry.is_dir():
                    shutil.copytree(entry, self.specs / entry.name)
                else:
                    shutil.copyfile(entry, self.specs / entry.name)
        self.factory = self.specs
        self.change = destination
        self.init()
        report = self.project()
        for key in ("baseline", "after"):
            self.assertFalse((Path(report[key]) / "pricing").exists())
        self.assertTrue((self.factory / "pricing/quotes/spec.md").is_file())

    def test_added_only_init_allows_missing_native_main(self):
        self.source = self.root / "openspec/changes/new-capability"
        self.specs = self.root / "missing-native-main"
        self.change = self.factory / "changes/early-added"
        self.write(self.source / "specs/new/spec.md", "## ADDED Requirements\n### Requirement: New\n"
                   "The system SHALL accept requests.\n#### Scenario: Accept\n"
                   "- **WHEN** requested\n- **THEN** accept\n")
        self.init()
        self.assertFalse(self.specs.exists())

    def test_draft_edit_during_planning_invalidates_projection(self):
        self.init()
        original_plan = helper.project_plan
        def changing_plan(*args):
            planned = original_plan(*args)
            self.update_change(lambda text: text + "\nChanged while planning.\n")
            return planned
        with patch.object(helper, "project_plan", side_effect=changing_plan):
            with self.assertRaisesRegex(ValueError, "draft changed while"):
                self.project()
        self.assert_no_projection()

    def test_manifest_cannot_redirect_writes(self):
        self.init()
        manifest = json.loads(self.workspace.read_text(encoding="utf-8"))
        manifest["write_roots"] = [str(self.factory)]
        self.write(self.workspace, json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "write root mismatch"):
            self.project()
        self.assert_no_projection()

    def test_authored_sidecar_replacement_is_copied_and_imported_is_rejected(self):
        for origin in ("authored", "imported"):
            with self.subTest(origin=origin):
                if origin == "imported":
                    # Reuse the existing declaration; only the ownership and its snapshot change.
                    companion = self.factory / "02-specifications/04-apis/external/api-price.md"
                    self.write(companion, companion.read_text().replace("authored", "imported"))
                    map_path = self.change / "import-map.json"
                    mapping = json.loads(map_path.read_text(encoding="utf-8"))
                    for entry in mapping["target_files"]:
                        if entry["path"].endswith("api-price.md"):
                            entry["sha256"] = helper.digest(companion.read_bytes())
                    self.write(map_path, json.dumps(mapping, ensure_ascii=False))
                else:
                    machine = self.add_sidecar_change(origin)
                self.init(origin)
                if origin == "authored":
                    report = self.project()
                    self.assertEqual((Path(report["after"]) / machine).read_bytes(), b"openapi: 3.1.0\n")
                    self.assertEqual((self.factory / machine).read_bytes(), b"openapi: 3.0.0\n")
                else:
                    with self.assertRaisesRegex(ValueError, "explicitly authored"):
                        self.project()
                    self.assert_no_projection()

    def test_map_cannot_make_arbitrary_code_in_a_layer_an_input(self):
        name = "01-requirements/hidden.py"
        self.write(self.factory / name, "DO NOT READ\n")
        map_path = self.change / "import-map.json"
        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        mapping["target_files"].append({"path": name, "sha256": "0" * 64})
        self.write(map_path, json.dumps(mapping, ensure_ascii=False))
        self.init()
        original_read = Path.read_bytes
        def guarded_read(path):
            self.assertNotEqual(path.name, "hidden.py", "code content must not be read")
            return original_read(path)
        with patch.object(Path, "read_bytes", guarded_read):
            with self.assertRaisesRegex(ValueError, "outside Markdown/declared sidecar"):
                self.project()
        self.assert_no_projection()

    def test_links_cannot_be_followed_in_spec_slice(self):
        outside = self.root / "src/linked-secret.txt"
        self.write(outside, "do not read\n")
        target = self.factory / "01-requirements/linked-secret.md"
        try:
            target.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        self.init()
        with self.assertRaisesRegex(ValueError, "symlink/junction"):
            self.project()
        self.assert_no_projection()

    def test_hardlinks_cannot_enter_projection(self):
        target = self.factory / "01-requirements/linked-artifact.md"
        try:
            os.link(self.factory / FN, target)
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.init()
        with self.assertRaisesRegex(ValueError, "hard-linked"):
            self.project()
        self.assert_no_projection()

    def test_cli_init_and_project_return_json(self):
        initialized = subprocess.run([sys.executable, str(SCRIPTS / "prepare_workspace.py"), "init",
                                      "--change", str(self.change), "--factory", str(self.factory),
                                      "--source", str(self.source), "--specs", str(self.specs), "--run", "cli"],
                                     capture_output=True, encoding="utf-8")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        manifest = json.loads(initialized.stdout)["workspace"]
        projected = subprocess.run([sys.executable, str(SCRIPTS / "prepare_workspace.py"), "project",
                                    "--workspace", manifest], capture_output=True, encoding="utf-8")
        self.assertEqual(projected.returncode, 0, projected.stderr)
        self.assertEqual(json.loads(projected.stdout)["result"], "draft-projection")


class CanonicalProjectionTests(unittest.TestCase):
    def block(self, operation, before="", after="", section="## Parent"):
        return {"operation": operation, "before": before, "after": after,
                "section": section, "path": "01-requirements/02-functions/fn-example.md"}

    def test_heading_chains_ignore_fenced_and_commented_headings(self):
        text = "## Parent\n```md\n### Child\n- old\n```\n<!--\n### Child\n-->\n### Child\n- old\n## Other\n### Child\n- old\n"
        block = self.block("modify-bullet", "- old", "- new", "`## Parent` → `### Child`")
        actual = helper.apply_block(text.encode(), block).decode()
        self.assertEqual(actual.count("- new"), 1)
        self.assertIn("### Child\n- new\n## Other", actual)

    def test_matching_is_whole_lines_with_only_leading_whitespace_normalized(self):
        block = self.block("modify-bullet", "- old", "  - new")
        text = b"## Parent\r\n\r\n    - old\r\n- older\r\n## Other\r\n"
        actual = helper.apply_block(text, block)
        self.assertEqual(actual, b"## Parent\r\n\r\n  - new\r\n- older\r\n## Other\r\n")
        for ambiguous in (b"## Parent\n- old\n  - old\n", b"## Parent\n- old suffix\n"):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                helper.apply_block(ambiguous, block)

    def test_replace_section_and_append_subsection_have_bounded_semantics(self):
        text = b"## Parent\n\nOld.\n### Existing\nChild.\n\n## Other\nKeep.\n"
        replaced = helper.apply_block(text, self.block("replace-section", "historical only", "New.")).decode()
        self.assertEqual(replaced, "## Parent\n\nNew.\n\n## Other\nKeep.\n")
        appended = helper.apply_block(text.replace(b"\n## Other", b"\n---\n\n## Other"),
                                     self.block("add-subsection", after="### Added\nNew.")).decode()
        self.assertIn("### Added\nNew.\n\n---\n\n## Other\nKeep.", appended)
        with self.assertRaisesRegex(ValueError, "already exists"):
            helper.apply_block(text, self.block("add-subsection", after="### Existing\nOther."))
        with self.assertRaises(ValueError):
            helper.apply_block(text, self.block("replace-section", after="## Escaping\nBad."))

    def test_diff_parser_preserves_nested_fences_and_rejects_duplicate_payloads(self):
        document = ("## 4. MODIFIED\n### 4.1. Example\n**Файл**: 01-requirements/02-functions/fn-example.md\n"
                    "**Раздел**: ## Parent\n**Тип правки**: replace-section\nПОСЛЕ:\n````md\n"
                    "```\n### 4.2. An example, not a second block\n```\n````\n## 5. Files\n")
        blocks = helper.diff_blocks(document)
        self.assertEqual(len(blocks), 1)
        self.assertIn("### 4.2. An example", blocks[0]["after"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            helper.diff_blocks(document.replace("## 5. Files", "ПОСЛЕ:\n```\nduplicate\n```\n## 5. Files"))


if __name__ == "__main__":
    unittest.main()
