"""Regression tests for the evolve write boundary, independent of LLM review."""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check-change-scope.py"
SPEC = importlib.util.spec_from_file_location("check_change_scope", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)

FN = "01-requirements/02-functions/fn-send.md"
API = "02-specifications/04-apis/external/api-send.md"


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.factory = Path(self.tmp.name) / "masterspec"
        self.change = self.factory / "changes" / "send"
        self.change.mkdir(parents=True)

    def write(self, name, content):
        path = self.factory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def artifact(self, path=FN, kind="function", slug="fn-send", sidecar=""):
        scope = "scope: external\n" if kind == "api" else ""
        return self.write(path, f"---\ntype: {kind}\nslug: {slug}\n{scope}{sidecar}---\n# Artifact\n")

    def document(self, modified=(), added=(), removed=(), diffs=None):
        lines = ["# Change: send", "> **Область**: spec-only", "## 2. Затронутые артефакты"]
        for number, name, rows in ((1, "MODIFIED", modified), (2, "ADDED", added), (3, "REMOVED", removed)):
            lines += [f"### 2.{number}. {name}", "| # | Тип | Slug | Путь | Описание |",
                      "|---|---|---|---|---|"]
            lines += [f"| {i} | {kind} | {slug} | `{path}` | change |"
                      for i, (kind, slug, path) in enumerate(rows, 1)]
        lines += ["## 4. MODIFIED — diff-блоки"]
        if diffs is None:
            diffs = [row[2] for row in modified if row[2].endswith(".md")]
        for i, path in enumerate(diffs, 1):
            lines += [f"### 4.{i}. change", f"**Файл**: `{path}`", "ПОСЛЕ:", "```", "# Payload", "```"]
        lines += ["## 5. ADDED"]
        new_files = sorted(entry.name for entry in (self.change / "new").iterdir()) if (self.change / "new").exists() else []
        lines += [f"- `new/{name}` — purpose" for name in new_files] or ["Нет изменений."]
        return self.write("changes/send/change.md", "\n".join(lines) + "\n")

    def assert_blocked(self, message=None):
        with self.assertRaises((ValueError, OSError), msg=message):
            CHECKER.check(self.change)

    def test_valid_modified_and_later_implementation_plan(self):
        self.artifact()
        self.document(modified=[("function", "fn-send", FN)])
        self.write("changes/send/design.md", "Created by impl-plan after evolve.\n")
        self.write("changes/send/tasks.md", "Separate implementation work.\n")
        CHECKER.check(self.change)

    def test_openspec_sibling_specs_root_and_explicit_root(self):
        self.artifact()
        self.document(modified=[("function", "fn-send", FN)])
        # Move the same factory's layers below specs/ and leave changes/ beside it.
        specs = self.factory / "specs"
        specs.mkdir()
        (self.factory / "01-requirements").rename(specs / "01-requirements")
        (specs / "00-masterspec-index.md").write_text(
            "# Index\n- Раскладка (layout): openspec\n", encoding="utf-8")
        CHECKER.check(self.change)
        CHECKER.check(self.change, specs)
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.change)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # A partially migrated factory needs an explicit choice, not first-match.
        self.write("00-masterspec-index.md", "# Classic index\n")
        self.assert_blocked()
        CHECKER.check(self.change, specs)

    def test_new_api_pair_and_existing_sidecar_replacement(self):
        machine = "api-send.openapi.yaml"
        self.artifact("changes/send/new/api-send.md", "api", "api-send",
                      f"sidecar: {machine}\nsidecar_format: openapi-3.1\n")
        self.write(f"changes/send/new/{machine}", "openapi: 3.1.0\n")
        self.document(added=[("api", "api-send", API)])
        CHECKER.check(self.change)
        # Replacement of an existing sidecar has a MODIFIED row and no diff.
        (self.change / "new" / "api-send.md").rename(self.factory / "api-send-temp.md")
        self.artifact(API, "api", "api-send", f"sidecar: {machine}\nsidecar_format: openapi-3.1\n")
        target = str(Path(API).with_name(machine)).replace("\\", "/")
        self.write(target, "openapi: 3.0.0\n")
        self.document(modified=[("api", "api-send", target)])
        CHECKER.check(self.change)

    def test_glossary_and_removed_artifact(self):
        self.write("00-glossary.md", "# Glossary\n")
        self.artifact()
        self.document(modified=[("glossary", "00-glossary", "00-glossary.md")],
                      removed=[("function", "fn-send", FN)])
        CHECKER.check(self.change)

    def test_forbidden_targets_in_every_operation(self):
        forbidden = ["03-codemap/cmap-send.md", "src/send.py", "design.md", "tasks.md",
                     "02-specifications/design.md", "00-masterspec-index.md"]
        for operation in ("modified", "added", "removed"):
            for path in forbidden:
                with self.subTest(operation=operation, path=path):
                    self.document(**{operation: [("function", "fn-send", path)]})
                    self.assert_blocked()

    def test_cross_platform_escape_and_alias_paths(self):
        for path in ["/tmp/fn-send.md", "C:/fn-send.md", "C:fn-send.md", "\\\\host\\x\\fn-send.md",
                     "01-requirements/../src/fn-send.md", "01-requirements\\..\\src\\fn-send.md",
                     "01-requirements//fn-send.md", "01-requirements/fn-send.md:stream",
                     "01-requirements/fn-send.md.", "01-requirements/NUL.md"]:
            with self.subTest(path=path):
                self.document(added=[("function", "fn-send", path)])
                self.assert_blocked()

    def test_undeclared_and_mismatched_diff_target(self):
        self.artifact()
        for target in ["03-codemap/cmap-send.md", "02-specifications/cmp-extra.md"]:
            self.document(modified=[("function", "fn-send", FN)], diffs=[target])
            self.assert_blocked()

    def test_payload_headings_and_file_labels_are_not_declarations(self):
        self.artifact()
        document = self.document(modified=[("function", "fn-send", FN)])
        document.write_text(document.read_text(encoding="utf-8").replace(
            "# Payload", "## 2. not a real section\n**Файл**: src/payload.py"), encoding="utf-8")
        CHECKER.check(self.change)

    def test_undeclared_new_file_and_nested_directory(self):
        self.artifact()
        self.document(modified=[("function", "fn-send", FN)])
        self.write("changes/send/new/implementation.py", "print('code')\n")
        self.assert_blocked()
        (self.change / "new" / "implementation.py").unlink()
        self.write("changes/send/new/nested/fn-extra.md", "# Extra\n")
        self.assert_blocked()

    def test_section_five_is_an_exact_safe_inventory(self):
        self.artifact("changes/send/new/fn-send.md")
        for manifest in ["Нет изменений.", "- `../src/code.py` — code",
                         "- `new/../code.py` — code", "- `new/extra.md` — extra"]:
            with self.subTest(manifest=manifest):
                document = self.document(added=[("function", "fn-send", FN)])
                source = document.read_text(encoding="utf-8").replace("- `new/fn-send.md` — purpose", manifest)
                document.write_text(source, encoding="utf-8")
                self.assert_blocked()

    def test_added_target_collision_is_rejected(self):
        self.artifact()
        self.artifact("changes/send/new/fn-send.md")
        self.document(added=[("function", "fn-send", FN)])
        self.assert_blocked()

    def test_missing_new_pair_file(self):
        self.artifact("changes/send/new/api-send.md", "api", "api-send",
                      "sidecar: api-send.openapi.yaml\nsidecar_format: openapi-3.1\n")
        self.document(added=[("api", "api-send", API)])
        self.assert_blocked()

    def test_unsafe_and_ambiguous_sidecar_declarations(self):
        for field in ["../src/api-send.py", "C:api-send.yaml", "nested/api-send.yaml", "other.yaml",
                      "[api-send.yaml]", "&alias api-send.yaml", "api-send.md"]:
            with self.subTest(sidecar=field):
                self.artifact("changes/send/new/api-send.md", "api", "api-send",
                              f"sidecar: {field}\nsidecar_format: openapi-3.1\n")
                self.document(added=[("api", "api-send", API)])
                self.assert_blocked()

    def test_duplicate_and_complex_frontmatter_keys_fail_closed(self):
        for extra in ["sidecar: api-send.yaml\nsidecar: api-send.other.yaml\n",
                      "'sidecar': ../escape.yaml\n", "<<: *shared\n"]:
            self.artifact("changes/send/new/api-send.md", "api", "api-send", extra)
            self.document(added=[("api", "api-send", API)])
            self.assert_blocked()

    def test_metadata_routing_cannot_escape_clean_declaration(self):
        self.artifact("changes/send/new/fn-send.md", sidecar="block: ../../src\n")
        self.document(added=[("function", "fn-send", FN)])
        self.assert_blocked()
        self.artifact("changes/send/new/fn-send.md", kind="repo-map")
        self.assert_blocked()
        self.artifact("changes/send/new/fn-send.md")
        self.document(added=[("function", "fn-send", "02-specifications/fn-send.md")])
        self.assert_blocked()

    def test_new_function_with_block_and_type_alias(self):
        self.artifact("changes/send/new/fn-send.md", sidecar="block: notifications\n")
        self.document(added=[("fn", "fn-send", "01-requirements/02-functions/notifications/fn-send.md")])
        CHECKER.check(self.change)

    def test_each_diff_block_requires_exactly_one_target(self):
        self.artifact()
        document = self.document(modified=[("function", "fn-send", FN)])
        source = document.read_text(encoding="utf-8")
        # The total count is two fields/two blocks; neither block is valid.
        source = source.replace("ПОСЛЕ:", f"**Файл**: `{FN}`\nПОСЛЕ:")
        source = source.replace("## 5. ADDED", "### 4.2. undeclared target\n## 5. ADDED")
        document.write_text(source, encoding="utf-8")
        self.assert_blocked()

    def test_malformed_or_duplicate_declaration_is_not_silently_skipped(self):
        self.artifact()
        for replacement in ["| 1 | function | fn-send | | change |", "function fn-send src/send.py",
                            "| 1 | function | fn-send | `" + FN + "` | extra | column |"]:
            document = self.document(modified=[("function", "fn-send", FN)])
            text = document.read_text(encoding="utf-8")
            text = text.replace(f"| 1 | function | fn-send | `{FN}` | change |", replacement)
            document.write_text(text, encoding="utf-8")
            self.assert_blocked()
        self.document(modified=[("function", "fn-send", FN)], removed=[("function", "fn-send", FN)])
        self.assert_blocked()

    def test_code_type_cannot_be_smuggled_into_allowed_directory(self):
        self.artifact("changes/send/new/cmap-send.md", "component-map", "cmap-send")
        self.document(added=[("component-map", "cmap-send", "02-specifications/cmap-send.md")])
        self.assert_blocked()

    def test_general_change_requires_separate_workflow(self):
        self.artifact()
        document = self.document(modified=[("function", "fn-send", FN)])
        document.write_text(document.read_text(encoding="utf-8").replace(
            "> **Область**: spec-only\n", ""), encoding="utf-8")
        self.assert_blocked()

    def test_symlink_target_escape(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "fn-send.md").write_text("# outside\n", encoding="utf-8")
        link = self.factory / "01-requirements"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation requires platform permission")
        self.document(removed=[("function", "fn-send", "01-requirements/fn-send.md")])
        self.assert_blocked()

    def test_cli_success_and_blocker_exit_codes(self):
        self.artifact()
        self.document(modified=[("function", "fn-send", FN)])
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.change)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("semantic layer review still required", result.stdout)
        self.document(removed=[("component-map", "cmap-send", "03-codemap/cmap-send.md")])
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.change)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKER", result.stderr)


if __name__ == "__main__":
    unittest.main()
