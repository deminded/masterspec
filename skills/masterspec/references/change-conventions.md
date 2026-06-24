# Соглашения про changes/

Как организована директория изменений фабрики. Документ читают workflow-скиллы `masterspec-propose`, `masterspec-design`, `masterspec-implement`, `masterspec-apply-change`, `masterspec-archive-change`.

---

## 1. Расположение

`masterspec/changes/` — внутри фабрики пользователя, рядом с артефактами слоёв.

```
masterspec/
├── 00-masterspec-index.md
├── 01-requirements/...
├── 02-specifications/...
├── 03-codemap/...
├── 04-decisions/...
└── changes/
    ├── <change-name>/            # активный change
    │   ├── change.md
    │   ├── new/                  # опц.
    │   ├── .research/            # опц.
    │   ├── design.md             # опц.
    │   └── tasks.md              # опц.
    └── archive/
        └── YYYY-MM-DD-<change-name>/
```

`<change-name>` — kebab-case, описывает суть изменения: `add-retry-logic`, `fix-ac-timeout`, `split-cmp-delivery-router`.

---

## 2. Содержимое активного change

### 2.1. `change.md` — обязательный

Шапка со статусом + 8 секций. Шаблон — `masterspec-propose/templates/change.md`. Формат детально — `masterspec-propose/references/change-format.md`.

Секции:
1. Мотивация (цель, инициатор, приоритет, слои)
2. Затронутые артефакты (таблицы MODIFIED / ADDED / REMOVED)
3. Обратная совместимость
4. MODIFIED — diff-блоки
5. ADDED — отсылка к `new/` + список
6. REMOVED — повтор §2.3 с обоснованием
7. Влияние на направление ссылок
8. Критерии приёмки изменения

### 2.2. `new/<slug>.md` — опционально

Появляется, когда change добавляет новые артефакты целиком (новый `fn-`, `cmp-`, `scn-`, `adr-` и т. д.). Имя файла = slug артефакта. YAML-фронтматтер обязателен, `status: draft`. Шаблон — соответствующий `masterspec/templates/tpl-*.md` по `type:`.

При `apply-change` файл копируется в целевую директорию фабрики по таблице из `references/artifact-routing.md`.

### 2.3. `.research/<role>.yaml` — опционально

Результаты работы `masterspec-explore` (structured research кодовой базы). Используются `propose` / `design` / `implement` для точной привязки изменений к коду. После `apply-change` и `archive-change` директория сохраняется внутри архива для аудита.

### 2.4. `design.md` + `tasks.md` — опционально

Создаются `masterspec-design` для сложных CR. Формат — как в `openspec-design` (dev-design, привязанный к реальным классам/модулям проекта). Для простых CR шаг пропускается.

---

## 3. Статусы change.md

Шапка `change.md` содержит поле `> **Статус**: ...`. Допустимые значения:

| Статус | Переход | Кто ставит |
|---|---|---|
| На согласовании | → Согласовано | `masterspec-propose` при создании |
| Согласовано | → В реализации | Аналитик вручную после merge PR |
| В реализации | → Реализовано | `masterspec-implement` при первом запуске |
| Реализовано | → Архивировано | `masterspec-apply-change` после успешного мержа |
| Архивировано | финал | `masterspec-archive-change` при перемещении в `archive/` |

Обратные переходы (возврат из «В реализации» в «Согласовано») — только вручную, скиллы не трогают.

При архивации из статуса ≠ `Реализовано` (warning-архивация для незавершённой работы) — change физически перемещается в `archive/`, но статус в шапке сохраняется как есть для аудита.

---

## 4. Гибридный формат change (diff vs new/)

Выбор — на стороне `masterspec-propose`. Правила — в `masterspec-propose/references/change-format.md`. Сводка:

| Тип правки | Формат |
|---|---|
| Правка одного bullet / AC / строки таблицы | diff-блок (§4 change.md) |
| Правка одного раздела `## ...` целиком, < 50 строк | diff-блок `replace-section` |
| Новый `cap-*` внутри существующего `cmp-` | diff-блок `add-subsection` |
| Замена раздела целиком, ≥ 50 строк | файл в `new/<slug>-<section>.patch.md` + пометка в change.md |
| Новый артефакт целиком (новый `fn-`, `cmp-`, `scn-`, `alg-`, `adr-`, ...) | файл в `new/<slug>.md` |
| Удаление артефакта целиком | только §2.3 и §6 change.md, файл не трогаем до apply |

---

## 5. Связь статусов с артефактами фабрики

| Статус change.md | Что означает для `masterspec/01-*/02-*/03-*/04-*` |
|---|---|
| На согласовании | Ничего не тронуто. Вся работа — в `masterspec/changes/<name>/`. |
| Согласовано | PR смержен. Артефакты фабрики не тронуты. Можно идти в `design`/`implement`. |
| В реализации | `implement` пишет код. Артефакты фабрики не тронуты. |
| Реализовано | `apply-change` выполнен. Diff-блоки применены, файлы из `new/` скопированы, `00-masterspec-index.md` обновлён. Новые артефакты — `status: draft`, переход в `actual` — вручную после ревью. |
| Архивировано | `changes/<name>/` перемещён в `changes/archive/YYYY-MM-DD-<name>/`. |

---

## 6. Откат

Единая команда при любой проблеме после `apply-change`:

```bash
git checkout HEAD -- masterspec/
```

Откатывает ВСЕ правки в `masterspec/01-*/02-*/03-*/04-*` и `00-masterspec-index.md`. Директория `masterspec/changes/<name>/` остаётся нетронутой — она под отдельным git'ом change'а.

Никаких `.bak`-файлов. Коммит до `apply-change` обязателен.

---

## 7. Архивация

`masterspec-archive-change` выполняет:

```bash
mkdir -p masterspec/changes/archive
mv masterspec/changes/<name> masterspec/changes/archive/YYYY-MM-DD-<name>
```

Где `YYYY-MM-DD` — сегодняшняя дата (UTC). Если директория с таким именем уже есть — добавляется суффикс `-2`, `-3`.

После архивации change больше не редактируется и не применяется. Для повторных изменений — новый change через `propose`.
