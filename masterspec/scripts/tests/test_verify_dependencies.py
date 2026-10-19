from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "check-operational-envelope.py"
EXAMPLE = SCRIPT.parents[1] / "examples" / "operational-envelope-factory"
REQUIREMENTS = SCRIPT.resolve().with_name("requirements.txt")

# An import hook lives only in the child process: installed packages and the
# environment running the rest of the suite remain untouched.
ISOLATED_CLI = textwrap.dedent("""\
    import builtins
    import runpy
    import sys

    missing = sys.argv[1]
    sys.argv = sys.argv[2:]
    original_import = builtins.__import__

    def import_without_dependency(name, *args, **kwargs):
        if name == missing or name.startswith(missing + "."):
            raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
        return original_import(name, *args, **kwargs)

    builtins.__import__ = import_without_dependency
    runpy.run_path(sys.argv[0], run_name="__main__")
""")


class VerifyDependencyPreflightTest(unittest.TestCase):
    def cli(self, root: Path, layer: str, missing: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-c", ISOLATED_CLI,
             missing, str(SCRIPT), str(root), "--layer", layer],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def assert_dependency_blocker(self, result: subprocess.CompletedProcess[str], missing: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        self.assertTrue(lines[0].startswith("BLOCKER:"), result.stdout)
        self.assertIn(missing, lines[0])
        self.assertIn(f'python -m pip install -r "{REQUIREMENTS}"', lines[0])
        self.assertNotIn("(F2)", result.stdout)
        self.assertNotIn("OE metrics:", result.stdout)

    def test_missing_jsonschema_stops_spec_and_code_before_sidecar_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "factory"
            shutil.copytree(EXAMPLE, root)
            apis = root / "02-specifications" / "04-apis" / "external"
            original = apis / "api-notification-channel.md"
            # Multiple contract companions previously repeated the same F2.
            for number in range(3):
                (apis / f"api-extra-{number}.md").write_text(
                    original.read_text(encoding="utf-8"), encoding="utf-8",
                )
            for layer in ("spec", "code"):
                with self.subTest(layer=layer):
                    result = self.cli(root, layer, "jsonschema")
                    self.assert_dependency_blocker(result, "jsonschema")
                    self.assertNotIn("api-notification-channel", result.stdout)

    def test_missing_dependencies_are_reported_before_factory_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            nonexistent = Path(directory) / "not-a-factory"
            cases = [("req", "yaml"), ("spec", "yaml"), ("code", "yaml"),
                     ("spec", "jsonschema"), ("code", "jsonschema"),
                     ("spec", "jsonschema_specifications"), ("spec", "referencing")]
            for layer, missing in cases:
                with self.subTest(layer=layer, missing=missing):
                    self.assert_dependency_blocker(self.cli(nonexistent, layer, missing), missing)

    def test_req_layer_remains_usable_without_jsonschema(self) -> None:
        result = self.cli(EXAMPLE, "req", "jsonschema")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("BLOCKER:", result.stdout)
        self.assertIn("OE metrics:", result.stdout)


if __name__ == "__main__":
    unittest.main()
