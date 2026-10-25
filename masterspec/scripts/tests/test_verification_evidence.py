from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load("test_pending", "check-pending.py")
STATE = GATE.STATE
PATCH = STATE.PATCH
CHANGE = load("test_evidence_change", "change-patch.py")
CHECKER = GATE.CHECKER
telemetry = load("evidence_report_fixture", "tests/test_check_verify_report.py").report


class VerificationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.factory = self.root / "factory"
        self.factory.mkdir()
        self.component = self.artifact("02-specifications/01-components", "cmp-owner", "component", "## Detail\nOriginal.")
        self.artifact("02-specifications/01-components", "cmp-isolated", "component", "Unrelated.")
        self.artifact("02-specifications/02-scenarios", "scn-call", "scenario", "-> cmp-owner")
        self.change = self.factory / "changes/update"
        self.change.mkdir(parents=True)
        relative = self.component.relative_to(self.factory).as_posix()
        (self.change / "change.md").write_text(f"""# Change: update
> **Статус**: Черновик
> **Область**: spec-only
## 1. Мотивация
Clarify the design.
## 2. Затронутые артефакты
### 2.1. MODIFIED
| # | Тип | Slug | Путь | Что меняется |
|---|---|---|---|---|
| 1 | component | cmp-owner | {relative} | Detail |
### 2.2. ADDED
Нет изменений.
### 2.3. REMOVED
Нет изменений.
## 3. Обратная совместимость
Preserved.
## 4. MODIFIED
### 4.1. cmp-owner — detail
**Файл**: `{relative}`
**Раздел**: `## Detail`
**Тип правки**: modify-bullet
ДО:
```
Original.
```
ПОСЛЕ:
```
Proposed.
```
## 5. Файлы
Нет изменений.
## 6. REMOVED
Нет изменений.
## 7. Влияние
The caller remains compatible.
## 8. Критерии
The detail is explicit.
""", encoding="utf-8")
        self.sequence = 0

    def artifact(self, directory, slug, kind, body):
        path = self.factory / directory / (slug + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: {kind}\nslug: {slug}\nfactory: demo\nstatus: draft\n---\n# {slug}\n{body}\n", encoding="utf-8")
        return path

    def report_text(self, scope, mode, started, finished, fields, readiness="yes", preset="full"):
        today = finished.date().isoformat()
        text = telemetry().replace("2026-07-13T10:00:00Z", started.isoformat())
        text = text.replace("2026-07-13T10:01:30Z", finished.isoformat())
        text = text.replace("2026-07-13", today).replace("2026-07-12", today)
        text = text.replace("oldest_element_age_days: 1", "oldest_element_age_days: 0")
        text = text.replace("scope: spec", "scope: " + scope)
        header = f"preset: {preset}\nmode: {mode}\n" + "".join(f"{key}: {value}\n" for key, value in fields.items())
        if scope == "change":
            header += f"change: {self.change.as_posix()}\n"
        text = text.replace("preset: full\n", header)
        for name in ("spec_ready", "codegen_ready", "cascade_ready"):
            value = readiness if mode == "full" and name == ("cascade_ready" if scope == "change" else "codegen_ready") else "N/A — local or other scope"
            text += f"- {name}: {value}\n"
        if mode == "patch":
            text += f"- patch_ready: {readiness}\n"
        return text

    def patch_report(self, scope="spec", extra_rules=None):
        self.sequence += 1
        started = datetime.now(timezone.utc)
        if scope == "spec":
            baseline = PATCH.snapshot(self.factory, extra_rules)
            with self.component.open("a", encoding="utf-8") as stream:
                stream.write(f"\nClarified {self.sequence}.\n")
            plan = PATCH.plan(self.factory, baseline, ["cmp-owner"])
            owner = self.factory
        else:
            baseline = CHANGE.snapshot(self.factory, self.change, extra_rules)
            path = self.change / "change.md"
            path.write_text(path.read_text(encoding="utf-8").replace("Proposed.", "Proposed. Clarified."), encoding="utf-8")
            plan = CHANGE.plan(self.factory, self.change, baseline, ["cmp-owner"])
            owner = self.change
        self.assertEqual(plan["route"], "patch")
        run = owner / f".verification/patches/run{self.sequence}"
        baseline_path, plan_path = run / "baseline.json", run / "plan.json"
        PATCH.write_json(baseline_path, baseline)
        PATCH.write_json(plan_path, plan)
        path = owner / f"verify-patch-{self.sequence}.md"
        text = self.report_text(scope, "patch", started, datetime.now(timezone.utc),
                                {"baseline": baseline_path.as_posix(), "plan": plan_path.as_posix(),
                                 "verified_inputs_digest": plan["current_digest"]})
        path.write_text(text, encoding="utf-8")
        return path, plan_path

    def full_report(self, scope="spec", readiness="yes", preset="full", extra_rules=None):
        self.sequence += 1
        started = datetime.now(timezone.utc)
        change = self.change if scope == "change" else None
        state = STATE.capture(self.factory, scope, change, extra_rules)
        owner = STATE.owner(self.factory, scope, change)
        inputs = owner / f".verification/full/run{self.sequence}/inputs.json"
        PATCH.write_json(inputs, state)
        path = owner / "verify-report.md"
        text = self.report_text(scope, "full", started, datetime.now(timezone.utc),
                                {"inputs": inputs.as_posix(), "verified_inputs_digest": STATE.state_digest(state)},
                                readiness=readiness, preset=preset)
        path.write_text(text, encoding="utf-8")
        return path, inputs

    def test_patch_report_replays_plan_and_current_tree_for_both_workflows(self):
        for scope in ("spec", "change"):
            with self.subTest(scope=scope):
                path, _ = self.patch_report(scope)
                _, errors = CHECKER.validate(path)
                self.assertEqual(errors, [])

    def test_report_digest_must_match_saved_plan(self):
        path, _ = self.patch_report()
        text = path.read_text(encoding="utf-8")
        digest = CHECKER.frontmatter(text)["verified_inputs_digest"]
        path.write_text(text.replace(digest, "0" * 64), encoding="utf-8")
        _, errors = CHECKER.validate(path)
        self.assertTrue(any("plan.current_digest" in error for error in errors))

    def test_tampered_scope_is_rejected_even_when_plan_digest_matches(self):
        path, plan_path = self.patch_report()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["verify_artifacts"] = []
        PATCH.write_json(plan_path, plan)
        _, errors = CHECKER.validate(path)
        self.assertTrue(any("saved plan differs" in error for error in errors))

    def test_patch_report_cannot_be_reused_after_tree_or_rules_change(self):
        rule = self.root / "rule.md"
        rule.write_text("Original rule", encoding="utf-8")
        path, _ = self.patch_report(extra_rules=[str(rule)])
        rule.write_text("New rule", encoding="utf-8")
        self.assertTrue(CHECKER.validate(path)[1])
        rule.write_text("Original rule", encoding="utf-8")
        with self.component.open("a", encoding="utf-8") as stream:
            stream.write("Another change.\n")
        self.assertTrue(CHECKER.validate(path)[1])

    def test_absent_pending_keeps_existing_accept_apply_workflows_compatible(self):
        self.assertFalse(GATE.check(self.factory, "spec"))
        self.assertFalse(GATE.check(self.factory, "change", self.change))

    def test_full_fresh_report_clears_only_selected_pending_marker(self):
        for scope in ("spec", "change"):
            with self.subTest(scope=scope):
                change = self.change if scope == "change" else None
                marker = GATE.mark(self.factory, scope, change)
                self.full_report(scope)
                self.assertTrue(GATE.check(self.factory, scope, change, clear=True))
                self.assertFalse(marker.exists())

    def test_local_report_does_not_clear_pending(self):
        marker = GATE.mark(self.factory, "spec")
        path, _ = self.patch_report()
        with self.assertRaises(ValueError):
            GATE.check(self.factory, "spec", report=path, clear=True)
        self.assertTrue(marker.exists())

    def test_full_report_needs_full_preset_and_positive_global_readiness(self):
        marker = GATE.mark(self.factory, "spec")
        for ready, preset in (("no", "full"), ("yes", "core")):
            with self.subTest(ready=ready, preset=preset):
                self.full_report(readiness=ready, preset=preset)
                with self.assertRaises(ValueError):
                    GATE.check(self.factory, "spec", clear=True)
                self.assertTrue(marker.exists())

    def test_full_report_is_invalid_after_tree_change(self):
        marker = GATE.mark(self.factory, "spec")
        self.full_report()
        with self.component.open("a", encoding="utf-8") as stream:
            stream.write("New fact after verification.\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            GATE.check(self.factory, "spec", clear=True)
        self.assertTrue(marker.exists())

    def test_full_report_before_pending_does_not_clear_a_new_patch_run(self):
        self.full_report()
        marker = GATE.mark(self.factory, "spec")
        with self.assertRaisesRegex(ValueError, "predates"):
            GATE.check(self.factory, "spec", clear=True)
        self.assertTrue(marker.exists())

    def test_legacy_full_report_without_input_proof_cannot_clear_pending(self):
        marker = GATE.mark(self.factory, "spec")
        path = self.factory / "verify-report.md"
        path.write_text(telemetry().replace("preset: full\n", "preset: full\nmode: full\n")
                        + "- codegen_ready: yes\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inputs and digest"):
            GATE.check(self.factory, "spec", clear=True)
        self.assertTrue(marker.exists())

    def test_change_gate_supports_approved_revision_without_reopening_it(self):
        path = self.change / "change.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Черновик", "Согласовано"), encoding="utf-8")
        marker = GATE.mark(self.factory, "change", self.change)
        before = path.read_bytes()
        self.full_report("change")
        GATE.check(self.factory, "change", self.change, clear=True)
        self.assertFalse(marker.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_wrong_scope_or_change_cannot_satisfy_gate(self):
        marker = GATE.mark(self.factory, "spec")
        path, _ = self.full_report("change")
        with self.assertRaises(ValueError):
            GATE.check(self.factory, "spec", report=path, clear=True)
        self.assertTrue(marker.exists())
        GATE.mark(self.factory, "change", self.change)
        other = self.factory / "changes/other"
        other.mkdir()
        (other / "change.md").write_text("Another proposal", encoding="utf-8")
        GATE.mark(self.factory, "change", other)
        with self.assertRaises(ValueError):
            GATE.check(self.factory, "change", other, report=path, clear=True)

    def test_cli_blocks_without_report_and_clears_after_full_verification(self):
        command = [sys.executable, str(SCRIPTS / "check-pending.py")]
        args = [str(self.factory), "--scope", "spec"]
        marked = subprocess.run(command + ["mark"] + args, capture_output=True, text=True)
        self.assertEqual(marked.returncode, 0, marked.stderr)
        blocked = subprocess.run(command + ["check"] + args, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 1)
        self.full_report()
        passed = subprocess.run(command + ["clear"] + args, capture_output=True, text=True)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertFalse(GATE.marker_path(self.factory, "spec").exists())

    def test_capture_cli_preserves_existing_preverification_inputs(self):
        path = self.factory / ".verification/full/run/inputs.json"
        command = [sys.executable, str(SCRIPTS / "check-pending.py"), "capture", str(self.factory),
                   "--scope", "spec", "--out", str(path)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = path.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
