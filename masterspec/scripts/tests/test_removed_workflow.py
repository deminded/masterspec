"""Execute the documented REMOVED metadata reader without requiring Bash."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[3] / "masterspec-apply-change" /
            "references" / "merge-workflow.md")


class RemovedWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        document = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(r'''if ! sidecar=\$\(python3 - "\$target" <<'PY'\n(.*?)\nPY\n''',
                          document, re.S)
        self.assertIsNotNone(match, "REMOVED metadata reader must guard errors before rm")
        self.reader = match[1]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / "legacy-note.md"

    def read(self, text: str) -> subprocess.CompletedProcess[str]:
        self.target.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "-X", "utf8", "-", str(self.target)],
                              input=self.reader, capture_output=True, text=True,
                              encoding="utf-8", check=False)

    def test_plain_markdown_has_no_sidecar_even_with_later_delimiters(self) -> None:
        result = self.read("# Legacy note\n---\nsidecar: not-metadata.yaml\n---\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "\n")

    def test_leading_frontmatter_preserves_legacy_pair(self) -> None:
        result = self.read("\ufeff---\ntype: legacy-contract\nsidecar: legacy-send.yaml\n---\n# Note\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "legacy-send.yaml\n")

    def test_empty_frontmatter_has_no_sidecar(self) -> None:
        result = self.read("---\n---\n# Note\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "\n")

    def test_invalid_metadata_fails_before_any_deletion(self) -> None:
        for text in ("---\nsidecar: missing-close.yaml\n",
                     "---\nsidecar: [invalid yaml\n---\n",
                     "---\n- sidecar.yaml\n---\n",
                     "---\n[]\n---\n",
                     "---\nfalse\n---\n",
                     "---\nsidecar: 17\n---\n",
                     "---\nsidecar: |\n  first.yaml\n  second.yaml\n---\n"):
            with self.subTest(text=text):
                result = self.read(text)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("CONFLICT: cannot read REMOVED metadata", result.stderr)
                self.assertTrue(self.target.is_file())


if __name__ == "__main__":
    unittest.main()
