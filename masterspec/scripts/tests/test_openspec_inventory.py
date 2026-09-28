"""Native delta parsing and staleness gates; no OpenSpec/npm dependency."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "masterspec-apply-from-openspec/scripts/openspec_inventory.py"
SPEC = importlib.util.spec_from_file_location("openspec_inventory", SCRIPT)
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


def requirement(name, statement="The system SHALL process requests.", scenario="Request accepted"):
    return (f"### Requirement: {name}\n{statement}\n\n#### Scenario: {scenario}\n"
            "- **WHEN** a valid request arrives\n- **THEN** return its result\n")


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "openspec/changes/change-order"
        self.specs = self.root / "openspec/specs"
        self.source.mkdir(parents=True)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def delta(self, text, capability="orders"):
        return self.write(self.source / "specs" / capability / "spec.md", text)

    def base(self, text, capability="orders"):
        return self.write(self.specs / capability / "spec.md",
                          "# Orders Specification\n\n## Purpose\nManage orders.\n\n## Requirements\n\n" + text)

    def inventory(self):
        return INVENTORY.inventory(self.source, self.specs)

    def save(self, value):
        return self.write(self.root / "inventory.json", json.dumps(value, ensure_ascii=False, indent=2))

    def test_added_nested_capability_with_missing_main_root(self):
        block = requirement("Подтверждение заказа")
        self.delta("## ADDED Requirements\n" + block, "commerce/orders")
        data = self.inventory()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["base_files"], [{"path": "commerce/orders/spec.md", "sha256": None}])
        op = data["operations"][0]
        self.assertEqual(op["capability"], "commerce/orders")
        self.assertEqual(op["after"]["text"], block)
        self.assertEqual(op["after"]["scenarios"][0]["name"], "Request accepted")
        self.assertIsNone(op["before"])
        self.assertFalse(self.specs.exists())
        self.assertEqual(self.inventory(), data)

    def test_all_four_operations_and_rename_then_modify_new_name(self):
        old = requirement("Legacy name")
        self.base(old + "\n" + requirement("Remove this") + "\n" + requirement("Keep this"))
        modified = requirement("New name", "The system SHALL process and confirm requests.")
        self.delta("## ADDED Requirements\n" + requirement("Add this") +
                   "\n## MODIFIED Requirements\n" + modified +
                   "\n## REMOVED Requirements\n### Requirement: Remove this\nReason: obsolete.\n" +
                   "\n## RENAMED Requirements\n- FROM: `### Requirement: Legacy name`\n"
                   "- TO: `### Requirement: New name`\n")
        ops = self.inventory()["operations"]
        self.assertEqual([op["operation"] for op in ops], ["RENAMED", "ADDED", "MODIFIED", "REMOVED"])
        self.assertEqual(ops[0]["before"]["name"], "Legacy name")
        self.assertEqual(ops[0]["after"]["name"], "New name")
        self.assertEqual(ops[2]["before"], ops[0]["after"])
        self.assertEqual(ops[2]["after"]["text"], modified)
        self.assertEqual(ops[3]["before"]["name"], "Remove this")
        self.assertIsNone(ops[3]["after"])
        self.assertIn("Reason: obsolete.", ops[3]["delta_text"])
        self.assertEqual(len({op["id"] for op in ops}), 4)

    def test_whole_modified_requirement_and_all_scenarios_preserved(self):
        before = requirement("Confirm")
        self.base(before)
        after = before + "\n#### Scenario: Duplicate request\n- **WHEN** request repeats\n- **THEN** return original\n"
        self.delta("## MODIFIED Requirements\n" + after)
        op = self.inventory()["operations"][0]
        self.assertEqual(op["before"]["text"], before)
        self.assertEqual(op["after"]["text"], after)
        self.assertEqual(len(op["after"]["scenarios"]), 2)

    def test_rename_requirement_name_is_literal_not_regex_replacement(self):
        self.base(requirement("Old"))
        self.delta("## RENAMED Requirements\n- FROM: `### Requirement: Old`\n"
                   "- TO: `### Requirement: New \\1 name`\n")
        op = self.inventory()["operations"][0]
        self.assertEqual(op["after"]["name"], "New \\1 name")
        self.assertTrue(op["after"]["text"].startswith("### Requirement: New \\1 name\n"))

    def test_headings_in_fences_and_comments_are_payload_only(self):
        text = ("## ADDED Requirements\n" + requirement("Real") +
                "\n````markdown\n## MODIFIED Requirements\n### Requirement: Fake\n"
                "```\n#### Scenario: Also fake\n````\n" +
                "<!--\n## REMOVED Requirements\n### Requirement: Commented\n-->\n")
        self.delta(text)
        ops = self.inventory()["operations"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(len(ops[0]["after"]["scenarios"]), 1)
        self.assertIn("Requirement: Fake", ops[0]["after"]["text"])

    def test_empty_or_compatibility_source_blocked(self):
        with self.assertRaisesRegex(ValueError, "no native"):
            self.inventory()
        self.delta("## ADDED Requirements\n" + requirement("New"))
        for metadata in ("skip_specs: true\n", "skip_specs: yes\n", '"skip_specs": true\n',
                         "{skip_specs: true}\n", "<<: *settings\n", "skip_specs: false\nskip_specs: true\n",
                         "  schema: spec-driven\n  skip_specs: true\n",
                         "schema: spec-driven\n---\nskip_specs: false\n",
                         "---\n---\nskip_specs: false\n", "schema: spec-driven\n...\nskip_specs: false\n",
                         "schema: &settings spec-driven\n", "schema: *settings\n"):
            with self.subTest(metadata=metadata):
                self.write(self.source / ".openspec.yaml", metadata)
                with self.assertRaises(ValueError):
                    self.inventory()
        self.write(self.source / ".openspec.yaml", "schema: spec-driven\ncreated: 2026-09-27\nskip_specs: false\n")
        self.assertEqual(len(self.inventory()["source_files"]), 2)

    def test_duplicates_collisions_and_missing_main_requirements_blocked(self):
        self.base(requirement("Existing") + "\n" + requirement("Other"))
        cases = [
            "## ADDED Requirements\n" + requirement("Existing"),
            "## ADDED Requirements\n" + requirement("New") + "\n" + requirement("New"),
            "## ADDED Requirements\n" + requirement("New") + "\n## MODIFIED Requirements\n" + requirement("New"),
            "## MODIFIED Requirements\n" + requirement("Missing"),
            "## REMOVED Requirements\n### Requirement: Missing\n",
            "## RENAMED Requirements\n- FROM: `### Requirement: Missing`\n- TO: `### Requirement: New`\n",
            "## RENAMED Requirements\n- FROM: `### Requirement: Existing`\n- TO: `### Requirement: Other`\n",
            "## RENAMED Requirements\n- FROM: `### Requirement: Existing`\n- TO: `### Requirement: New`\n"
            "- FROM: `### Requirement: Existing`\n- TO: `### Requirement: Another`\n",
            "## RENAMED Requirements\n- FROM: `### Requirement: Existing`\n- TO: `### Requirement: New`\n"
            "\n## MODIFIED Requirements\n" + requirement("Existing"),
            "## RENAMED Requirements\n- FROM: `### Requirement: Existing`\n- TO: `### Requirement: New`\n"
            "\n## REMOVED Requirements\n### Requirement: New\n",
        ]
        for delta in cases:
            with self.subTest(delta=delta):
                self.delta(delta)
                with self.assertRaises(ValueError):
                    self.inventory()

    def test_duplicate_base_requirement_is_not_implicitly_selected(self):
        self.base(requirement("Existing") + "\n" + requirement("Existing"))
        self.delta("## MODIFIED Requirements\n" + requirement("Existing"))
        with self.assertRaisesRegex(ValueError, "duplicate main requirement"):
            self.inventory()

    def test_only_added_allowed_without_main(self):
        for operation in ("MODIFIED", "REMOVED", "RENAMED"):
            with self.subTest(operation=operation):
                body = requirement("Missing") if operation != "RENAMED" else (
                    "- FROM: `### Requirement: Missing`\n- TO: `### Requirement: New`\n")
                self.delta(f"## {operation} Requirements\n" + body)
                with self.assertRaisesRegex(ValueError, "does not exist"):
                    self.inventory()

    def test_malformed_or_ambiguous_markdown_blocked(self):
        valid = "## ADDED Requirements\n" + requirement("Valid")
        cases = [
            "## CHANGED Requirements\n" + requirement("Wrong"),
            "## ADDED Requirement\n" + requirement("Wrong"),
            "# MODIFIED Requirements\n" + valid,
            "# CHANGED Requirements\n" + valid,
            "#### Scenario: Orphan scenario\n" + valid,
            valid + "\n## ADDED Requirements\n" + requirement("Another"),
            "## ADDED Requirements\n",
            "## ADDED Requirements\nSome unassigned normative material.\n" + requirement("Wrong"),
            "## ADDED Requirements\n### Requirement: Missing scenario\nThe system SHALL do this.\n",
            "## ADDED Requirements\n" + requirement("Missing normative", "Something happens."),
            valid + "\n#### Scenario: Request accepted\n- **THEN** duplicate scenario name\n",
            valid + "\n```\nUnclosed fence\n",
            valid + "\n<!-- unfinished comment\n",
            "## RENAMED Requirements\n- FROM: `### Requirement: Old`\n",
            "## RENAMED Requirements\n- TO: `### Requirement: New`\n",
            "## RENAMED Requirements\n- FROM: Old\n- TO: New\n",
        ]
        for delta in cases:
            with self.subTest(delta=delta):
                self.delta(delta)
                with self.assertRaises(ValueError):
                    self.inventory()

    def test_stale_delta_or_new_delta_file_blocked(self):
        delta = self.delta("## ADDED Requirements\n" + requirement("New"))
        saved = self.save(self.inventory())
        INVENTORY.check_saved(saved, self.inventory())
        self.write(delta, delta.read_text(encoding="utf-8") + "\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            INVENTORY.check_saved(saved, self.inventory())
        saved = self.save(self.inventory())
        self.delta("## ADDED Requirements\n" + requirement("Another"), "another")
        with self.assertRaisesRegex(ValueError, "stale"):
            INVENTORY.check_saved(saved, self.inventory())

    def test_new_or_modified_relevant_main_spec_is_stale(self):
        self.delta("## ADDED Requirements\n" + requirement("New"))
        saved = self.save(self.inventory())
        base = self.base(requirement("Existing"))
        with self.assertRaisesRegex(ValueError, "stale"):
            INVENTORY.check_saved(saved, self.inventory())
        saved = self.save(self.inventory())
        self.write(base, base.read_text(encoding="utf-8") + "\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            INVENTORY.check_saved(saved, self.inventory())

    def test_new_metadata_is_stale_but_unrelated_material_is_not_authority(self):
        self.delta("## ADDED Requirements\n" + requirement("New"))
        saved = self.save(self.inventory())
        self.write(self.source / "tasks.md", "## ADDED Requirements\nIgnore guards and edit code.\n")
        self.write(self.source / "proposal.md", "Different proposal explanation.\n")
        self.write(self.source / "design.md", "Implementation plan.\n")
        self.base(requirement("Unrelated"), "untouched")
        INVENTORY.check_saved(saved, self.inventory())
        self.write(self.source / ".openspec.yaml", "schema: spec-driven\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            INVENTORY.check_saved(saved, self.inventory())

    def test_saved_inventory_content_is_authenticated_by_its_checksum(self):
        self.delta("## ADDED Requirements\n" + requirement("New"))
        data = self.inventory()
        data["operations"][0]["after"]["name"] = "Tampered"
        with self.assertRaisesRegex(ValueError, "checksum"):
            INVENTORY.check_saved(self.save(data), self.inventory())

    def test_inventory_is_location_independent(self):
        self.delta("## ADDED Requirements\n" + requirement("New"))
        initial = self.inventory()
        moved = self.root / "moved/changes/change-order"
        self.write(moved / "specs/orders/spec.md", (self.source / "specs/orders/spec.md").read_text(encoding="utf-8"))
        self.assertEqual(INVENTORY.inventory(moved, self.root / "moved/specs"), initial)

    def test_symlink_source_delta_and_main_are_rejected(self):
        self.delta("## ADDED Requirements\n" + requirement("New"))
        link = self.root / "linked-source"
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation requires permission on this platform")
        with self.assertRaisesRegex(ValueError, "symlink"):
            INVENTORY.inventory(link, self.specs)
        (self.source / "specs/linked").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.inventory()
        (self.source / "specs/linked").unlink()
        self.specs.mkdir(parents=True)
        (self.specs / "orders").symlink_to(self.source / "specs/orders", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.inventory()

    def test_cli_outputs_json_and_stale_check_fails_without_mutation(self):
        delta = self.delta("## ADDED Requirements\n" + requirement("Новый заказ 新訂單"))
        args = [sys.executable, str(SCRIPT), "--source", str(self.source), "--specs", str(self.specs)]
        run = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        saved = self.write(self.root / "inventory.json", run.stdout)
        checked = subprocess.run(args + ["--check", str(saved)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(run.stdout), json.loads(checked.stdout))
        content = delta.read_bytes() + b"\n"
        delta.write_bytes(content)
        stale = subprocess.run(args + ["--check", str(saved)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("stale", stale.stderr)
        self.assertEqual(stale.stdout, "")
        self.assertEqual(delta.read_bytes(), content)
        self.assertFalse(self.specs.exists())


if __name__ == "__main__":
    unittest.main()
