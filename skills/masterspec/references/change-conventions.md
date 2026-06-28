# Соглашения про changes/

Как организована директория изменений фабрики. Документ читают workflow-скиллы `masterspec-evolve` (создаёт change, шаг 0), `masterspec-impl-plan`, `masterspec-implement`, `masterspec-apply-change`, `masterspec-archive-change`.

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

Шапка со статусом + 8 секций. Шаблон — `../templates/tpl-change.md`. Формат детально — `change-format.md` (рядом).

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

Появляется, когда change добавляет новые артефакты целиком (новый `fn-`, `cmp-`, `scn-`, `adr-` и т. д.). Имя файла = slug артефакта. YAML-фронтматтер обязателен. Статус по типу (`meta_model.md §6.1.2`): артефакты слоёв — `status: draft`; `adr-` — `proposed`; `dr-` — `accepted`. Шаблон — соответствующий `masterspec/templates/tpl-*.md` по `type:`.

При `apply-change` файл копируется в целевую директорию фабрики по таблице из `references/artifact-routing.md`.

### 2.3. `.research/<role>.yaml` — опционально

Результаты работы `masterspec-explore` (structured research кодовой базы). Используются `evolve` / `impl-plan` / `implement` для точной привязки изменений к коду. После `apply-change` и `archive-change` директория сохраняется внутри архива для аудита.

### 2.4. `design.md` + `tasks.md` — опционально

Создаются `masterspec-impl-plan` для сложных CR. Формат — dev-design, привязанный к реальным классам/модулям проекта. Для простых CR шаг пропускается.

---

## 3. Статусы change.md

Шапка `change.md` содержит поле `> **Статус**: ...`. Допустимые значения:

| Статус | Кто ставит | Когда |
|---|---|---|
| На согласовании | `masterspec-evolve` | при создании change (шаг 0) |
| Согласовано | аналитик (вручную) | после merge PR |
| В реализации | `masterspec-implement` | при первом запуске кодинга |
| Реализовано | `masterspec-apply-change` | после успешного влития change в фабрику |
| Архивировано | `masterspec-archive-change` | при перемещении в `archive/` |

Обратные переходы (возврат из «В реализации» в «Согласовано») — только вручную, скиллы не трогают.

При архивации из статуса ≠ `Реализовано` (warning-архивация для незавершённой работы) — change физически перемещается в `archive/`, но статус в шапке сохраняется как есть для аудита.

---

## 4. Гибридный формат change (diff vs new/)

Выбор делается при создании change (`masterspec-evolve`, шаг 0). Правила — в `change-format.md` (рядом). Сводка:

| Тип правки | Формат |
|---|---|
| Правка одного bullet / AC / строки таблицы | diff-блок (§4 change.md) |
| Правка раздела `## ...` целиком | diff-блок `replace-section` |
| Новый `cap-*` внутри существующего `cmp-` | diff-блок `add-subsection` |
| Новый артефакт целиком (новый `fn-`, `cmp-`, `scn-`, `alg-`, `adr-`, `dr-`, ...) | файл в `new/<slug>.md` |
| Удаление артефакта целиком | только §2.3 и §6 change.md, файл не трогаем до apply-change |

---

## 5. Связь статусов с артефактами фабрики

Таблица описывает поток ИЗМЕНЕНИЯ (`evolve` → `apply-change`). В потоке генерации с нуля (`derive`) артефакты пишутся прямо в дерево и получают `actual` сменой статуса человеком при merge — без change.md и без apply-change. Этап «В реализации» нужен, ТОЛЬКО если change требует правки кода; если меняется лишь спека — после `Согласовано` идёт сразу `apply-change`.

| Статус change.md | Что означает для `masterspec/01-*/02-*/03-*/04-*` |
|---|---|
| На согласовании | Ничего не тронуто. Вся работа — в `masterspec/changes/<name>/`. |
| Согласовано | PR смержен. Артефакты фабрики не тронуты. Если нужен код — `impl-plan`/`implement`; если меняется только спека — сразу `apply-change`. |
| В реализации | (опционально, только если нужен код) `implement` пишет код. Артефакты фабрики не тронуты. |
| Реализовано | `apply-change` выполнен. Diff-блоки применены, файлы из `new/` скопированы, `00-masterspec-index.md` перегенерирован. Артефакты слоёв получают `status: actual` (merge PR уже был согласованием); `adr-`/`dr-` сохраняют свой решенческий статус. |
| Архивировано | `changes/<name>/` перемещён в `changes/archive/YYYY-MM-DD-<name>/`. |

---

## 6. Откат

Единая команда при любой проблеме после `apply-change`:

```bash
git checkout HEAD -- masterspec/ ':(exclude)masterspec/changes/'
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

После архивации change больше не редактируется и не применяется. Для повторных изменений — новый change через `evolve`.
