from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "check-verify-report.py"
SPEC = importlib.util.spec_from_file_location("check_verify_report", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


def report(machine: int = 3, total: int = 4, percent: str = "75.00") -> str:
    return f"""---
type: verify-report
factory: demo
scope: spec
preset: full
last_verified: 2026-07-13
verified_revision: abc123
started_at: 2026-07-13T10:00:00Z
finished_at: 2026-07-13T10:01:30Z
---
# Verify-report

- last_verified: 2026-07-13
- verification_age_days: 0
- oldest_element_last_verified: 2026-07-12
- oldest_element_age_days: 1
- stale_after_days: 14
- stale_elements: 0
- wall_time_seconds: 90.0
- agent_calls: 2
- input_tokens: N/A — runtime has no counter
- output_tokens: 1200
- cached_input_tokens: 0
- estimated_cost: N/A — tariff unavailable
- cost_basis: N/A — tariff unavailable
- axis_runs_total: {total}
- axis_runs_machine: {machine}
- machine_axes_percent: {percent}
"""


class VerifyReportCheckerTest(unittest.TestCase):
    def check(self, content: str, *, today: date | None = None, now: datetime | None = None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verify-report.md"
            path.write_text(content, encoding="utf-8")
            return CHECKER.validate(
                path, today=today, now=now or datetime(2026, 7, 14, tzinfo=timezone.utc)
            )

    def test_accepts_complete_telemetry_and_reasoned_na(self) -> None:
        _, errors = self.check(report())
        self.assertEqual(errors, [])

    def patch_report(self) -> str:
        return report().replace("preset: full\n", "preset: full\nmode: patch\n"
                                "baseline: .verification/patches/run/baseline.json\n"
                                "plan: .verification/patches/run/plan.json\n"
                                f"verified_inputs_digest: {'a' * 64}\n") + """
- patch_ready: yes
- spec_ready: N/A — local verification
- codegen_ready: N/A — local verification
- cascade_ready: N/A — local verification
"""

    def test_accepts_partial_report_with_evidence_without_layer_certificate(self) -> None:
        data, errors = self.check(self.patch_report())
        self.assertEqual(errors, [])
        self.assertEqual(data["patch_ready"], "yes")

    def test_patch_report_cannot_certify_layer_or_change_readiness(self) -> None:
        for field in ("spec_ready", "codegen_ready", "cascade_ready"):
            with self.subTest(field=field):
                content = self.patch_report().replace(f"{field}: N/A — local verification", f"{field}: yes")
                _, errors = self.check(content)
                self.assertIn("patch report cannot certify readiness of the whole layer/change", errors)

    def test_patch_report_cannot_hide_duplicate_green_claim(self) -> None:
        content = self.patch_report().replace("- codegen_ready: N/A", "- codegen_ready: yes\n- codegen_ready: N/A")
        _, errors = self.check(content)
        self.assertIn("patch report cannot certify readiness of the whole layer/change", errors)

    def test_partial_report_requires_evidence_digest_verdict_and_mode(self) -> None:
        for line in ("baseline: .verification/patches/run/baseline.json\n",
                     "plan: .verification/patches/run/plan.json\n",
                     f"verified_inputs_digest: {'a' * 64}\n", "- patch_ready: yes\n", "mode: patch\n"):
            with self.subTest(line=line):
                _, errors = self.check(self.patch_report().replace(line, ""))
                self.assertTrue(errors)

    def test_patch_mode_does_not_support_req(self) -> None:
        _, errors = self.check(self.patch_report().replace("scope: spec", "scope: req"))
        self.assertIn("patch mode requires scope=spec or change", errors)

    def test_change_patch_report_requires_identity_without_cascade_certificate(self) -> None:
        text = self.patch_report().replace("scope: spec", "scope: change\nchange: changes/price")
        _, errors = self.check(text)
        self.assertEqual(errors, [])
        _, errors = self.check(text.replace("change: changes/price\n", ""))
        self.assertIn("change patch report requires change evidence path", errors)
        _, errors = self.check(text.replace("cascade_ready: N/A — local verification", "cascade_ready: yes"))
        self.assertIn("patch report cannot certify readiness of the whole layer/change", errors)

    def test_accepts_unknown_staleness_policy_without_invented_measurement(self) -> None:
        content = report().replace("stale_after_days: 14", "stale_after_days: N/A — factory defines no threshold")
        content = content.replace("stale_elements: 0", "stale_elements: N/A — no threshold to classify elements")
        data, errors = self.check(content)
        self.assertEqual(errors, [])
        self.assertEqual(data["stale_after_days"], "N/A — factory defines no threshold")
        self.assertEqual(data["stale_elements"], "N/A — no threshold to classify elements")

    def test_rejects_numeric_stale_count_without_threshold_including_zero(self) -> None:
        for count in (0, 2):
            with self.subTest(count=count):
                content = report().replace("stale_after_days: 14", "stale_after_days: N/A — no policy")
                content = content.replace("stale_elements: 0", f"stale_elements: {count}")
                _, errors = self.check(content)
                self.assertIn("stale_elements must be 'N/A — reason' when stale_after_days is N/A", errors)

    def test_accepts_unmeasured_stale_count_with_known_threshold_and_reason(self) -> None:
        content = report().replace("stale_elements: 0", "stale_elements: N/A — element inventory is incomplete")
        _, errors = self.check(content)
        self.assertEqual(errors, [])

    def test_accepts_explicit_zero_staleness_threshold(self) -> None:
        content = report().replace("stale_after_days: 14", "stale_after_days: 0")
        content = content.replace("stale_elements: 0", "stale_elements: 1")
        _, errors = self.check(content)
        self.assertEqual(errors, [])

    def test_requires_staleness_na_reasons_and_nonnegative_integer_counts(self) -> None:
        for field, original in (("stale_after_days", "14"), ("stale_elements", "0")):
            for value in ("N/A", "N/A —", "N/A -", "-1", "1.5"):
                with self.subTest(field=field, value=value):
                    content = report().replace(f"{field}: {original}", f"{field}: {value}")
                    _, errors = self.check(content)
                    self.assertIn(f"{field} must be a non-negative integer or 'N/A — reason'", errors)

    def test_rejects_incorrect_machine_axis_percentage(self) -> None:
        _, errors = self.check(report(percent="80.00"))
        self.assertIn("machine_axes_percent does not equal machine/total × 100", errors)

    def test_rejects_blank_token_counter(self) -> None:
        _, errors = self.check(report().replace("input_tokens: N/A — runtime has no counter", "input_tokens:"))
        self.assertIn("missing/template metric input_tokens", errors)

    def test_rejects_zero_token_counter(self) -> None:
        # Нулевой счётчик потреблённых токенов = дыра телеметрии, не «бесплатно».
        _, errors = self.check(report().replace("output_tokens: 1200", "output_tokens: 0"))
        self.assertIn(
            "output_tokens must be positive or 'N/A — reason' (zero hides an unmeasured value)",
            errors,
        )

    def test_rejects_zero_estimated_cost(self) -> None:
        _, errors = self.check(
            report().replace("estimated_cost: N/A — tariff unavailable", "estimated_cost: 0.00 USD")
        )
        self.assertIn(
            "estimated_cost must be positive or 'N/A — reason' (zero cost hides an unmeasured value)",
            errors,
        )

    def test_accepts_zero_cached_tokens(self) -> None:
        # cached_input_tokens=0 (холодный кеш) законно — фикстура уже содержит 0.
        _, errors = self.check(report())
        self.assertEqual(errors, [])

    def test_ages_remain_at_report_date_when_checked_later(self) -> None:
        _, errors = self.check(report(), now=datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(errors, [])

    def test_explicit_age_reference_override_is_preserved(self) -> None:
        content = report().replace("verification_age_days: 0", "verification_age_days: 2")
        content = content.replace("oldest_element_age_days: 1", "oldest_element_age_days: 3")
        _, errors = self.check(content, today=date(2026, 7, 15))
        self.assertEqual(errors, [])

    def test_date_fields_use_finished_at_calendar_across_utc_midnight(self) -> None:
        cases = (
            # Report's calendar is one day ahead of UTC; the run crosses local midnight.
            ("2026-07-12T23:59:30+03:00", "2026-07-13T00:01:00+03:00", "2026-07-12T21:02:00Z"),
            # Report's calendar is one day behind UTC.
            ("2026-07-13T23:58:00-07:00", "2026-07-13T23:59:30-07:00", "2026-07-14T07:00:00Z"),
            # A UTC report validated by a runtime whose calendar is still yesterday.
            ("2026-07-13T00:00:00Z", "2026-07-13T00:01:30Z", "2026-07-12T17:02:00-07:00"),
        )
        for start, finish, now in cases:
            with self.subTest(finish=finish, now=now):
                content = report().replace("2026-07-13T10:00:00Z", start)
                content = content.replace("2026-07-13T10:01:30Z", finish)
                _, errors = self.check(content, now=datetime.fromisoformat(now.replace("Z", "+00:00")))
                self.assertEqual(errors, [])

    def test_does_not_accept_date_fields_after_report_date(self) -> None:
        for field in ("last_verified", "oldest_element_last_verified"):
            with self.subTest(field=field):
                old = "2026-07-13" if field == "last_verified" else "2026-07-12"
                content = report().replace(f"{field}: {old}", f"{field}: 2026-07-14")
                _, errors = self.check(content)
                self.assertIn(f"{field} is in the future", errors)

    def test_rejects_future_finish_even_with_consistent_date_fields(self) -> None:
        _, errors = self.check(report(), now=datetime(2026, 7, 13, 10, 1, 29, tzinfo=timezone.utc))
        self.assertIn("finished_at is in the future", errors)

    def test_rejects_wrong_age_at_report_date(self) -> None:
        content = report().replace("verification_age_days: 0", "verification_age_days: 1")
        content = content.replace("oldest_element_age_days: 1", "oldest_element_age_days: 2")
        _, errors = self.check(content)
        self.assertIn("verification_age_days is 1, expected 0", errors)
        self.assertIn("oldest_element_age_days is 2, expected 1", errors)

    def test_requires_timezone_for_both_timestamps_without_crashing(self) -> None:
        for field, value in (
            ("started_at", "2026-07-13T10:00:00Z"),
            ("finished_at", "2026-07-13T10:01:30Z"),
        ):
            with self.subTest(field=field):
                _, errors = self.check(report().replace(value, value.removesuffix("Z")))
                self.assertIn(f"{field} must include an explicit timezone (Z or UTC offset)", errors)

    def test_rejects_malformed_timezone(self) -> None:
        _, errors = self.check(report().replace("2026-07-13T10:01:30Z", "2026-07-13T10:01:30+25:00"))
        self.assertIn("finished_at must be an ISO-8601 timestamp", errors)

    def test_compares_timestamp_order_as_instants(self) -> None:
        content = report().replace("2026-07-13T10:00:00Z", "2026-07-13T01:00:00+03:00")
        content = content.replace("2026-07-13T10:01:30Z", "2026-07-13T00:00:00+01:00")
        _, errors = self.check(content)
        self.assertEqual(errors, [])

        content = report().replace("2026-07-13T10:00:00Z", "2026-07-13T00:00:00+01:00")
        content = content.replace("2026-07-13T10:01:30Z", "2026-07-13T01:00:00+03:00")
        _, errors = self.check(content)
        self.assertIn("finished_at precedes started_at", errors)


if __name__ == "__main__":
    unittest.main()
