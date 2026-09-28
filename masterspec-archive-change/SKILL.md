---
name: masterspec-archive-change
description: >
  Заархивировать завершённый change — перенести директорию masterspec/changes/<name>/ в
  masterspec/changes/archive/YYYY-MM-DD-<name>/ (или openspec/changes/ в openspec-режиме).
  Используй после применения change
  (статус `Реализовано`), либо когда пользователь говорит "архивируй change",
  "закрой change", "убери из активных", "archive".
when_to_use: >
  архивировать change, закрыть change, убрать из активных, archive change
argument-hint: "[имя change]"
license: MIT
compatibility: Использует masterspec/ layout, bash, AskUserQuestion (при отсутствии — текстовый fallback, см. README).
allowed-tools:
  - Read
  - Edit
  - Glob
  - Bash
---

# masterspec-archive-change — архивирование завершённого change

Архивировать завершённый change.

**Input**: Опционально — имя change. Если не указано — выбор из активных через AskUserQuestion.

Определи корни фабрики по `../masterspec/references/layout-modes.md §2` (положение `00-masterspec-index.md` → specs-root, changes-root).

**AskUserQuestion fallback**: если инструмент недоступен — задай вопрос обычным текстом и дождись ответа.

---

## Шаги

### 1. Если имя не указано — выбор

Найди активные changes:
```bash
# <changes-root> — из резолвинга layout-modes.md §2 (например masterspec/changes/ в classic-подпапке или openspec/changes/ в openspec-режиме)
ls <changes-root>/ 2>/dev/null
```
Исключи `archive/` из списка. Используй AskUserQuestion для выбора.

**ВАЖНО**: НЕ угадывай и НЕ выбирай автоматически. Пусть пользователь выберет.

### 2. Проверь наличие change.md

Проверь, что `<changes-root>/<name>/change.md` существует.

Если не существует — покажи предупреждение, спроси подтверждение через AskUserQuestion, продолжи при подтверждении.

### 3. Проверь статус change.md

Прочитай `<changes-root>/<name>/change.md` и проверь поле `> **Статус**:` в шапке:

| Статус | Действие |
|--------|----------|
| `Реализовано` | Готов к архивации. На шаге 4 поменяй статус на `Архивировано` ДО `mv`. |
| `Применено, не сертифицировано` | **СТОП, не архивируй.** Правки внесены, полного сертификата нет. Покажи из apply-report.md отдельно BLOCKER и непроверенные scope (`not-assessed`); отсутствие отчёта отметь как недостающие доказательства. Предложи закрыть остаток и пересертифицировать (`apply-change` §13, режим без change). |
| `Архивировано` | Change уже помечен архивированным. Если директория всё ещё в `<changes-root>/<name>/` (не в `archive/`) — предложи через AskUserQuestion переместить без правки статуса. Иначе выйди с сообщением «уже в архиве». |
| `На согласовании` / `Согласовано` / `В реализации` / отсутствует | Предупреди о незавершённом состоянии, спроси подтверждение через AskUserQuestion. При подтверждении — архивируй, но **статус НЕ трогай** (сохрани фактический для аудита незавершённой работы). |

### 4. Выполни архивацию

**a. Обнови статус (условно)**

Если на шаге 3 статус был `Реализовано` — замени в `<changes-root>/<name>/change.md` строку `> **Статус**: Реализовано` на `> **Статус**: Архивировано`.

Если статус был другой (архивируем с предупреждением) — **не** меняй статус. Это сохраняет сигнал о незавершённой работе.

Меняй ТОЛЬКО строку `> **Статус**:`, ничего больше.

**b. Перемести директорию**

```bash
mkdir -p <changes-root>/archive
```

Имя архива: `YYYY-MM-DD-<change-name>` (YYYY-MM-DD — сегодняшняя дата).

Проверь, что целевая директория не существует:
- Если существует — добавь суффикс `-2`, `-3`, ... (или предложи пользователю через AskUserQuestion).
- Если нет — перемести:

```bash
mv <changes-root>/<name> <changes-root>/archive/YYYY-MM-DD-<name>
```

Openspec-режим: перенос в `<changes-root>/archive/YYYY-MM-DD-<name>/` безопасен — openspec игнорирует `archive/` (проверено CLI 1.8.0).

### 5. Покажи результат

---

## Output On Success

```
## Archive Complete

**Change:** <change-name>
**Archived to:** <changes-root>/archive/YYYY-MM-DD-<name>/

Все артефакты завершены. Change архивирован.
```

## Output With Warnings

```
## Archive Complete (с предупреждениями)

**Change:** <change-name>
**Archived to:** <changes-root>/archive/YYYY-MM-DD-<name>/

**Предупреждения:**
- change.md не в статусе `Реализовано` (статус сохранён как есть для аудита, `Архивировано` НЕ поставлен).
- <N> невыполненных задач (если есть tasks.md).

Проверь архив, если это не было намеренным.
```

---

## Guardrails

- Всегда предлагай выбор change, если имя не указано.
- Проверяй статус по содержимому change.md, а не через CLI.
- НЕ блокируй архивацию при предупреждениях — информируй и подтверждай через AskUserQuestion.
- Вся директория change перемещается целиком (включая `.research/`, `new/`, `design.md`, `tasks.md` — всё для аудита).
- **НЕ трогай артефакты фабрики** (`<specs-root>/01-*/02-*/03-*/04-*`, например `masterspec/01-*/…` или `openspec/specs/01-*/…`) — они уже вмержены через `masterspec-apply-change`.
- Покажи понятный итог.
