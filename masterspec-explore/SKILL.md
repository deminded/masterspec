---
name: masterspec-explore
description: >
  Structured research кодовой базы под мета-модель masterspec. Запускает параллельных
  read-only субагентов по 5 специализированным ролям (requirements-scope, components-scope,
  scenarios-scope, data-scope, codemap-scope для target=factory-spec; те же роли с сужением
  до anchor_paths для target=factory-change), агрегирует YAML и сохраняет в
  `masterspec/.research/` или `masterspec/changes/<name>/.research/`. Используй напрямую когда нужно
  разовое картирование фабрики или зоны изменения — триггеры «исследуй код для фабрики»,
  «картируй зону change», «собери research-notes для derive/evolve». Дополнительно работает как
  prompt-library для route-скиллов (`derive`/`evolve`/`recover`) —
  они переиспользуют `references/research-roles.md` и `references/invocation-contract.md`,
  оркестрируя субагентов сами.
when_to_use: >
  исследовать код для описания фабрики, картировать зону изменения,
  собрать research notes, structured research codebase, research for change,
  картируй сервис, research codebase
argument-hint: "[target: factory-spec|factory-change] roots=<пути к коду> [factory=<slug>] [name=<change>] [anchor=<paths|slugs>]"
license: MIT
compatibility: >
  Использует bash/git и встроенный tool запуска read-only субагента (при отсутствии — sequential sweep, research-orchestration §8)
  (имя и subagent_type — по таблице § 3.1 references/invocation-contract.md).
  Опционально Serena/LSP/embedding MCP-серверы — сильно повышают качество исследования.
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
---

# masterspec-explore — structured research кодовой базы

Исследование кодовой базы силами параллельных специализированных субагентов, агрегация их YAML-выводов и запись в `.research/` рядом с целевым артефактом. **Не модифицирует исходный код и не создаёт артефакты фабрики** — единственные записи это `.research/*.yaml` и `.research-notes.md`.

Conversational-режим **не поддерживается** — для размытого обсуждения используй обычный чат без скилла.

## Две роли скилла

1. **Standalone** — пользователь зовёт напрямую («картируй фабрику X», «research зону change»). Лид этого скилла сам принимает параметры, запускает субагентов и возвращает сводку.
2. **Prompt-library** для route-скиллов (`derive`/`evolve`/`recover`). Они читают `references/research-roles.md` и `references/invocation-contract.md` и оркестрируют субагентов сами.

> explore нужен только когда у фабрики ЕСТЬ код. Для фабрики или слоя без кода (описание с нуля от бизнес-запроса) `derive`/`evolve` работают БЕЗ explore: контекст берётся из бизнес-запроса, индекс ссылок — `Grep` по `-> ` в артефактах.

## Bundle-пути

- `references/X` — относительно директории этого скилла.
- Если harness даёт строку `Skill directory: <abs>` в обёртке активации — используй её.
- Иначе один раз `Glob("**/masterspec-explore/references/<file>")` и бери первый результат.
- Пусто → спроси пользователя путь установки.

## Bundled references

- `references/invocation-contract.md` — канонический контракт вызова субагентов: обнаружение tool-а и `subagent_type`, параллельный запуск, fallback, адаптация путей под стек, валидация YAML, дедупликация, персистентность.
- `references/research-orchestration.md` — классификация размера, оси декомпозиции, группировка, агрегация, fallback, таблица «слой → коллекции».
- `references/research-roles.md` — 5 промпт-шаблонов ролей с YAML-контрактами (requirements-scope, components-scope, scenarios-scope, data-scope, codemap-scope) + адаптация под factory-change.
- `references/code-analysis-priority.md` — приоритет инструментов: Serena → LSP → embeddings → MCP → Grep/Glob.
- `references/masterspec-awareness.md` — осведомлённость о `masterspec/`, активных changes, переиспользовании существующего codemap.

---

## Вход

Параметры, которые должны быть известны ДО запуска исследования:

- **target**: `factory-spec` (картируем всю фабрику под её описание) или `factory-change` (картируем зону изменения)
- **factory**: slug фабрики (kebab-case)
- **roots**: корневые пути исходного кода. Без `roots` не запускайся.
- **anchor** (только для `target=factory-change`): пути/символы/slug'и, попадающие в скоуп изменения. Без них не запускайся.
- **thoroughness** (опционально): `quick` (default) / `medium`.

Если параметры не переданы — запроси у пользователя (или у вызывающего скилла). Не угадывай.

---

## Шаги

1. **Awareness.** Проверь `masterspec/` и активные changes. Подробности — [`references/masterspec-awareness.md`](references/masterspec-awareness.md). Переиспользуй существующий `.research-notes.md` (субагентов не запускай) ТОЛЬКО если совпали ВСЕ условия: mtime < 24 ч; тот же `target`; те же `roots` и (для `factory-change`) `anchor`; код не менялся с момента сбора (`git status`/mtime исходников). Любое расхождение — собирай заново, иначе оркестратор получит устаревший контекст.

2. **Классифицируй размер.** По `research-orchestration.md § 2` (Малый <50 / Средний 50–500 / Крупный >500 файлов).

3. **Выбери роли и группировку.**
   - `target=factory-spec` → `requirements-scope`, `components-scope`, `scenarios-scope`, `data-scope`, `codemap-scope` (5 ролей).
   - `target=factory-change` → те же имена ролей, но с сужением до `anchor_paths` + адаптация формата вывода (§ «Роли для target=factory-change» в `research-roles.md`). По умолчанию 2 группы.

   Группировка по размеру — `research-orchestration.md § 3.1`/`§ 3.2`.

4. **Адаптируй границы.** Подставь реальные пути проекта в плейсхолдеры `<controllers/**>`, `<services/**>`, `<domain/**>` и т. д. Таблица эвристик по стекам (Spring / Go / FastAPI / Django / Express / .NET / Rails) — [`references/invocation-contract.md § 5`](references/invocation-contract.md). Зоны между группами не должны пересекаться.

5. **Создай каталог для результатов (до запуска субагентов).**

   ```bash
   # target=factory-spec
   mkdir -p masterspec/.research

   # target=factory-change
   mkdir -p masterspec/changes/<name>/.research
   ```

6. **Запусти субагентов параллельно.**

   Имя tool-а и `subagent_type` — по алгоритму [`references/invocation-contract.md § 3.1`](references/invocation-contract.md). Промпты берутся **дословно** из [`references/research-roles.md`](references/research-roles.md). Параметры: `description` (3–5 слов), `prompt` (полный текст роли с подставленными путями), `task_id` — не использовать.

   Запуск — в одном ответе лида, одним блоком tool-use, несколько tool-вызовов. Последовательные вызовы в разных сообщениях = не параллель, переделать.

   Fallback: tool запуска субагента не найден → sequential sweep по ролям (`research-orchestration.md § 8`).

7. **Собери YAML-выводы.** По возврату каждого субагента — запиши в `.research/<role>.yaml` (вариант A из `invocation-contract.md § 8.2`). Валидация YAML по `invocation-contract.md § 6`.

8. **Агрегация.** Склей коллекции по ролям, сними дубли по ключам `invocation-contract.md § 7`. Запиши `_aggregate.yaml` + `.research-notes.md` (шаблон — `invocation-contract.md § 8.4`).

9. **Проверь полноту.** По таблице `research-orchestration.md § 6.1` (слой фабрики → коллекции агрегата). Пустые коллекции фиксируй в `gaps[]`.

10. **Верни вызывающему короткую сводку + путь к `.research-notes.md`**, не сырой YAML. Вызов от пользователя → покажи ту же сводку и предложи следующий скилл (`derive` / `evolve` / `recover`). См. `references/masterspec-awareness.md § 5`.

---

## Выход

Два артефакта на диске + сводка в ответе:

1. `<research-dir>/.research/_aggregate.yaml` — машинный агрегат со всеми коллекциями (`functions[]`, `nfrs[]`, `rules[]`, `entities[]`, `components[]`, `capabilities[]`, `scenarios[]`, `algorithms[]`, `apis[]`, `data_schemas[]`, `component_maps[]`, `scenario_traces[]`, `data_maps[]`) + общий `gaps[]`.
2. `<research-dir>/.research-notes.md` — человекочитаемая сводка.

В ответе вызывающему:

- Путь к `.research-notes.md` и `.research/_aggregate.yaml`.
- Краткая статистика (N fn-кандидатов, M cmp-кандидатов, K scn, L apis, P data_schemas).
- Список `gaps[]` как приоритизированные вопросы.

**Не вставляй сырой YAML в ответ вызывающему** — данные уже на диске.

---

## Ограничения

- **Не трогает исходный код и артефакты фабрики.** Единственные записи — `.research/*.yaml` и `.research-notes.md`. Фиксация артефактов — через `derive`/`evolve` (с вычиткой и гейтом, затем apply-change).
- **Conversational-режим не поддерживается.** Размытые вопросы без `target`/`factory`/`roots` → уточнить и направить в подходящий скилл.
- **Рекурсия субагентов запрещена.** Субагент не имеет права звать другого.
- **Границы субагентов не пересекаются.** Перекрываются — укрупни задачи, уменьши число агентов.
- **Лид не читает сырые файлы кода** ни до запуска субагентов (кроме классификации размера через `find | wc -l`), ни после (работай с YAML-сводками; точечный Read/Grep допустим только для уточнения конкретной gap, ≤3 файлов за раз).
- **Fallback если tool недоступен.** Снижай класс размера на ступень и делай sequential sweep по каталогу ролей (`research-orchestration.md § 8`).

## Траектория, изоляция и дозапрос
- Веди ТРАЕКТОРИЮ сбора: что и зачем собрано, по какому пути — не только итог. Это аудит-след контекста под правку.
- Research ПЕРСИСТЕНТЕН: `.research/` сохраняется для аудита, не удаляется автоматически после построения артефакта.
- Передавай генератору (`gen`) ИЗОЛИРОВАННЫЙ фокус-набор под его артефакт, а не всю фабрику. Если генератору не хватило — `explore` добирает ТОЛЬКО то, что из КОДА; срез документа/артефакта (в lean) добирает `planner`, не explore (единый маршрут — `../masterspec/references/patterns/context-isolation.md §Дозапрос`). Не более 2 раундов, потом эскалация человеку (открытый вопрос).
