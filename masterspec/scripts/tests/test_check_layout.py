from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "check-layout.py"
SPEC = importlib.util.spec_from_file_location("check_layout", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


def _write(root: Path, rel: str, frontmatter: str, body: str = "# doc\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


def _fm(type_: str, slug: str, extra: str = "") -> str:
    return f"type: {type_}\nslug: {slug}\nfactory: test-factory\nstatus: draft\nupdated: 2026-01-01\n{extra}"


def _snapshot(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class RoutingTableParseTest(unittest.TestCase):
    """(5) Парсинг artifact-routing.md §1 даёт непустую карту с алиасами — по РЕАЛЬНОМУ файлу,
    карта type -> путь не хардкодится в скрипте."""

    def test_routing_map_parses_real_registry_with_aliases(self) -> None:
        text = CHECKER.default_routing_path().read_text(encoding="utf-8")
        aliases = CHECKER.load_routing_map(text)
        self.assertGreater(len(aliases), 20)
        for canonical, alias in (
            ("component", "cmp"),
            ("function", "fn"),
            ("scenario", "scn"),
            ("decision-record", "dr"),
        ):
            self.assertIs(aliases[canonical], aliases[alias])
        self.assertEqual(
            aliases["component"].dir, "02-specifications/01-components"
        )
        self.assertEqual(
            aliases["api"].scope_dirs,
            {
                "internal": "02-specifications/04-apis/internal",
                "external": "02-specifications/04-apis/external",
            },
        )
        self.assertTrue(aliases["function"].block_field)
        self.assertTrue(aliases["decision-record"].skip)
        self.assertEqual(aliases["repo-map"].fixed_file, "03-codemap/00-repo-map.md")
        self.assertEqual(aliases["masterspec-index"].fixed_file, "00-masterspec-index.md")


class LayoutCheckerTest(unittest.TestCase):
    """(1)-(4): построение мини-фабрики с артефактами ВАЛОМ в корне слоя + уже разложенными,
    проверка check/fix/apply/идемпотентность."""

    def _build_factory(self, root: Path) -> Path:
        _write(root, "00-masterspec-index.md", _fm("masterspec-index", "idx"))

        # --- misplaced: ВАЛОМ в корне слоя, вместо канонического подкаталога ---
        _write(root, "02-specifications/cmp-foo.md", _fm("component", "cmp-foo"))
        _write(root, "03-codemap/cmap-bar.md", _fm("component-map", "cmap-bar", "generated: true\n"))
        _write(
            root,
            "02-specifications/04-apis/api-baz.md",
            _fm("api", "api-baz", "scope: internal\n"),
        )
        _write(
            root,
            "02-specifications/04-apis/api-ext.md",
            _fm(
                "api", "api-ext",
                "scope: external\nsidecar: api-ext.openapi.yaml\nsidecar_format: openapi-3.1\n",
            ),
        )
        (root / "02-specifications/04-apis/api-ext.openapi.yaml").write_text(
            "openapi: 3.1.0\npaths: {}\n", encoding="utf-8"
        )
        _write(
            root,
            "01-requirements/02-functions/fn-wrong.md",
            _fm("function", "fn-wrong", "block: blockA\ncriticality: medium\n"),
        )

        # --- decision-record: путь не проверяем статически (skip), независимо от расположения ---
        _write(root, "01-requirements/dr-cmp-foo-choice.md", _fm("decision-record", "dr-cmp-foo-choice"))

        # --- already correctly laid out — must NOT be flagged ---
        _write(root, "02-specifications/01-components/cmp-good.md", _fm("component", "cmp-good"))
        _write(
            root,
            "03-codemap/01-component-maps/cmap-good.md",
            _fm("component-map", "cmap-good", "generated: true\n"),
        )
        _write(
            root,
            "02-specifications/04-apis/external/api-good.md",
            _fm("api", "api-good", "scope: external\n"),
        )
        _write(
            root,
            "01-requirements/02-functions/fn-plain.md",
            _fm("function", "fn-plain", "criticality: low\n"),
        )
        _write(
            root,
            "01-requirements/02-functions/blockA/fn-blocked.md",
            _fm("function", "fn-blocked", "block: blockA\ncriticality: low\n"),
        )
        return root

    def _aliases(self):
        return CHECKER.load_routing_map(
            CHECKER.default_routing_path().read_text(encoding="utf-8")
        )

    # ---- (1) check ловит именно misplaced и не флагует правильные ----
    def test_check_flags_only_misplaced(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._build_factory(Path(d))
            aliases = self._aliases()
            misplaced, checked = CHECKER.assess_factory(root, aliases)

            self.assertEqual(checked, 10)  # 5 misplaced + 5 correctly-placed; dr/index excluded
            misplaced_names = {item.path.name for item in misplaced}
            self.assertEqual(
                misplaced_names,
                {"cmp-foo.md", "cmap-bar.md", "api-baz.md", "api-ext.md", "fn-wrong.md"},
            )
            correct_names = {"cmp-good.md", "cmap-good.md", "api-good.md", "fn-plain.md", "fn-blocked.md"}
            self.assertFalse(misplaced_names & correct_names)

            by_name = {item.path.name: item for item in misplaced}
            self.assertEqual(
                by_name["cmp-foo.md"].placement.expected_dir, "02-specifications/01-components"
            )
            self.assertEqual(
                by_name["cmap-bar.md"].placement.expected_dir, "03-codemap/01-component-maps"
            )
            self.assertEqual(
                by_name["api-baz.md"].placement.expected_dir, "02-specifications/04-apis/internal"
            )
            self.assertEqual(
                by_name["api-ext.md"].placement.expected_dir, "02-specifications/04-apis/external"
            )
            self.assertEqual(
                by_name["fn-wrong.md"].placement.expected_dir,
                "01-requirements/02-functions/blockA",
            )

            # CLI-level: exit code + printed report shape (YAML block + summary counters)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = CHECKER.run(root, fix=False, apply=False)
            self.assertEqual(exit_code, 1)
            printed = output.getvalue()
            self.assertIn("checked: 10, misplaced: 5", printed)
            yaml_block, _, _ = printed.rpartition("checked: 10, misplaced: 5")
            violations = CHECKER.yaml.safe_load(yaml_block)
            self.assertEqual(len(violations), 5)
            self.assertEqual(set(violations[0]), {"file", "type", "actual_dir", "expected_dir"})

    # ---- (2) fix dry-run ничего не двигает ----
    def test_fix_dry_run_moves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._build_factory(Path(d))
            before = _snapshot(root)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = CHECKER.run(root, fix=True, apply=False)
            after = _snapshot(root)
            self.assertEqual(before, after)
            self.assertEqual(exit_code, 1)
            self.assertIn("mv ", output.getvalue())
            self.assertIn("planned: 6", output.getvalue())  # 5 misplaced + 1 sidecar

    # ---- (3) fix --apply раскладывает всё в канон; сайдкар едет с компаньоном ----
    def test_fix_apply_lays_out_canonically(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._build_factory(Path(d))
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = CHECKER.run(root, fix=True, apply=True)
            self.assertEqual(exit_code, 0)
            self.assertIn("moved: 6", output.getvalue())

            expect_present = [
                "02-specifications/01-components/cmp-foo.md",
                "03-codemap/01-component-maps/cmap-bar.md",
                "02-specifications/04-apis/internal/api-baz.md",
                "02-specifications/04-apis/external/api-ext.md",
                "02-specifications/04-apis/external/api-ext.openapi.yaml",  # sidecar traveled with companion
                "01-requirements/02-functions/blockA/fn-wrong.md",
            ]
            for rel in expect_present:
                self.assertTrue((root / rel).is_file(), rel)

            expect_gone = [
                "02-specifications/cmp-foo.md",
                "03-codemap/cmap-bar.md",
                "02-specifications/04-apis/api-baz.md",
                "02-specifications/04-apis/api-ext.md",
                "02-specifications/04-apis/api-ext.openapi.yaml",
                "01-requirements/02-functions/fn-wrong.md",
            ]
            for rel in expect_gone:
                self.assertFalse((root / rel).exists(), rel)

            aliases = self._aliases()
            misplaced, checked = CHECKER.assess_factory(root, aliases)
            self.assertEqual(misplaced, [])
            self.assertEqual(checked, 10)

    # ---- (4) повторный apply — ноль перемещений ----
    def test_fix_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = self._build_factory(Path(d))
            CHECKER.run(root, fix=True, apply=True)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = CHECKER.run(root, fix=True, apply=True)
            self.assertEqual(exit_code, 0)
            self.assertIn("moved: 0", output.getvalue())


class ScopeAndBlockEdgeCasesTest(unittest.TestCase):
    """§2: api без scope — нарушение (needs scope), но не падаем; --fix её не двигает."""

    def test_missing_scope_is_flagged_but_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "00-masterspec-index.md", _fm("masterspec-index", "idx"))
            _write(root, "02-specifications/04-apis/api-noscope.md", _fm("api", "api-noscope"))
            aliases = CHECKER.load_routing_map(
                CHECKER.default_routing_path().read_text(encoding="utf-8")
            )
            misplaced, checked = CHECKER.assess_factory(root, aliases)
            self.assertEqual(checked, 1)
            self.assertEqual(len(misplaced), 1)
            self.assertIsNone(misplaced[0].placement.expected_file)
            self.assertIn("scope", misplaced[0].placement.reason)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = CHECKER.run(root, fix=True, apply=True)
            self.assertEqual(exit_code, 0)
            self.assertIn("unfixable: 1", output.getvalue())
            self.assertTrue((root / "02-specifications/04-apis/api-noscope.md").is_file())

    def test_function_without_block_accepts_root_or_any_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "00-masterspec-index.md", _fm("masterspec-index", "idx"))
            _write(root, "01-requirements/02-functions/fn-a.md", _fm("function", "fn-a"))
            _write(root, "01-requirements/02-functions/blockX/fn-b.md", _fm("function", "fn-b"))
            aliases = CHECKER.load_routing_map(
                CHECKER.default_routing_path().read_text(encoding="utf-8")
            )
            misplaced, checked = CHECKER.assess_factory(root, aliases)
            self.assertEqual(checked, 2)
            self.assertEqual(misplaced, [])


if __name__ == "__main__":
    unittest.main()
