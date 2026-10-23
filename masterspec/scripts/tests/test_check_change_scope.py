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

    def test_removed_legacy_type_with_frontmatter(self):
        path = "02-specifications/legacy-note.md"
        self.artifact(path, "retired-note", "legacy-send")
        self.document(removed=[("retired-note", "legacy-send", path)])
        CHECKER.check(self.change)
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.change)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_removed_files_without_frontmatter_or_companion(self):
        for kind, path, content in [
            ("retired-note", "02-specifications/README.md", b"# Legacy notes\n"),
            ("component-map", "02-specifications/old-map.md", b"# Obsolete map\n"),
            ("legacy-data", "02-specifications/legacy.yaml", b"legacy: true\n"),
            ("legacy-image", "02-specifications/old-logo.png", b"\x89PNG\r\n\x1a\n\xff\xfe"),
        ]:
            with self.subTest(kind=kind, path=path):
                target = self.write(path, "")
                target.write_bytes(content)
                self.document(removed=[(kind, "legacy-send", path)])
                CHECKER.check(self.change)

    def test_removed_frontmatter_must_match_slug(self):
        for path in ["02-specifications/legacy.md", "02-specifications/legacy.txt"]:
            with self.subTest(path=path):
                self.artifact(path, "retired-note", "legacy-other")
                self.document(removed=[("retired-note", "legacy-send", path)])
                with self.assertRaisesRegex(ValueError, "slug does not match"):
                    CHECKER.check(self.change)

    def test_removed_registered_type_still_matches_frontmatter(self):
        self.artifact()
        self.document(removed=[("fn", "fn-send", FN)])
        CHECKER.check(self.change)
        self.document(removed=[("component", "fn-send", FN)])
        with self.assertRaisesRegex(ValueError, "type does not match"):
            CHECKER.check(self.change)

    def test_unknown_type_remains_forbidden_for_added_and_modified(self):
        for operation in ("added", "modified"):
            with self.subTest(operation=operation):
                self.document(**{operation: [("retired-note", "legacy-send",
                                              "02-specifications/legacy-send.md")]})
                with self.assertRaisesRegex(ValueError, "unknown or non-specification artifact type"):
                    CHECKER.check(self.change)

    def test_removed_target_must_exist_and_be_a_file(self):
        for path in ["02-specifications/legacy-send.md", "02-specifications/legacy.yaml"]:
            with self.subTest(path=path):
                self.document(removed=[("retired-note", "legacy-send", path)])
                with self.assertRaisesRegex(ValueError, "missing REMOVED artifact"):
                    CHECKER.check(self.change)
        (self.factory / "02-specifications" / "legacy-dir").mkdir(parents=True)
        self.document(removed=[("retired-note", "legacy-send", "02-specifications/legacy-dir")])
        with self.assertRaisesRegex(ValueError, "missing REMOVED artifact"):
            CHECKER.check(self.change)

    def test_removed_legacy_sidecar_keeps_path_boundary(self):
        path = "02-specifications/legacy-send.md"
        self.artifact(path, "retired-note", "legacy-send", "sidecar: legacy-send.json\n")
        self.write("02-specifications/legacy-send.json", "{}\n")
        self.document(removed=[("retired-note", "legacy-send", path)])
        CHECKER.check(self.change)
        for machine in ["../legacy-send.json", "nested/legacy-send.json", "other.json"]:
            with self.subTest(sidecar=machine):
                self.artifact(path, "retired-note", "legacy-send", f"sidecar: {machine}\n")
                self.assert_blocked()

    def test_removed_cr_line_endings_do_not_bypass_sidecar_check(self):
        path = "02-specifications/legacy.md"
        target = self.write(path, "")
        self.write("02-specifications/tasks.md", "# unrelated\n")
        self.document(removed=[("legacy", "legacy", path)])
        for raw in (b"---\rtype: legacy\rslug: legacy\rsidecar: tasks.md\r---\r# note\r",
                    b"---\ntype: legacy\nslug: legacy\nsidecar: tasks.md\n---\n# note\n",
                    b"---\r\ntype: legacy\r\nslug: legacy\r\nsidecar: tasks.md\r\n---\r\n# note\r\n"):
            with self.subTest(raw=raw):
                target.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "sidecar must be a local basename"):
                    CHECKER.check(self.change)

    def test_removed_nul_in_body_does_not_hide_frontmatter(self):
        self.write("02-specifications/tasks.md", "# unrelated\n")
        self.write("02-specifications/legacy.json", "{}\n")
        cases = [("02-specifications/legacy.md", b"sidecar: tasks.md", "sidecar must be a local basename"),
                 ("02-specifications/legacy.txt", b"sidecar: legacy.json", "only for .md companions")]
        for path, declared, message in cases:
            for offset in (0, 4095, 4096):
                with self.subTest(path=path, offset=offset):
                    target = self.write(path, "")
                    target.write_bytes(b"---\ntype: legacy\nslug: legacy\n" + declared + b"\n---\n" +
                                       b"x" * offset + b"\x00\n")
                    self.document(removed=[("legacy", "legacy", path)])
                    with self.assertRaisesRegex(ValueError, message):
                        CHECKER.check(self.change)

    def test_removed_binary_starting_like_frontmatter_is_not_text(self):
        path = "02-specifications/legacy.bin"
        target = self.write(path, "")
        target.write_bytes(b"---\x00\x01\x02\n---\n")
        self.document(removed=[("legacy-data", "legacy-send", path)])
        CHECKER.check(self.change)

    def test_removed_invalid_utf8_after_delimiter_is_blocked(self):
        path = "02-specifications/legacy.md"
        target = self.write(path, "")
        target.write_bytes(b"---\ntype: legacy\xff\n---\n")
        self.document(removed=[("legacy", "legacy", path)])
        with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
            CHECKER.check(self.change)

    def test_removed_sidecar_pair_requires_md_companion(self):
        path = "02-specifications/legacy.txt"
        self.artifact(path, "legacy", "legacy-send", "sidecar: legacy-send.json\n")
        self.write("02-specifications/legacy-send.json", "{}\n")
        self.document(removed=[("legacy", "legacy-send", path)])
        with self.assertRaisesRegex(ValueError, "only for .md companions"):
            CHECKER.check(self.change)

    def test_removed_registered_machine_sidecar_keeps_companion_binding(self):
        target = "02-specifications/04-apis/external/api-send.openapi.yaml"
        self.artifact(API, "api", "api-send", "sidecar: api-send.openapi.yaml\n")
        self.write(target, "openapi: 3.1.0\n")
        self.document(removed=[("api", "api-send", target)])
        CHECKER.check(self.change)
        self.document(removed=[("data", "api-send", target)])
        with self.assertRaisesRegex(ValueError, "not the companion's declared sidecar"):
            CHECKER.check(self.change)
        self.document(removed=[("api", "api-send", target)])
        self.artifact(API, "api", "api-send", "sidecar: api-send.other.yaml\n")
        with self.assertRaisesRegex(ValueError, "not the companion's declared sidecar"):
            CHECKER.check(self.change)

    def test_new_component_diagram_pairs_accept_canonical_type_and_alias(self):
        rows = []
        for kind, slug in (("component-diagram", "cd-send"), ("cd", "cd-receive")):
            # Generate from the actual template so its optional pair declaration stays usable.
            template = SCRIPT.parents[1] / "templates" / "tpl-component-diagram.md"
            text = template.read_text(encoding="utf-8").replace("<factory-slug>", slug.removeprefix("cd-"))
            text = text.replace("# sidecar_format: mermaid", "sidecar_format: mermaid")
            text = text.replace("# sidecar: ", "sidecar: ")
            text = text.replace("type: component-diagram", f"type: {kind}")
            self.write(f"changes/send/new/{slug}.md", text)
            self.write(f"changes/send/new/{slug}.mmd", "C4Component\nComponent(sender, \"Sender\")\n")
            rows.append((kind, slug, f"02-specifications/06-diagrams/{slug}.md"))
        self.document(added=rows)
        CHECKER.check(self.change)

    def test_existing_component_diagram_sidecar_replacement(self):
        target = "02-specifications/06-diagrams/cd-send.mmd"
        self.artifact("02-specifications/06-diagrams/cd-send.md", "component-diagram", "cd-send",
                      "sidecar: cd-send.mmd\nsidecar_format: mermaid\n")
        self.write(target, "flowchart LR\n  A --> B\n")
        self.write("changes/send/new/cd-send.mmd", "flowchart LR\n  A --> C\n")
        self.document(modified=[("cd", "cd-send", target)])
        CHECKER.check(self.change)

    def test_new_component_diagram_pair_requires_format_and_machine_file(self):
        companion = self.artifact("changes/send/new/cd-send.md", "cd", "cd-send",
                                  "sidecar: cd-send.mmd\n")
        machine = self.write("changes/send/new/cd-send.mmd", "C4Component\n")
        rows = [("cd", "cd-send", "02-specifications/06-diagrams/cd-send.md")]
        self.document(added=rows)
        with self.assertRaisesRegex(ValueError, "missing sidecar_format"):
            CHECKER.check(self.change)
        companion.write_text(companion.read_text(encoding="utf-8").replace(
            "sidecar: cd-send.mmd\n", "sidecar: cd-send.mmd\nsidecar_format: mermaid\n"), encoding="utf-8")
        machine.unlink()
        self.document(added=rows)
        with self.assertRaisesRegex(ValueError, "must list every declared new/ file"):
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

    def test_new_decisions_from_templates_preserve_hyphenated_ids(self):
        self.artifact()
        templates = SCRIPT.parents[1] / "templates"
        adr_slug = "adr-007-channel-adapter-selection"
        dr_slug = "dr-fn-send-storage-engine"
        adr = (templates / "tpl-adr.md").read_text(encoding="utf-8")
        dr = (templates / "tpl-dr.md").read_text(encoding="utf-8")
        adr = adr.replace("adr-NNN-<slug>", adr_slug).replace("ADR-NNN", "ADR-007")
        dr = (dr.replace("dr-<артефакт-slug>-<тема>", dr_slug)
              .replace("<slug артефакта, к которому относится решение>", "fn-send")
              .replace("<тема: privacy | storage | algorithm | contract | ...>", "storage-engine"))
        for slug, content in ((adr_slug, adr), (dr_slug, dr)):
            content = (content.replace("<factory-slug>", "notifications")
                       .replace("<team or person>", "platform").replace("YYYY-MM-DD", "2026-10-15"))
            self.write(f"changes/send/new/{slug}.md", content)
        self.document(added=[
            ("adr", adr_slug, f"04-decisions/{adr_slug}.md"),
            ("dr", dr_slug, f"01-requirements/02-functions/{dr_slug}.md"),
        ])

        CHECKER.check(self.change)
        for slug in (adr_slug, dr_slug):
            self.assertEqual(CHECKER.frontmatter(self.change / "new" / f"{slug}.md")["slug"], slug)
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.change)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_malformed_decision_ids_still_fail_slug_validation(self):
        for kind, slug in [("adr", "adr-007-channel--selection"),
                           ("adr", "adr-007-channel-selection-"),
                           ("dr", "dr-fn-send_storage"),
                           ("dr", "dr-fn-Send-storage"),
                           ("dr", "dr-fn-send-storage.v2")]:
            with self.subTest(slug=slug):
                self.document(added=[(kind, slug, f"04-decisions/{slug}.md")])
                with self.assertRaisesRegex(ValueError, "invalid slug"):
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
