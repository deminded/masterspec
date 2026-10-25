from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "design-patch.py"
SPEC = importlib.util.spec_from_file_location("design_patch", SCRIPT)
assert SPEC and SPEC.loader
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class DesignPatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fn = self.artifact("01-requirements/02-functions", "fn-send", "", status="actual")
        self.cmp = self.artifact("02-specifications/01-components", "cmp-sender", "-> fn-send")
        self.api = self.artifact("02-specifications/04-apis/internal", "api-send", "-> fn-send",
                                 extra="sidecar: api-send.yaml\ncontract_origin: authored\n")
        self.sidecar = self.api.with_suffix(".yaml")
        self.sidecar.write_text("openapi: 3.1.0\ninfo: {title: Send, version: '1'}\n", encoding="utf-8")
        self.scn = self.artifact("02-specifications/02-scenarios", "scn-send", "-> api-send\n-> cmp-sender")
        self.flt = self.artifact("02-specifications/08-test-cases", "tc-flt-send", "-> scn-send\n-> api-send")
        self.tc = self.artifact("02-specifications/08-test-cases", "tc-int-send", "-> tc-flt-send")
        self.other = self.artifact("02-specifications/02-scenarios", "scn-other", "-> cmp-sender")
        self.base = PATCH.snapshot(self.root)

    def artifact(self, folder, slug, body, *, status="draft", extra=""):
        path = self.root / folder / (slug + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: {slug.split('-')[0]}\nslug: {slug}\nfactory: demo\n"
                        f"status: {status}\n{extra}---\n# {slug}\n{body}\n", encoding="utf-8")
        return path

    def key(self, path):
        return path.relative_to(self.root).as_posix()

    def change(self, path, text="Clarify the existing oracle.\n"):
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def test_transitive_dependents_rechecked_but_unrelated_design_is_not(self):
        self.change(self.api)
        result = PATCH.plan(self.root, self.base, ["api-send"])
        self.assertEqual(result["route"], "patch")
        self.assertEqual(set(result["verify_artifacts"]),
                         {self.key(p) for p in (self.api, self.scn, self.flt, self.tc)})
        self.assertEqual(result["write_artifacts"], [self.key(self.api)])
        self.assertIn(self.key(self.fn), result["read_only_context"])
        self.assertIn(self.key(self.cmp), result["read_only_context"])
        self.assertNotIn(self.key(self.other), result["verify_files"])

    def test_removed_link_keeps_only_old_direct_endpoint_in_context(self):
        text = self.other.read_text(encoding="utf-8").replace("-> cmp-sender", "")
        self.other.write_text(text, encoding="utf-8")
        result = PATCH.plan(self.root, self.base)
        self.assertEqual(result["verify_artifacts"], [self.key(self.other)])
        self.assertIn(self.key(self.cmp), result["read_only_context"])
        self.assertNotIn(self.key(self.fn), result["read_only_context"])

    def test_comments_and_fenced_examples_create_neither_unknown_nor_known_edges(self):
        self.change(self.other, "<!-- -> fn-ghost and -> api-send -->\n"
                    "```text\n-> api-missing\n-> api-send\n```\n")
        base = PATCH.snapshot(self.root)
        self.assertEqual(base["unresolved"], [])
        self.assertNotIn(self.key(self.api), base["files"][self.key(self.other)]["deps"])
        self.assertEqual(PATCH.plan(self.root, base)["route"], "noop")
        self.change(self.api)
        self.assertNotIn(self.key(self.other), PATCH.plan(self.root, base)["verify_artifacts"])

    def test_codemap_references_are_deferred_without_reading_code(self):
        self.artifact("04-decisions", "adr-delivery", "-> trace-inbound-delivery\n-> cmap-server\n-> dmap-cache", status="accepted")
        code = self.root / "03-codemap"
        code.mkdir()
        (code / "trace-inbound-delivery.md").write_bytes(b"\xff unreadable code layer")
        base = PATCH.snapshot(self.root)
        self.assertEqual(base["unresolved"], [])
        self.assertEqual(len(base["deferred_references"]), 3)
        self.change(self.api)
        result = PATCH.plan(self.root, base)
        self.assertEqual(result["route"], "patch")
        self.assertTrue(all(not key.startswith("03-codemap/") for key in result["verify_files"]))

    def test_known_slug_mention_in_normal_prose_still_creates_edge(self):
        self.change(self.other, "This scenario also consumes api-send.\n")
        base = PATCH.snapshot(self.root)
        self.change(self.api)
        self.assertIn(self.key(self.other), PATCH.plan(self.root, base)["verify_artifacts"])

    def test_context_does_not_walk_the_entire_upstream_chain(self):
        self.change(self.tc)
        result = PATCH.plan(self.root, self.base)
        self.assertEqual(result["read_only_context"], [self.key(self.flt)])
        self.assertNotIn(self.key(self.scn), result["read_only_context"])

    def test_whole_specification_layer_is_escalated_by_the_planner(self):
        self.change(self.api, "-> tc-int-send\n")
        base = PATCH.snapshot(self.root)
        self.change(self.cmp)
        result = PATCH.plan(self.root, base)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["coverage"]["verified"], result["coverage"]["total"])
        self.assertTrue(any("whole layer" in reason for reason in result["reasons"]))

    def test_kernel_examples_and_evidence_are_not_verification_rules(self):
        kernel = self.root / "bundle/masterspec"
        (kernel / "references").mkdir(parents=True)
        rule = kernel / "references/spec-writing.md"
        rule.write_text("Normative rule", encoding="utf-8")
        for name in ("masterspec-derive", "masterspec-evolve", "masterspec-verify", "masterspec-gen",
                     "masterspec-accept", "masterspec-apply-change"):
            entry = kernel.parent / name / "SKILL.md"
            entry.parent.mkdir()
            entry.write_text("Operation rule", encoding="utf-8")
        with patch.object(PATCH, "KERNEL", kernel):
            before = PATCH.rules_snapshot(self.root, [])
            generated = kernel / "examples/factory/.verification/baseline.json"
            generated.parent.mkdir(parents=True)
            generated.write_text("{}", encoding="utf-8")
            self.assertEqual(PATCH.rules_snapshot(self.root, []), before)
            rule.write_text("Changed normative rule", encoding="utf-8")
            self.assertNotEqual(PATCH.rules_snapshot(self.root, []), before)

    def test_unrelated_old_unresolved_debt_does_not_close_local_route(self):
        self.change(self.other, "-> api-old-missing\n")
        base = PATCH.snapshot(self.root)
        self.change(self.api)
        result = PATCH.plan(self.root, base)
        self.assertEqual(result["route"], "patch")
        self.assertTrue(any("api-old-missing" in item for item in result["unresolved_outside_scope"]))
        self.change(self.other, "Another correction.\n")
        blocked = PATCH.plan(self.root, base)
        self.assertEqual(blocked["route"], "full")
        self.assertTrue(any("api-old-missing" in reason and self.key(self.other) in reason for reason in blocked["reasons"]))

    def test_repository_operational_envelope_example_is_noop_despite_template_comment(self):
        factory = SCRIPT.parents[1] / "examples/operational-envelope-factory"
        baseline = PATCH.snapshot(factory)
        self.assertEqual(baseline["unresolved"], [])
        self.assertEqual(PATCH.plan(factory, baseline)["route"], "noop")

    def test_new_reference_expands_scope(self):
        self.change(self.other, "-> api-send\n")
        self.change(self.api)
        result = PATCH.plan(self.root, self.base)
        self.assertIn(self.key(self.other), result["verify_artifacts"])

    def test_sidecar_edit_rechecks_companion_and_consumers(self):
        self.change(self.sidecar, "description: Clarified example\n")
        result = PATCH.plan(self.root, self.base)
        self.assertEqual(result["route"], "patch")
        self.assertIn(self.key(self.api), result["write_artifacts"])
        self.assertIn(self.key(self.tc), result["verify_artifacts"])

    def test_machine_ref_adds_dependency_even_without_slug_in_companion(self):
        data = self.artifact("02-specifications/05-data", "data-message", "",
                             extra="sidecar: payload.json\n")
        data.with_name("payload.json").write_text('{"type":"object"}', encoding="utf-8")
        self.change(self.sidecar, "$ref: ../../05-data/payload.json#/type\n")
        base = PATCH.snapshot(self.root)
        self.change(data.with_name("payload.json"), " ")
        result = PATCH.plan(self.root, base)
        self.assertEqual(result["route"], "patch")
        self.assertIn(self.key(self.api), result["verify_artifacts"])
        self.assertIn(self.key(self.tc), result["verify_artifacts"])

    def test_target_cannot_hide_other_changed_drafts(self):
        self.change(self.api)
        self.change(self.other)
        result = PATCH.plan(self.root, self.base, ["api-send"])
        self.assertIn(self.key(self.other), result["changed_files"])
        self.assertIn(self.key(self.other), result["verify_artifacts"])

    def test_requirement_glossary_and_decision_changes_force_full(self):
        for path in (self.fn, self.root / "00-glossary.md"):
            with self.subTest(path=path.name):
                base = PATCH.snapshot(self.root)
                self.change(path) if path.exists() else path.write_text("Term\n", encoding="utf-8")
                self.assertEqual(PATCH.plan(self.root, base)["route"], "evolve" if path == self.fn else "full")
        decision = self.artifact("04-decisions", "adr-transport", "", status="accepted")
        base = PATCH.snapshot(self.root)
        self.change(decision)
        self.assertEqual(PATCH.plan(self.root, base)["route"], "evolve")

    def test_non_draft_owner_routes_to_evolve_including_sidecar_only_edit(self):
        self.api.write_text(self.api.read_text(encoding="utf-8").replace("status: draft", "status: actual"),
                            encoding="utf-8")
        base = PATCH.snapshot(self.root)
        self.change(self.sidecar, "description: Changed\n")
        self.assertEqual(PATCH.plan(self.root, base)["route"], "evolve")

    def test_imported_sidecar_is_not_editable_in_patch(self):
        self.api.write_text(self.api.read_text(encoding="utf-8").replace("authored", "imported"), encoding="utf-8")
        base = PATCH.snapshot(self.root)
        self.change(self.sidecar, "description: Changed\n")
        self.assertEqual(PATCH.plan(self.root, base)["route"], "full")

    def test_file_addition_and_deletion_force_full(self):
        added = self.artifact("02-specifications/03-algorithms", "alg-new", "-> fn-send")
        self.assertEqual(PATCH.plan(self.root, self.base)["route"], "full")
        added.unlink()
        self.other.unlink()
        self.assertEqual(PATCH.plan(self.root, self.base)["route"], "full")

    def test_new_slug_does_not_misclassify_unchanged_accepted_source_as_a_write(self):
        self.change(self.fn, "The planned design name is alg-future.\n")
        base = PATCH.snapshot(self.root)
        added = self.artifact("02-specifications/03-algorithms", "alg-future", "-> fn-send")
        result = PATCH.plan(self.root, base)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["changed_files"], [self.key(added)])

    def test_explicit_extra_rules_and_configured_packs_are_watched(self):
        pack = self.root / "rules"
        pack.mkdir()
        rule = pack / "manifest.yaml"
        rule.write_text("version: 1\n", encoding="utf-8")
        for configured in (False, True):
            with self.subTest(configured=configured):
                if configured:
                    (self.root / "masterspec-config.yaml").write_text(
                        "guardrail_packs:\n  - path: rules\n", encoding="utf-8")
                base = PATCH.snapshot(self.root, [] if configured else ["rules"])
                self.change(rule, "# Changed\n")
                self.assertEqual(PATCH.plan(self.root, base)["route"], "full")

    def test_unknown_slug_or_remote_machine_ref_forces_full(self):
        self.change(self.scn, "-> api-missing\n")
        self.assertEqual(PATCH.plan(self.root, self.base)["route"], "full")
        self.scn.write_text(self.scn.read_text(encoding="utf-8").replace("-> api-missing\n", ""), encoding="utf-8")
        self.change(self.sidecar, "$ref: https://example.invalid/remote.json\n")
        self.assertEqual(PATCH.plan(self.root, self.base)["route"], "full")

    def test_snapshot_is_not_a_green_verdict_and_identical_tree_is_noop(self):
        result = PATCH.plan(self.root, self.base)
        self.assertEqual(result["route"], "noop")
        self.assertNotIn("patch_ready", result)
        self.assertNotIn("codegen_ready", result)
        self.assertEqual(result["baseline_digest"], result["current_digest"])

    def test_factory_identity_and_unknown_baseline_schema_are_rejected(self):
        for field, value in (("factory_root", "elsewhere"), ("schema", 99)):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.base)
                bad[field] = value
                with self.assertRaises(ValueError):
                    PATCH.plan(self.root, bad)

    def test_digest_is_stable_and_covers_all_inputs(self):
        first = PATCH.plan(self.root, self.base)
        second = PATCH.plan(self.root, self.base)
        self.assertEqual(first["current_digest"], second["current_digest"])
        self.change(self.api)
        third = PATCH.plan(self.root, self.base)
        self.assertNotEqual(first["current_digest"], third["current_digest"])

    def test_derived_index_and_code_are_outside_design_inputs(self):
        (self.root / "00-masterspec-index.md").write_text("regenerated", encoding="utf-8")
        code = self.root / "03-codemap"
        code.mkdir()
        (code / "trace.md").write_bytes(b"\xff not a design artifact")
        result = PATCH.plan(self.root, self.base)
        self.assertEqual(result["route"], "noop")

    def test_sidecar_cannot_escape_factory(self):
        self.api.write_text(self.api.read_text(encoding="utf-8").replace(
            "sidecar: api-send.yaml", "sidecar: ../../../../outside.yaml"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "escapes root"):
            PATCH.plan(self.root, self.base)

    def test_cli_preserves_baseline_and_fails_closed_for_missing_or_invalid_input(self):
        baseline = self.root / ".verification" / "baseline.json"
        capture = subprocess.run([sys.executable, str(SCRIPT), "snapshot", str(self.root),
                                  "--out", str(baseline)], capture_output=True, text=True)
        self.assertEqual(capture.returncode, 0, capture.stderr)
        before = baseline.read_bytes()
        self.change(self.api)
        command = [sys.executable, str(SCRIPT), "plan", str(self.root), "--baseline", str(baseline)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["route"], "patch")
        self.assertEqual(baseline.read_bytes(), before)
        baseline.write_text("{}", encoding="utf-8")
        invalid = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(json.loads(invalid.stdout)["route"], "full")
        baseline.unlink()
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["route"], "full")


if __name__ == "__main__":
    unittest.main()
