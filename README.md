# masterspec-skills

Набор скиллов для описания фабрик (автоматизированных систем) по мета-модели masterspec. Поддерживает полный жизненный цикл: проектирование с нуля, восстановление из документов/кода, и workflow изменений уже описанной фабрики.

> Скиллы работают напрямую с файловой системой — внешних CLI/зависимостей не требуется.

## Скиллы

| Скилл | Назначение |
|---|---|
| `masterspec` | **Kernel.** Содержит мета-модель, 24 шаблона артефактов, и режимы работы над самой фабрикой: `design` (проектирование с нуля), `recover` (восстановление из документов), `codemap` (анализ репозитория), `audit` (проверка покрытия), `reverse` (reverse engineering из кода) |
| `masterspec-explore` | Structured research кодовой базы параллельными read-only субагентами по 5 ролям (requirements-scope, components-scope, scenarios-scope, data-scope, codemap-scope) |
| `masterspec-propose` | Создать `change.md` — предложение на изменение артефактов фабрики. Гибридный формат: diff-блоки для мелких правок, файлы в `new/` для крупных |
| `masterspec-design` | Создать `design.md` + `tasks.md` — план реализации change в КОДЕ (dev-design, не путать с kernel-режимом `design`) |
| `masterspec-implement` | Выполнить `tasks.md` change'а с обязательной верификацией (сборка/тесты/линтер) |
| `masterspec-apply-change` | Мультиартефактный мерж `change.md` (diff-блоки) + файлы из `new/` в артефакты фабрики, обновление `00-masterspec-index.md`. Откат — через git |
| `masterspec-archive-change` | Переместить завершённый change в `changes/archive/YYYY-MM-DD-<name>/` |

## Мета-модель: три слоя

| Слой | Директория | Что описывает |
|---|---|---|
| Требования | `01-requirements/` | ЧТО даёт система (функции, NFR, правила, концептуальные данные) |
| Спецификации | `02-specifications/` | КАК устроено взаимодействие (компоненты, сценарии, алгоритмы, API, данные) |
| Кодовая база | `03-codemap/` | ГДЕ в коде (`file:line`, таблицы) — генерируемый слой |

Плюс `04-decisions/` для ADR. Ссылки идут **снизу вверх** — требования не ссылаются на спецификации/код.

Полная мета-модель — `skills/masterspec/meta_model.md`. Операционная выжимка по запретам — `skills/masterspec/references/layer-discipline.md`.

## Жизненный цикл изменения

```
masterspec (design) ─┐
                      ▼
                   propose → (design?) → implement → apply-change → archive-change
                      ▲                                   │
                      └──────── explore (read-only) ──────┘
```

1. Нет ни одной фабрики в `masterspec/` → kernel `masterspec` в режиме `design`.
2. Нужно изменить артефакты уже описанной фабрики → `masterspec-propose` (создаёт `masterspec/changes/<name>/change.md` со статусом `На согласовании`).
3. Ревью PR → merge → статус вручную меняется на `Согласовано`.
4. Сложный CR (затрагивает код) → `masterspec-design` создаёт `design.md` + `tasks.md`. Простой CR пропускает этот шаг.
5. Реализация кода → `masterspec-implement` выполняет tasks.md с верификацией, ставит статус `В реализации`.
6. Вливание в артефакты фабрики → `masterspec-apply-change` мержит diff-блоки и файлы из `new/` в соответствующие директории, ставит статус `Реализовано`.
7. Архивация → `masterspec-archive-change` перемещает change в `masterspec/changes/archive/YYYY-MM-DD-<name>/`.

### Статусы change.md

| Статус | Кто ставит | Когда |
|---|---|---|
| На согласовании | `masterspec-propose` | Change создан, идёт ревью в PR |
| Согласовано | Аналитик вручную | PR с change.md вмержен, change одобрен |
| В реализации | `masterspec-implement` | Первый запуск implement, идёт кодинг по tasks.md |
| Реализовано | `masterspec-apply-change` | Изменения вмержены в артефакты фабрики |
| Архивировано | `masterspec-archive-change` | Change перемещён в `archive/` из статуса `Реализовано` |

## Структура фабрики в проекте пользователя

```
masterspec/
├── 00-masterspec-index.md
├── 00-glossary.md
├── 01-requirements/       # as-*, fn-*, nfr-*, rules-*, context-*, fd-*, cdm-*, dict-*, tc-acc-*
├── 02-specifications/     # cmp-* (с cap-*), scn-*, alg-*, api-*, data-*, cd-*, lp-*, tc-int-*
├── 03-codemap/            # repo-map, cmap-*, trace-*, dmap-*  (generated: true)
├── 04-decisions/          # adr-*
└── changes/
    ├── <change-name>/
    │   ├── change.md
    │   ├── new/           # опц.: крупные новые артефакты
    │   ├── .research/     # опц.: от masterspec-explore
    │   ├── design.md      # опц.
    │   └── tasks.md       # опц.
    └── archive/YYYY-MM-DD-<name>/
```

## Установка

### Claude Code

```bash
claude plugin install <путь до этой директории>
```

### Другие harness'ы

Скопируй директорию `skills/` в свой skill-registry. Путь к kernel-скиллу `masterspec` автоматически резолвится соседним скиллом через `<Skill dir>/../masterspec/<file>`.

## Разработка

### Структура поставки

```
skills/
├── masterspec/                   # kernel: meta_model.md + 24 шаблона + 5 режимов
├── masterspec-explore/           # 5 references (invocation-contract, research-orchestration, research-roles, code-analysis-priority, masterspec-awareness)
├── masterspec-propose/           # SKILL.md + templates/change.md + 4 references
├── masterspec-design/            # SKILL.md + templates/{design,tasks}.md
├── masterspec-implement/         # SKILL.md + 3 references (runbook, verification, edge-cases)
├── masterspec-apply-change/      # SKILL.md + references/merge-workflow.md
└── masterspec-archive-change/    # SKILL.md
```

### Где живёт мета-модель

В ОДНОМ месте: `skills/masterspec/meta_model.md` + `skills/masterspec/references/*`. Все workflow-скиллы читают её по относительному пути `<Skill dir>/../masterspec/<file>`. Правишь один файл — меняется поведение всех.

### Мелкие правки vs крупные (change.md)

- Мелкая правка (одна строка, AC, bullet, NFR-значение) → **diff-блок** в `change.md §4` с указанием типа (`modify-bullet` / `replace-section` / `add-subsection`).
- Крупная правка (новый артефакт целиком: новый `fn-`, `cmp-`, `scn-`, `adr-`) → **файл** в `changes/<name>/new/<slug>.md`.

Правила выбора — `skills/masterspec-propose/references/change-format.md`.

## Roadmap

- [ ] Git WorkTree для параллельной работы над несколькими changes
- [ ] MCP-интеграция для генерации PlantUML / Mermaid / drawio диаграмм из артефактов
- [ ] CI-проверка дисциплины слоёв (блок на merge, если в `fn-` появились имена компонентов)
- [ ] Автогенерация `masterspec-awareness` подсказок для конкретных стеков
