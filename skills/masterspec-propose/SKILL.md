---
name: masterspec-propose
description: >
  Создать change.md — предложение на изменение артефактов фабрики по мета-модели
  masterspec. Ведёт двухэтапное интервью (ЧТО → КАК), при затрагивании кода запускает
  параллельных read-only субагентов `masterspec-explore` с target=factory-change.
  Гибридный формат: мелкие правки — diff-блоки в change.md; крупные (новый fn/cmp/scn/adr)
  — файлы в `changes/<name>/new/<slug>.md`. Используй когда пользователь формулирует новую
  функцию, правку существующего AC/NFR/компонента/сценария, новый ADR, правку codemap —
  до написания кода. НЕ используй для описания фабрики с нуля (для этого kernel `masterspec`
  в режиме `design`).
when_to_use: >
  добавить/поменять/убрать в фабрике, изменить спецификацию, обновить фабрику,
  внести изменение, создать change, propose, предложение на изменение, change-request
argument-hint: "[kebab-name ИЛИ описание того, что нужно изменить]"
license: MIT
compatibility: >
  Требуется masterspec/ layout в проекте, доступ к bash/git, AskUserQuestion tool,
  встроенный tool запуска read-only субагента (имя и subagent_type — по таблице § 3.1
  masterspec-explore/references/invocation-contract.md). Опционально Serena/LSP/embedding MCP.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
---

# masterspec-propose — создание change.md

Создать предложение на изменение артефактов фабрики — единый `change.md` (мотивация + таблицы MODIFIED/ADDED/REMOVED + diff-блоки) + опционально файлы в `new/`. После ревью PR и реализации запусти `masterspec-apply-change` для вливания в артефакты фабрики.

**Input**: Имя change (kebab-case) ИЛИ описание того, что нужно изменить.

---

## Bundle-пути

- Собственные `templates/X` и `references/X` — относительно директории этого скилла.
- Внешние файлы kernel `masterspec` — сосед по директории, резолв через `<Skill dir>/../masterspec/<file>`.
- Внешние файлы `masterspec-explore` — сосед по директории, резолв через `<Skill dir>/../masterspec-explore/references/<file>`.
- Если harness даёт `Skill directory: <abs>` в обёртке активации — используй. Например:
  - `Read("<Skill dir>/templates/change.md")` — шаблон change.md
  - `Read("<Skill dir>/references/interview-playbook.md")` — сценарий интервью
  - `Read("<Skill dir>/../masterspec/meta_model.md")` — мета-модель
  - `Read("<Skill dir>/../masterspec/references/layer-discipline.md")` — проверка diff'ов
  - `Read("<Skill dir>/../masterspec/references/artifact-routing.md")` — тип→путь для `new/`
  - `Read("<Skill dir>/../masterspec/templates/tpl-function-as.md")` — шаблон при создании нового `fn-` в `new/`
- Fallback — `Glob("**/masterspec-skills/skills/masterspec-propose/<file>")` и `Glob("**/masterspec-skills/skills/masterspec/<file>")`. Пусто → спроси пользователя путь установки.

## Bundled materials

- `templates/change.md` — шаблон изменения (шапка + §1..§8)
- `references/interview-playbook.md` — сценарий двух этапов интервью
- `references/guardrails.md` — запреты, уровни обязательности, чек-лист ревью
- `references/change-format.md` — когда diff-блок, когда файл в `new/`, форматы
- `references/example-change.md` — пример заполненного change.md

## Внешние references (kernel `masterspec`)

- `masterspec/meta_model.md` — мета-модель (три слоя, запреты, направление ссылок)
- `masterspec/references/layer-discipline.md` — операционная проверка каждого diff-блока
- `masterspec/references/artifact-routing.md` — таблица тип→шаблон→путь→slug (для `new/`)
- `masterspec/references/change-conventions.md` — соглашения про changes/
- `masterspec/templates/tpl-*.md` — шаблоны для файлов в `new/<slug>.md`

## Внешние references (скил `masterspec-explore`)

- `masterspec-explore/references/invocation-contract.md` — контракт запуска read-only субагентов
- `masterspec-explore/references/research-roles.md` — промпты ролей для `target=factory-change`
- `masterspec-explore/references/research-orchestration.md` § 3.2 — группировка ролей по размеру

**Scope исследования кода.** Лид **не читает исходный код напрямую**. Если change затрагивает кодовый слой — оркестрирует субагентов по контракту из `invocation-contract.md`. Чисто текстовая правка требований (например, AC) — research пропускается.

**AskUserQuestion fallback**: если инструмент недоступен — задай тот же вопрос обычным текстом и дождись ответа.

---

## Шаги

### 1. Этап 1 интервью — ЧТО и ЗАЧЕМ

Открытый вопрос → 2–3 уточнения порциями (цель / инициатор / слои / приоритет / backward-compat). Детали — `references/interview-playbook.md` (этап 1).

Выведи kebab-case имя change. Получи подтверждение.

### 2. Проверь фабрику

**2.1.** Прочитай `masterspec/00-masterspec-index.md`.

Если файла нет — AskUserQuestion: «Фабрика `<factory-slug>` ещё не описана. Запустить kernel `masterspec` в режиме `design`?» (опции: «да, переключить на design» / «фабрика существует, но без индекса — продолжить без него»).

**2.2.** По упоминаниям пользователя из этапа 1 — прочитай конкретные артефакты фабрики, которые вероятно затрагиваются (`fn-*.md`, `cmp-*.md`, `scn-*.md`).

### 3. Опциональный research кода

Запускается только если change затрагивает код (слои 2 или 3). Для чисто текстовой правки требований — пропустить.

**3.1.** Прочитай канонический контракт — `masterspec-explore/references/invocation-contract.md` целиком.

**3.2.** Собери параметры:
- `target=factory-change`
- `name=<kebab-case>` (из этапа 1)
- `anchor` — пути/символы/slug'и в скоупе (из описания задачи или из §2.2)
- `thoroughness=quick` (default)

**3.3.** Создай каталог:

```bash
mkdir -p masterspec/changes/<name>/.research
```

**3.4.** Классифицируй размер и группу по `masterspec-explore/references/research-orchestration.md § 2` и § 3.2.

**3.5.** Прочитай промпты ролей из `research-roles.md` — `requirements-scope`, `components-scope`, `scenarios-scope`, `data-scope` (для change — с сужением по anchor_paths). Копируй **дословно**, подставь реальные пути.

**3.6.** Запусти субагентов параллельно — один ответ, один блок tool-use, несколько вызовов. Имя tool-а и `subagent_type` — по алгоритму `invocation-contract.md § 3.1`.

**3.7.** Сохрани результаты в `.research/<role>.yaml`, валидируй YAML (`§ 6`), агрегируй (`§ 7`), запиши `_aggregate.yaml` + `.research-notes.md` (`§ 8.4`).

Не выходи со скилла, пока 3.6 → 3.7 не выполнены целиком.

### 4. Этап 2 интервью — КАК меняем

С `.research-notes.md` на руках (если был research) — детализируй изменения. Составь черновик §2 change.md (MODIFIED / ADDED / REMOVED), получи подтверждение. Для каждой строки — задай конкретные вопросы: что ДО / ПОСЛЕ, какой раздел, какой тип правки.

Валидируй на лету по `masterspec/references/layer-discipline.md`: не появляются ли имена компонентов в требованиях, код в спецификациях.

Для каждого нового артефакта (§2.2 ADDED): прочитай `masterspec/templates/tpl-<type>.md`, проведи интервью по шаблону.

Категории вопросов и правила перехода — `references/interview-playbook.md` (этап 2).

### 5. Проверь change-директорию

Каталог `masterspec/changes/<name>/` уже создан на шаге 3.3 (если был research) или создай сейчас:

```bash
mkdir -p masterspec/changes/<name>
```

Если `change.md` в нём уже есть (повторный запуск) — AskUserQuestion: продолжить редактирование или создать новый под другим именем.

### 6. Прочитай шаблон

Открой `templates/change.md` — это даст структуру шапки и всех 8 секций с инструктивными HTML-комментариями.

### 7. Создай `change.md`

Запиши в `masterspec/changes/<name>/change.md`. Шапка: статус `На согласовании`, дата, автор, фабрика.

Заполни секции (формат детально — `references/change-format.md`):
- §1 — мотивация (цель, инициатор, приоритет, слои, контекст)
- §2 — три таблицы (MODIFIED / ADDED / REMOVED). Пустая таблица — не выкидываем, пишем `Нет изменений.` в соответствующей секции ниже
- §3 — backward compat (да/нет + план миграции если нет)
- §4 — diff-блоки (по одному на каждую строку §2.1)
- §5 — список файлов `new/` (дубль §2.2 для удобства)
- §6 — обоснование для каждой REMOVED
- §7 — влияние на ссылки (проверка на отсутствие обратных)
- §8 — критерии приёмки change

Удали ВСЕ HTML-комментарии из шаблона.

### 8. Создай файлы в `new/`

Для каждой строки §2.2:
1. **Проверь уникальность slug'а.** Выполни `Glob("masterspec/**/<slug>.md")` с исключением `masterspec/changes/`. Если совпадение найдено — это коллизия: либо предлагаемый slug дублирует существующий артефакт, либо уже был создан в предыдущем change. Блок: AskUserQuestion — выбрать новый slug или отменить добавление. Не продолжай создание `new/<slug>.md` до разрешения.
2. По полю `type:` определи шаблон (`masterspec/references/artifact-routing.md`).
3. Прочитай `masterspec/templates/tpl-<type>.md`.
4. Скопируй в `masterspec/changes/<name>/new/<slug>.md`.
5. Заполни фронтматтер (`type`, `slug`, `factory`, `status: draft`, `updated` = сегодня).
6. Заполни содержимое через интервью (шаг 4.4).
7. Удали HTML-комментарии.

Проверь дисциплину слоёв для каждого файла.

### 9. Ревью

Проведи ревью по чек-листу `references/guardrails.md § 4`. Если доступен tool запуска субагента — запусти отдельный ревьюер (см. `guardrails.md § 5`).

Blocking-issues исправь до сдачи. Soft-issues зафиксируй в «Открытые вопросы» change.md.

### 10. Финализация

Сообщи пользователю:
- Имя change и путь: `masterspec/changes/<name>/change.md`
- Какие секции заполнены, какие `Нет изменений.`
- Список файлов в `new/`
- Результат ревью
- Подсказка: «Change создан со статусом `На согласовании`. Отправь на ревью (PR). После merge PR — поставь статус `Согласовано` вручную. Далее:
  - **Сложный CR** (затрагивает код, несколько компонентов): `masterspec-design` → `masterspec-implement` → `masterspec-apply-change`.
  - **Простой CR** (правка одного AC, текстовая правка): можно пропустить `masterspec-design` и сразу `masterspec-apply-change` после merge PR».

---

## Output

- Имя change и путь к файлу
- Перечень заполненных секций
- Список файлов `new/` (если есть)
- Результат ревью (blocking / soft / clean)
- Целевая фабрика и затронутые слои
- Подсказка про next step

---

## Guardrails

- `change.md` — документ системного аналитика: **ЧТО** и **ЗАЧЕМ**, не **КАК в коде**. Код приложения, unit-тесты поимённо, конфиги целиком — запрещены. Разрешены: описание поведения (ЕСЛИ/ТОГДА/ИНАЧЕ), таблицы полей/параметров в логических терминах, контракты API (логические), формулировки КОГДА/ТОГДА для AC, JSON-schema/Protobuf/Avro как артефакты при необходимости. Полный список — `references/guardrails.md`.
- **Статусы change.md** (описание — `masterspec/references/change-conventions.md`):
  - `На согласовании` — создан этим скиллом, отправлен на ревью.
  - `Согласовано` — PR с change.md замержен; можно идти в design/implement.
  - `В реализации` — начата реализация (design/implement).
  - `Реализовано` — изменения вмержены в артефакты фабрики (`apply-change`).
  - `Архивировано` — change перемещён в archive (`archive-change`).
- **Гибридный формат**: diff-блоки для мелких правок, `new/<slug>.md` для крупных (полные правила — `references/change-format.md`).
- **Маппинг скиллов**: `masterspec-propose` → (`masterspec-design` опционально) → `masterspec-implement` → `masterspec-apply-change` → `masterspec-archive-change`.
- Не создавай change.md, пока остаются неясности. Всегда прочитай целевые артефакты ПЕРЕД созданием. Не копируй примеры из references в итоговый файл. Проверь, что все 8 секций на месте.
