---
name: masterspec-impl-plan
description: >
  Создать технический проект реализации (design.md) и план задач (tasks.md) на основе
  согласованного change.md фабрики — точечное изучение кода плюс генерация design и tasks
  по шаблонам. ВАЖНО: этот скилл — про **план разработки кода** для change-request'а
  Если нужно проектировать фабрику с нуля — запусти
  скилл `derive layer=spec`. Используй этот скилл когда change
  согласован (статус `Согласовано`) и пользователь готовится к реализации, говорит
  "design", "спроектируй реализацию change", "подготовь tasks", "разбей на задачи",
  "план разработки по change".
when_to_use: >
  спроектировать реализацию change, подготовить план задач, design.md, tasks.md,
  техпроект для change, разбить change на задачи, план разработки change
argument-hint: "[имя change]"
license: MIT
compatibility: >
  Требуется masterspec/ layout в проекте с готовым change.md, доступ к bash/git,
  AskUserQuestion tool. Опционально Serena/LSP/embedding MCP-серверы для анализа кода.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
---

# masterspec-impl-plan — техпроект реализации change

> **Этот скилл создаёт план разработки кода для change-request'а** — технический проект (design.md) и план задач (tasks.md), привязанные к реальным классам/модулям проекта.
> Если нужно проектировать фабрику с нуля — запусти скилл `derive layer=spec` (там другая семантика слова «design» — проектирование артефактов мета-модели).

Создаёт `design.md` (технический проект) и `tasks.md` (план задач на реализацию) в директории active change. Опирается на `change.md` + содержимое `new/` + опционально `.research-notes.md` от `masterspec-explore`.

**Input**: Опционально — имя change. Если не указано — автовыбор через `ls masterspec/changes/`.

## Bundle-пути

- Собственные `templates/X` — относительно директории этого скилла.
- Внешние файлы `masterspec-explore` — сосед по директории, резолв через `<Skill dir>/../masterspec-explore/references/<file>`.
- Если harness даёт `Skill directory: <abs>` — используй. Например:
  - `Read("<Skill dir>/templates/design.md")`
  - `Read("<Skill dir>/templates/tasks.md")`
  - `Read("<Skill dir>/../masterspec-explore/references/code-analysis-priority.md")`
- Fallback — `Glob("**/masterspec-impl-plan/templates/<file>")` и `Glob("**/masterspec-explore/references/<file>")`. Пусто → спроси пользователя.

## Bundled materials

- `templates/design.md` — шаблон технического проекта.
- `templates/tasks.md` — шаблон плана задач.

## Внешние references (скил `masterspec-explore`)

- `masterspec-explore/references/code-analysis-priority.md` — приоритет инструментов анализа кода.

**AskUserQuestion fallback**: если инструмент недоступен — задай тот же вопрос текстом, дождись ответа.

---

## Шаги

### 1. Выбрать change

Если имя указано — использовать. Иначе:
```bash
ls masterspec/changes/ 2>/dev/null | grep -v "^archive$"
```
- Автовыбор, если только один активный change (исключая `archive/`).
- Если несколько — предложить выбор через AskUserQuestion.

Объявить: «Проектирую change: `<name>`».

### 2. Проверь наличие change.md

Прочитай `masterspec/changes/<name>/change.md`.

- **Если файла нет**: change ещё не заведён — предложи сначала запустить `masterspec-evolve` (заводит change на шаге 0).
- **Если `design.md` уже существует**: AskUserQuestion — продолжить редактирование или создать заново.

### 3. Прочитай change.md целиком

Изучи все 8 секций:
- §1 Мотивация
- §2 Затронутые артефакты (таблицы MODIFIED / ADDED / REMOVED)
- §3 Обратная совместимость
- §4 Diff-блоки (MODIFIED)
- §5 Список ADDED
- §6 REMOVED с обоснованием
- §7 Влияние на ссылки
- §8 Критерии приёмки изменения

Прочитай также все файлы в `masterspec/changes/<name>/new/*.md` — они описывают новые артефакты, которые появятся после apply-change.

### 4. Изучи контекст

a. **Проверь наличие `.research-notes.md`** в `masterspec/changes/<name>/`. Если есть и актуален (создан недавно в `masterspec-evolve`/`masterspec-explore`) — используй агрегат как источник информации о текущей реализации. Экономит время — исследование уже проведено.

b. **Прочитай целевые артефакты фабрики** из §2.1 MODIFIED change.md — каждый `masterspec/01-*/02-*/03-*/04-*/<slug>.md`. Они описывают логику ДО изменения.

c. **Прочитай build-файлы / манифесты зависимостей** проекта для понимания стека: `pom.xml`, `build.gradle`, `go.mod`, `package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`.

d. **Для design-решений делай точечные reads** — не более 3–5 файлов за раз, только непосредственно затронутые узлы (классы/модули, явно упомянутые в change.md + их ближайшие вызывающие). Запрещено массовое сканирование — этим занимается `masterspec-explore`. Если нужно шире — прерви шаг и запусти `masterspec-explore` отдельно с `target=factory-change`.

e. **Анализ кода** — приоритет: Serena (MCP) → LSP → embeddings → прочие MCP → Grep/Glob. Подробнее — `masterspec-explore/references/code-analysis-priority.md`.

Если `.research-notes.md` отсутствует и change нетривиален — предложи пользователю прогнать `masterspec-explore` для полного research, либо продолжи в ручном режиме с явной пометкой риска неполноты.

### 5. Директория

Каталог `masterspec/changes/<name>/` уже существует. Просто проверь:

```bash
test -d masterspec/changes/<name>
```

### 6. Прочитай шаблоны

`templates/design.md` и `templates/tasks.md` — структура, описания, примеры.

### 7. Создай design.md

Заполни разделы шаблона `templates/design.md` реальными данными из `change.md` + `new/*.md` + изученного кода.

**Ссылайся на конкретные сущности кода проекта** (классы, модули, пакеты, функции — в терминах стека). Не проектируй вслепую.

**Уровни обязательности:**
- ДОЛЖЕН / ОБЯЗАН — обязательно для реализации
- СЛЕДУЕТ — рекомендуется
- МОЖЕТ — опционально

**Контракт живой эксплуатации:** для каждой затронутой external-I/O функции выполни set-diff её
`APPLICABLE OE-*` против таблиц единственных владельцев `scn-`. В `design.md` не копируй строки:
оставь ссылки на затронутые `scn-` и будущие `trace-`; code/evidence-маппинг принадлежит `trace-`,
а не плану. Пустое воплощение не превращай в общую задачу «учесть требования» —
это blocker техпроекта.

Удали все HTML-комментарии из шаблона. Запиши в `masterspec/changes/<name>/design.md`.

### 8. Создай tasks.md

На основе design.md и критериев приёмки из change.md §8:

- Группируй задачи логически (подготовка → core → тестирование → финализация → apply-change)
- Каждая задача — чекбокс: `- [ ] X.Y Описание`
- Порядок — по зависимостям
- Задачи должны быть достаточно маленькими для выполнения за одну сессию
- Обязательно включи задачи верификации (запуск сборки/тестов/линтера)
- По ссылкам на `scn-` включи конкретные задачи реализации и обновление единственного `trace-`;
  не размножай OE-строки в tasks. Stub оставляет residual risk до production-like/live-e2e.
- **Последняя фаза** — шаг запуска `masterspec-apply-change` для вливания в артефакты фабрики

Запиши в `masterspec/changes/<name>/tasks.md`.

### 9. Предложи ревью

После создания предложи пользователю проверить и дать обратную связь.

---

## Output

```
## Design Complete

**Change:** <change-name>
**Design:** masterspec/changes/<name>/design.md
**Tasks:** masterspec/changes/<name>/tasks.md

### Технические решения
- Архитектура реализации change: ...
- Изменения в сущностях кода: ...
- Миграция данных / конфигурации: ...

### Next Steps
- Просмотри design.md и tasks.md
- Дай обратную связь или подтверди
- Для реализации запусти скилл `masterspec-implement` (если установлен) или работай по tasks.md
- После реализации — `masterspec-apply-change` для вливания в артефакты фабрики

### Open Questions
- <вопросы, требующие ответа>
```

---

## Guardrails

- ВСЕГДА читай change.md и new/*.md перед началом
- ВСЕГДА изучай существующий код (не проектируй вслепую)
- НЕ придумывай технологии/библиотеки, которых нет в проекте
- Если контекст неясен — задавай вопросы, не делай предположений
- design.md ДОЛЖЕН ссылаться на конкретные сущности из кода проекта (классы/модули/пакеты/функции)
- tasks.md должен быть реализуемым — не добавляй нереальные задачи
- **design.md ≠ change.md**: change.md — что и зачем меняется в фабрике (логически); design.md — как это реализуется в коде (технически)
- При обновлении файлов сохраняй уже заполненные данные, если они корректны
- **Последний этап tasks.md** — вызов `masterspec-apply-change` (вливание diff-блоков и new/ в артефакты фабрики). Не забывай.

---

## Обновление при обратной связи

Если пользователь даёт обратную связь:
1. Прочитай текущие design.md и/или tasks.md
2. Примени запрошенные изменения
3. Сохрани файл
4. Сообщи что изменено
