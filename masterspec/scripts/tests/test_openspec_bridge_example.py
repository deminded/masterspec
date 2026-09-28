"""Meaningful replay checks for the checked-in native OpenSpec import example."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "masterspec-apply-from-openspec/examples/code-factory/replay.py"
SPEC = importlib.util.spec_from_file_location("openspec_example", EXAMPLE)
example = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example)


class OpenSpecBridgeExampleTests(unittest.TestCase):
    def test_apply_matches_reviewed_snapshot_and_replay_is_noop(self):
        with example.Replay() as run:
            self.assertEqual(run.apply(), "applied-in-disposable-example")
            self.assertEqual(run.factory_tree(), example.tree(example.HERE / "after/masterspec"))
            self.assertEqual(run.apply(), "no-op")
            run.assert_untouched()

    def test_stale_source_blocks_before_any_factory_write(self):
        with example.Replay() as run:
            delta = run.source / "specs/pricing/quotes/spec.md"
            delta.write_text(delta.read_text(encoding="utf-8").replace("20 percent", "21 percent"), encoding="utf-8")
            before = run.factory_tree()
            with self.assertRaisesRegex(ValueError, "inventory is stale"):
                run.apply()
            self.assertEqual(run.factory_tree(), before)

    def test_stale_target_blocks_before_any_factory_write(self):
        with example.Replay() as run:
            function = run.factory / "01-requirements/02-functions/fn-calculate-quote.md"
            function.write_text(function.read_text(encoding="utf-8") + "\nЧужая согласованная норма.\n", encoding="utf-8")
            before = run.factory_tree()
            with self.assertRaisesRegex(ValueError, "stale target"):
                run.apply()
            self.assertEqual(run.factory_tree(), before)

    def test_wrong_before_is_not_silently_replaced(self):
        with example.Replay() as run:
            change = run.change / "change.md"
            text = change.read_text(encoding="utf-8")
            text = text.replace("итоговая сумма 12.\n```", "итоговая сумма 99.\n```", 1)
            change.write_text(text, encoding="utf-8")
            before = run.factory_tree()
            with self.assertRaisesRegex(ValueError, "BEFORE does not match"):
                run.apply()
            self.assertEqual(run.factory_tree(), before)

    def test_report_identity_does_not_hide_post_apply_drift(self):
        with example.Replay() as run:
            run.apply()
            target = run.factory / "02-specifications/01-components/cmp-quote-policy.md"
            target.write_text(target.read_text(encoding="utf-8") + "\nНовая обязанность.\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "postconditions drifted"):
                run.apply()


if __name__ == "__main__":
    unittest.main()
