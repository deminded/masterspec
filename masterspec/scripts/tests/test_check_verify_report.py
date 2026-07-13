from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date
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
    def check(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verify-report.md"
            path.write_text(content, encoding="utf-8")
            return CHECKER.validate(path, today=date(2026, 7, 13))

    def test_accepts_complete_telemetry_and_reasoned_na(self) -> None:
        _, errors = self.check(report())
        self.assertEqual(errors, [])

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


if __name__ == "__main__":
    unittest.main()
