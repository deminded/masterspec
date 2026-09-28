"""Pre-apply imports fail closed on stale data, incomplete maps and code targets."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[3] / "masterspec-apply-from-openspec/scripts"
sys.path.insert(0, str(SCRIPTS))
import check_import as gate

sys.path.pop(0)
FN = "01-requirements/02-functions/fn-price.md"
SOURCE = "## ADDED Requirements\n### Requirement: Price\nThe system SHALL calculate the price.\n#### Scenario: Quote\n- **WHEN** a price is requested\n- **THEN** return the total\n"


class ImportGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.factory = self.root / "masterspec"
        self.change = self.factory / "changes/from-openspec-price"
        self.source = self.root / "openspec/changes/price"
        self.specs = self.root / "openspec/specs"
        self.put(self.source / "specs/pricing/spec.md", SOURCE)
        self.put(self.factory / "00-masterspec-index.md", "# Factory index\n")
        self.put(self.factory / FN, "---\ntype: function\nslug: fn-price\n---\n# Price\n## Acceptance\n- AC-01: old\n")
        inventory = gate.inventory(self.source, self.specs)
        self.save("source-inventory.json", inventory)
        self.mapping = {"schema_version": 1, "inventory_id": inventory["inventory_id"],
                        "bindings": [{"operation_id": inventory["operations"][0]["id"],
                                      "disposition": "change", "reason": "The function owns price calculation.",
                                      "targets": [{"path": FN, "anchor": "AC-01"}]}],
                        "target_files": [{"path": name, "sha256": hashlib.sha256((self.factory / name).read_bytes()).hexdigest()}
                                         for name in (FN, "00-masterspec-index.md")]}
        self.save("import-map.json", self.mapping)
        text = "# Change\n> **Область**: spec-only\n## 2. Артефакты\n"
        for i, name in enumerate(("MODIFIED", "ADDED", "REMOVED"), 1):
            text += f"### 2.{i}. {name}\n| # | Тип | Slug | Путь | Описание |\n|---|---|---|---|---|\n"
            if i == 1:
                text += f"| 1 | function | fn-price | `{FN}` | Price rule |\n"
        text += f"## 4. MODIFIED\n### 4.1. Price\n**Файл**: `{FN}`\n**Раздел**: `## Acceptance`\n**Тип правки**: modify-bullet\nДО:\n```\n- AC-01: old\n```\nПОСЛЕ:\n```\n- AC-01: new\n```\n## 5. Файлы\nНет изменений.\n"
        self.put(self.change / "change.md", text)

    def put(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def save(self, name, value):
        self.put(self.change / name, json.dumps(value, ensure_ascii=False))

    def check(self):
        return gate.check(self.change, self.factory, self.source, self.specs)

    def test_valid_import_and_cli_are_read_only(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.check()["result"], "ready-for-review")
        result = subprocess.run([sys.executable, str(SCRIPTS / "check_import.py"), "--change", str(self.change),
                                 "--factory", str(self.factory), "--source", str(self.source), "--specs", str(self.specs)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_changed_native_delta_is_stale(self):
        self.put(self.source / "specs/pricing/spec.md", SOURCE.replace("the total", "a rounded total"))
        with self.assertRaisesRegex(ValueError, "stale"):
            self.check()

    def test_changed_target_or_index_is_stale(self):
        for name in (FN, "00-masterspec-index.md"):
            with self.subTest(name=name):
                path = self.factory / name
                before = path.read_bytes()
                path.write_bytes(before + b"\nEdited externally\n")
                with self.assertRaisesRegex(ValueError, "stale target"):
                    self.check()
                path.write_bytes(before)

    def test_missing_duplicate_and_unknown_operation_bindings(self):
        original = self.mapping["bindings"]
        for bindings in ([], original * 2, [dict(original[0], operation_id="unknown")]):
            with self.subTest(bindings=bindings):
                self.mapping["bindings"] = bindings
                self.save("import-map.json", self.mapping)
                with self.assertRaises(ValueError):
                    self.check()

    def test_blocked_mapping_rejects_whole_change(self):
        self.mapping["bindings"][0].update(disposition="blocked", reason="Which rounding policy?", targets=[])
        self.save("import-map.json", self.mapping)
        with self.assertRaisesRegex(ValueError, "unresolved mapping"):
            self.check()

    def test_blocked_draft_still_checks_scope_and_declared_snapshots(self):
        self.mapping["bindings"][0].update(disposition="blocked", reason="Owner must choose.", targets=[])
        self.save("import-map.json", self.mapping)
        report = gate.diagnose(self.change, self.factory, self.source, self.specs)
        self.assertEqual(report["result"], "blocked")
        self.assertEqual(report["checks"]["scope"], "passed")
        self.assertEqual([item["kind"] for item in report["diagnostics"]], ["semantic"])
        self.mapping["target_files"] = self.mapping["target_files"][1:]
        self.save("import-map.json", self.mapping)
        with self.assertRaisesRegex(gate.ImportCheckError, "missing target snapshots") as caught:
            self.check()
        self.assertEqual(caught.exception.report["checks"]["target-snapshots"], "failed")

    def test_blocked_mapping_without_draft_skips_scope_but_checks_snapshots(self):
        self.mapping["bindings"][0].update(disposition="blocked", reason="Owner must choose.", targets=[])
        self.save("import-map.json", self.mapping)
        (self.change / "change.md").unlink()
        report = gate.diagnose(self.change, self.factory, self.source, self.specs)
        self.assertEqual(report["result"], "blocked")
        self.assertEqual(report["checks"]["scope"], "skipped")
        self.assertEqual(report["checks"]["source-snapshot"], "passed")
        self.assertEqual(report["checks"]["target-snapshots"], "passed")
        self.assertEqual([item["kind"] for item in report["diagnostics"]], ["semantic"])

    def test_semantic_blockers_do_not_report_structural_scope_failure(self):
        self.mapping["bindings"][0].update(disposition="blocked", reason="Owner must choose.")
        self.save("import-map.json", self.mapping)
        change_file = self.change / "change.md"
        self.put(change_file, "> **Статус**: Заблокировано\n" + change_file.read_text(encoding="utf-8"))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for _ in range(2):
            report = gate.diagnose(self.change, self.factory, self.source, self.specs)
            self.assertEqual(report["result"], "blocked")
            self.assertEqual(report["checks"]["readiness"], "failed")
            self.assertTrue(all(value == "passed" for key, value in report["checks"].items()
                                if key != "readiness"))
            self.assertEqual({item["check"] for item in report["diagnostics"]}, {"readiness"})
            self.assertEqual({item["kind"] for item in report["diagnostics"]}, {"semantic"})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_all_blockers_and_independent_failures_are_reported_without_mutation(self):
        delta = SOURCE + SOURCE.partition("\n")[2].replace("Requirement: Price", "Requirement: Tax")
        delta += SOURCE.partition("\n")[2].replace("Requirement: Price", "Requirement: Discount")
        self.put(self.source / "specs/pricing/spec.md", delta)
        inventory = gate.inventory(self.source, self.specs)
        self.save("source-inventory.json", inventory)
        self.mapping["inventory_id"] = inventory["inventory_id"]
        operation_ids = [operation["id"] for operation in inventory["operations"]]
        self.mapping["bindings"] = [
            {"operation_id": operation, "disposition": "blocked", "reason": f"Resolve {operation}.", "targets": []}
            for operation in operation_ids[:2]
        ] + ["malformed binding"]
        self.save("import-map.json", self.mapping)
        # Independent source staleness, target staleness and a forbidden draft path.
        self.put(self.source / "specs/pricing/spec.md", delta + "\n")
        self.put(self.factory / FN, (self.factory / FN).read_text(encoding="utf-8") + "\nExternal edit\n")
        change_file = self.change / "change.md"
        self.put(change_file, change_file.read_text(encoding="utf-8").replace(FN, "src/pricing.py"))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(SCRIPTS / "check_import.py"), "--change", str(self.change),
                                 "--factory", str(self.factory), "--source", str(self.source), "--specs", str(self.specs)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["result"], "blocked")
        blocked_ids = {item["operation_id"] for item in report["diagnostics"] if item["kind"] == "semantic"}
        self.assertEqual(blocked_ids, set(operation_ids[:2]))
        for expected in ("inventory is stale", "binding must be an object", "unmapped source operations",
                         operation_ids[2], "stale target", "outside spec-only scope"):
            self.assertIn(expected, result.stderr)
        for phase in ("source-snapshot", "mapping", "operation-coverage", "target-snapshots", "scope"):
            self.assertEqual(report["checks"][phase], "failed")
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_source_only_skips_dependent_source_snapshot_check(self):
        self.put(self.source / "specs/pricing/spec.md", "Not a native delta\n")
        self.mapping["bindings"][0].update(disposition="blocked", reason="No owner.", targets=[])
        self.save("import-map.json", self.mapping)
        self.put(self.factory / "00-masterspec-index.md", "Changed index\n")
        report = gate.diagnose(self.change, self.factory, self.source, self.specs)
        self.assertEqual(report["checks"]["inventory"], "failed")
        self.assertEqual(report["checks"]["source-snapshot"], "skipped")
        self.assertEqual(report["checks"]["operation-coverage"], "skipped")
        self.assertEqual(report["checks"]["target-snapshots"], "failed")
        self.assertEqual(report["checks"]["scope"], "passed")
        self.assertEqual(sum(item["kind"] == "semantic" for item in report["diagnostics"]), 1)

    def test_unreadable_map_still_checks_source_and_scope(self):
        self.put(self.change / "import-map.json", "{ invalid JSON")
        change_file = self.change / "change.md"
        self.put(change_file, change_file.read_text(encoding="utf-8").replace(FN, "src/pricing.py"))
        report = gate.diagnose(self.change, self.factory, self.source, self.specs)
        self.assertEqual(report["checks"]["mapping"], "failed")
        self.assertEqual(report["checks"]["source-snapshot"], "passed")
        self.assertEqual(report["checks"]["target-snapshots"], "skipped")
        self.assertEqual(report["checks"]["scope"], "failed")

    def test_malformed_fields_do_not_hide_later_bindings_or_snapshots(self):
        self.mapping["bindings"].insert(0, {"operation_id": [], "disposition": {}, "reason": None, "targets": []})
        self.mapping["bindings"][1].update(disposition="blocked", reason="Owner choice.", targets=[])
        self.mapping["target_files"].insert(0, {"path": [], "sha256": {}})
        self.save("import-map.json", self.mapping)
        self.put(self.factory / "00-masterspec-index.md", "Changed index\n")
        report = gate.diagnose(self.change, self.factory, self.source, self.specs)
        messages = "\n".join(item["message"] for item in report["diagnostics"])
        for expected in ("unknown or repeated", "missing reason", "invalid disposition", "unresolved mapping",
                         "mapping path must be a string", "stale target"):
            self.assertIn(expected, messages)

    def test_blocked_change_status_cannot_claim_readiness(self):
        change_file = self.change / "change.md"
        self.put(change_file, "> **Статус**: Заблокировано\n" + change_file.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(gate.ImportCheckError, "Статус|status") as caught:
            self.check()
        self.assertEqual(caught.exception.report["result"], "blocked")
        self.assertEqual(caught.exception.report["diagnostics"][0]["kind"], "semantic")

    def test_every_mapping_target_needs_snapshot(self):
        self.mapping["target_files"] = self.mapping["target_files"][1:]
        self.save("import-map.json", self.mapping)
        with self.assertRaisesRegex(ValueError, "missing target snapshots"):
            self.check()

    def test_mapping_cannot_target_code_or_escape_root(self):
        for name in ("src/pricing.py", "03-codemap/cmap-pricing.md", "../other.md", "C:/other.md",
                     "01-requirements/../../code.md", "02-specifications/tasks.md"):
            with self.subTest(name=name):
                self.mapping["bindings"][0]["targets"][0]["path"] = name
                self.save("import-map.json", self.mapping)
                with self.assertRaises(ValueError):
                    self.check()

    def test_changed_mapping_requires_declared_target(self):
        extra = "01-requirements/02-functions/fn-other.md"
        self.mapping["bindings"][0]["targets"].append({"path": extra, "anchor": "AC-01"})
        self.mapping["target_files"].append({"path": extra, "sha256": None})
        self.save("import-map.json", self.mapping)
        with self.assertRaisesRegex(ValueError, "absent from change.md"):
            self.check()

    def test_null_snapshot_detects_added_target_collision(self):
        extra = "01-requirements/02-functions/fn-other.md"
        self.mapping["target_files"].append({"path": extra, "sha256": None})
        self.save("import-map.json", self.mapping)
        self.check()
        self.put(self.factory / extra, "created by someone else\n")
        with self.assertRaisesRegex(ValueError, "stale target"):
            self.check()

    def test_duplicate_json_keys_do_not_override_reviewed_mapping(self):
        path = self.change / "import-map.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"schema_version": 1',
                        '"schema_version": 2, "schema_version": 1'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.check()

    def test_no_op_requires_no_staged_mutations(self):
        self.mapping["bindings"][0]["disposition"] = "already-satisfied"
        self.save("import-map.json", self.mapping)
        with self.assertRaisesRegex(ValueError, "no-op import"):
            self.check()
        (self.change / "change.md").unlink()
        report = self.check()
        self.assertEqual(report["result"], "no-op-needs-semantic-verification")
        self.assertEqual(report["checks"]["scope"], "passed")

    def test_source_destination_overlap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            gate.check(self.source, self.factory, self.source, self.specs)

    def test_no_op_positive_requirement_cannot_cite_absent_evidence(self):
        self.mapping["bindings"][0]["disposition"] = "already-satisfied"
        self.mapping["target_files"][0]["sha256"] = None
        self.save("import-map.json", self.mapping)
        (self.change / "change.md").unlink()
        (self.factory / FN).unlink()
        with self.assertRaisesRegex(ValueError, "existing evidence"):
            self.check()

    def test_source_root_symlink_is_not_hidden_by_resolve(self):
        link = self.root / "source-alias"
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation requires platform permission")
        with self.assertRaisesRegex(ValueError, "symlink/junction"):
            gate.check(self.change, self.factory, link, self.specs)


if __name__ == "__main__":
    unittest.main()
