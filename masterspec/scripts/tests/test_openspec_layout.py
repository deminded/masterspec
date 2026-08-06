"""Приёмка режима layout=openspec (references/layout-modes.md §6).

ЗАЧЕМ. Режим обещает: дерево masterspec под openspec/specs/ не ломает openspec CLI,
change с мостами (proposal.md + .openspec.yaml) проходит validate, archive/ игнорируется.
Обещание держится не текстом скилла, а поведением ЧУЖОГО инструмента — поэтому тест
зовёт живой `openspec` CLI, и при его отсутствии честно скипается (не проверено ≠ зелено).

Негативная половина: change БЕЗ .openspec.yaml обязан падать в validate. Если и без
моста зелено — мост декоративен, и тест обязан сказать об этом красным.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
OPENSPEC = shutil.which("openspec")


def _factory(root: Path) -> None:
    """Мини-фабрика в openspec-раскладке: индекс + fn + change с мостами + архив."""
    specs = root / "openspec" / "specs"
    (specs / "01-requirements" / "02-functions").mkdir(parents=True)
    (specs / "00-masterspec-index.md").write_text(
        "# Индекс\n\n## 1. Паспорт\n- **Раскладка (layout)**: openspec\n",
        encoding="utf-8")
    (specs / "01-requirements" / "02-functions" / "fn-send.md").write_text(
        "---\ntype: fn\nslug: fn-send\n---\n# Функция отправки\n", encoding="utf-8")
    ch = root / "openspec" / "changes" / "nostory-20260806-probe"
    ch.mkdir(parents=True)
    (ch / "change.md").write_text("# Change: probe\n\n> **Статус**: На согласовании\n",
                                  encoding="utf-8")
    (ch / "proposal.md").write_text(
        "> Источник истины — change.md; этот файл — мост для OpenSpec.\n\n"
        "## Why\nПроба режима.\n\n## What Changes\n- см. change.md\n\n## Impact\n- нет\n",
        encoding="utf-8")
    (ch / ".openspec.yaml").write_text("schema: spec-driven\nskip_specs: true\n",
                                       encoding="utf-8")
    (ch / "tasks.md").write_text("## 1. Проба\n\n- [ ] 1.1 шаг\n", encoding="utf-8")
    arch = root / "openspec" / "changes" / "archive" / "2026-08-06-old"
    arch.mkdir(parents=True)
    (arch / "change.md").write_text("# старый\n", encoding="utf-8")
    (root / "openspec" / "config.yaml").write_text("schema: spec-driven\n",
                                                   encoding="utf-8")


def _run_openspec(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DO_NOT_TRACK="1")
    return subprocess.run([OPENSPEC, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


class OpenspecLayoutAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="msos-"))
        _factory(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_layout_accepts_openspec_specs_root(self):
        """Раскладка внутри specs-root канонична и проверяема штатным контролем."""
        r = subprocess.run(
            ["python3", str(SCRIPTS / "check-layout.py"),
             str(self.tmp / "openspec" / "specs"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("misplaced: 0", r.stdout)

    @unittest.skipUnless(OPENSPEC, "не проверено: openspec CLI недоступен")
    def test_masterspec_tree_does_not_break_validate(self):
        """Дерево masterspec под specs/ и мосты в change дают зелёный validate --all."""
        r = _run_openspec(self.tmp, "validate", "--all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 failed", r.stdout)

    @unittest.skipUnless(OPENSPEC, "не проверено: openspec CLI недоступен")
    def test_change_visible_with_task_progress(self):
        """Change фабрики виден openspec list, прогресс задач читается из tasks.md."""
        r = _run_openspec(self.tmp, "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nostory-20260806-probe", r.stdout)
        self.assertIn("0/1", r.stdout)
        self.assertNotIn("2026-08-06-old", r.stdout, "archive/ не должен сканироваться")

    @unittest.skipUnless(OPENSPEC, "не проверено: openspec CLI недоступен")
    def test_bridge_is_required_not_decorative(self):
        """ПОДСАДКА: снятый .openspec.yaml обязан дать красный validate."""
        (self.tmp / "openspec" / "changes" / "nostory-20260806-probe" /
         ".openspec.yaml").unlink()
        r = _run_openspec(self.tmp, "validate", "--all")
        self.assertNotEqual(r.returncode, 0,
                            "validate зелёный без моста — мост декоративен: " + r.stdout)


if __name__ == "__main__":
    unittest.main()
