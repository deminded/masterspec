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
    # config — ИЗ ШАБЛОНА поставки, не упрощённый: приёмка обязана доказывать,
    # что поставляемый дескриптор принимается живым CLI (находка ревью Sol P3).
    tpl = (Path(__file__).parents[1].parent / "templates" /
           "tpl-openspec-config.md").read_text(encoding="utf-8")
    yaml_block = tpl.split("```yaml\n", 1)[1].split("```", 1)[0]
    (root / "openspec" / "config.yaml").write_text(yaml_block, encoding="utf-8")


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


class ResolveRootsScenarios(unittest.TestCase):
    """Исполняемые сценарии резолвинга (закрытие находки Sol №5): референс-реализация
    layout-modes §2 гоняется на четырёх раскладках, включая неоднозначную."""

    def setUp(self):
        import importlib.util
        import sys as _sys
        spec = importlib.util.spec_from_file_location(
            "chk_resolver", SCRIPTS / "check-layout.py")
        self.chk = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = self.chk  # без записи в sys.modules dataclass-модуль падает при exec
        spec.loader.exec_module(self.chk)
        self.tmp = Path(tempfile.mkdtemp(prefix="msres-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _index(self, rel, layout_line=None):
        d = self.tmp / rel
        d.mkdir(parents=True, exist_ok=True)
        body = "# Индекс\n\n## 1. Паспорт\n"
        if layout_line:
            body += layout_line + "\n"
        (d / "00-masterspec-index.md").write_text(body, encoding="utf-8")
        return d

    def test_classic_in_root(self):
        d = self._index(".")
        s, c, l = self.chk.resolve_roots(self.tmp)
        self.assertEqual((s, c, l), (d.resolve(), (d / "changes").resolve(), "classic"))

    def test_classic_subdir(self):
        d = self._index("masterspec")
        s, c, l = self.chk.resolve_roots(self.tmp)
        self.assertEqual((s, c, l), (d.resolve(), (d / "changes").resolve(), "classic"))

    def test_openspec_by_passport_and_by_path(self):
        d = self._index("openspec/specs", "- Раскладка (layout): openspec")
        s, c, l = self.chk.resolve_roots(self.tmp)
        self.assertEqual(l, "openspec")
        self.assertEqual(c, (d.parent / "changes").resolve(),
                         "changes-root обязан быть СОСЕДОМ specs, не подкаталогом")
        # и без строки паспорта — по пути
        (d / "00-masterspec-index.md").write_text("# Индекс\n", encoding="utf-8")
        _, c2, l2 = self.chk.resolve_roots(self.tmp)
        self.assertEqual((l2, c2), ("openspec", (d.parent / "changes").resolve()))

    def test_two_indexes_is_ambiguous_not_silent(self):
        self._index("masterspec")
        self._index("openspec/specs")
        with self.assertRaises(ValueError) as ctx:
            self.chk.resolve_roots(self.tmp)
        self.assertIn("спроси человека", str(ctx.exception),
                      "полупереехавшая фабрика должна давать вопрос, не молчаливый выбор")

    def test_archive_and_work_are_not_candidates(self):
        self._index("masterspec")
        self._index("masterspec/changes/archive/2026-01-01-old/snapshot")
        self._index("masterspec/.work/run-1/copy")
        s, _, _ = self.chk.resolve_roots(self.tmp)
        self.assertEqual(s, (self.tmp / "masterspec").resolve())


class MergeWorkflowNoHardcodedRoots(unittest.TestCase):
    """Страж регресса P1 (ревью Sol): обязательные команды merge-workflow не смеют
    хардкодить masterspec/ — в openspec-режиме такой rollback молча не откатывает."""

    def test_executable_fences_use_resolved_roots(self):
        ref = (Path(__file__).parents[1].parent / ".." / "masterspec-apply-change" /
               "references" / "merge-workflow.md").resolve().read_text(encoding="utf-8")
        bad = []
        fence_lang = None
        for i, line in enumerate(ref.splitlines(), 1):
            if line.strip().startswith("```"):
                fence_lang = None if fence_lang is not None else line.strip()[3:] or "plain"
                continue
            # исполняемое в этом файле живёт ТОЛЬКО в bash-фенсах; фенсы без языка —
            # примеры текстов сообщений, их classic-конкретика покрыта шапкой файла
            if fence_lang != "bash" or line.lstrip().startswith("#"):
                continue
            if "masterspec/" in line and "<specs-root>" not in line \
                    and "<changes-root>" not in line \
                    and "references/" not in line and "../masterspec/" not in line:
                bad.append(f"{i}: {line.strip()[:90]}")
        self.assertEqual(bad, [], "исполняемые строки с жёстким masterspec/: %s" % bad)
        # inline-исполняемое вне fence: `find masterspec/ — smoke-check §9.1 ловился
        # только этим (находка re-check Sol: страж по fence его пропустил)
        inline_bad = [f"{i}: {l.strip()[:80]}" for i, l in
                      enumerate(ref.splitlines(), 1)
                      if "`find masterspec/" in l and "<specs-root>" not in l]
        self.assertEqual(inline_bad, [], "inline-команды с жёстким masterspec/: %s" % inline_bad)


if __name__ == "__main__":
    unittest.main()
