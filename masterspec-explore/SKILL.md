---
name: masterspec-explore
description: >
  Structured research под мета-модель masterspec — кодовой базы (source=code) ИЛИ сырья
  в 00-source-data (source=docs: Confluence-выгрузки, готовые API-контракты, тест-кейсы,
  YAML структуры модулей, скетчи). Запускает параллельных read-only субагентов по ролям
  (requirements-scope, components-scope, scenarios-scope, data-scope, codemap-scope для кода;
  docs-inventory → те же роли + опциональная testcases-scope для сырья),
  агрегирует YAML и сохраняет в
  `masterspec/.research/` или `masterspec/changes/<name>/.research/`. Используй напрямую когда нужно
  разовое картирование фабрики или зоны изменения — триггеры «исследуй код для фабрики»,
  «картируй зону change», «собери research-notes для derive/evolve». Дополнительно работает как
  prompt-library для route-скиллов (`derive`/`evolve`/`recover`) —
  они переиспользуют `references/research-roles.md` и `references/invocation-contract.md`,
  оркестрируя субагентов сами.
when_to_use: >
  исследовать код для описания фабрики, картировать зону изменения,
  собрать research notes, structured research codebase, research for change,
  картируй сервис, research codebase, разобрать сырьё в 00-source-data,
  размётка входящих материалов, research по документам, explore docs
argument-hint: "[source=code|docs] [target=factory-spec|factory-change] roots=<пути к коду> | docs=<пути к материалам> [factory=<slug>] [name=<change>] [anchor=<paths|slugs>]"
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

# masterspec-explore — structured research кода и сырья

Исследование кодовой базы (`source=code`) или входящего сырья (`source=docs`) силами параллельных специализированных субагентов, агрегация их YAML-выводов и запись в `.research/` рядом с целевым артефактом. **Не модифицирует исходный код и не создаёт артефакты фабрики** — единственные записи это `.research/*.yaml` и `.research-notes.md`.

Conversational-режим **не поддерживается** — для размытого обсуждения используй обычный чат без скилла.

## Две роли скилла

1. **Standalone** — пользователь зовёт напрямую («картируй фабрику X», «research зону change»). Лид этого скилла сам принимает параметры, запускает субагентов и возвращает сводку.
2. **Prompt-library** для route-скиллов (`derive`/`evolve`/`recover`). Они читают `references/research-roles.md` и `references/invocation-contract.md` и оркестрируют субагентов сами.

> explore нужен там, где есть МАССИВ на разбор — код (`source=code`) или сырьё (`source=docs`). Если у фабрики нет ни того, ни другого (описание с нуля от бизнес-запроса), `derive`/`evolve` работают БЕЗ explore: контекст берётся из запроса, индекс ссылок — `Grep` по `-> ` в артефактах.
>
> **Код и сырьё режутся по-разному.** Код — по путям (ось «по слоям», каждому агенту свой срез каталогов). Документ так не режется: одна страница Confluence несёт и требования, и контракт, и тест-кейсы вперемешку. Поэтому сырьё режется по МАТЕРИАЛУ, и docs-ветка двухфазна: сначала опись и разметка, потом извлечение по слоям.

## Bundle-пути

- `references/X` — относительно директории этого скилла.
- Если harness даёт строку `Skill directory: <abs>` в обёртке активации — используй её.
- Иначе один раз `Glob("**/masterspec-explore/references/<file>")` и бери первый результат.
- Пусто → спроси пользователя путь установки.

## Bundled references

- `references/invocation-contract.md` — канонический контракт вызова субагентов: обнаружение tool-а и `subagent_type`, параллельный запуск, fallback, адаптация путей под стек, валидация YAML, дедупликация, персистентность.
- `references/research-orchestration.md` — классификация размера, оси декомпозиции, группировка, агрегация, fallback, таблица «слой → коллекции».
- `references/research-roles.md` — промпт-шаблоны ролей с YAML-контрактами: 5 для кода (requirements-scope, components-scope, scenarios-scope, data-scope, codemap-scope) + адаптация под factory-change; для сырья — `docs-inventory` (фаза A), docs-вариант scope-ролей и опциональная `testcases-scope` (фаза B).
- `references/code-analysis-priority.md` — приоритет инструментов: Serena → LSP → embeddings → MCP → Grep/Glob.
- `references/masterspec-awareness.md` — осведомлённость о `masterspec/`, активных changes, переиспользовании существующего codemap.

---

## Вход

Параметры, которые должны быть известны ДО запуска исследования:

- **source**: `code` (default) — исследуем кодовую базу; `docs` — исследуем сырьё.
- **target**: `factory-spec` (картируем всю фабрику под её описание) или `factory-change` (картируем зону изменения)
- **factory**: slug фабрики (kebab-case)
- **roots**: корневые пути исходного кода (для `source=code`). Без `roots` не запускайся.
- **docs**: пути к материалам (для `source=docs`); дефолт — `masterspec/00-source-data/`. Пусто → не запускайся, спроси где сырьё.

**Входной гейт:** комбинация `source=docs` + `target=factory-change` НЕ поддерживается (docs-роли картируют фабрику целиком; `anchor` в документах не определён). Запрошена — откажись и предложи `source=code target=factory-change`.

**Куда пишется research** (важно, иначе прогоны затирают друг друга): `<research-dir>/.research/<source>/` — то есть `.research/code/` и `.research/docs/` РАЗДЕЛЬНО. `recover source=both` делает оба прогона, и смешивать их нельзя: находки разной природы (`declared: true` против `code:<path>`).
- **anchor** (только для `target=factory-change`): пути/символы/slug'и, попадающие в скоуп изменения. Без них не запускайся.
- **thoroughness** (опционально): `quick` (default) / `medium`.

Если параметры не переданы — запроси у пользователя (или у вызывающего скилла). Не угадывай.

---

## Шаги — `source=code`

1. **Awareness.** Проверь `masterspec/` и активные changes. Подробности — [`references/masterspec-awareness.md`](references/masterspec-awareness.md).

   **Reuse — только по манифесту, не по mtime.** Каждый прогон пишет `<research-dir>/.research/<source>/_meta.yaml`: `source`, `target`, `roots`/`docs` (список), `anchor`, `run_id`, время, и отпечаток входа: для кода — `git rev-parse HEAD` + `git status --short`; для docs — sha256 нормализованного манифеста `path+size+sha256` по каждому файлу (число файлов и слов НЕ отпечаток: правка внутри файла их не меняет, а корпус уже другой). Переиспользуй прошлый research (субагентов не запускай) ТОЛЬКО если ВСЕ поля манифеста совпали с текущими параметрами и отпечаток входа тот же. Манифеста нет — собирай заново. mtime сам по себе ничего не доказывает: он не отличает другой `source`, другие `roots` и изменившийся корпус.

2. **Классифицируй размер.** По `research-orchestration.md § 2` (Малый <50 / Средний 50–500 / Крупный >500 файлов).

3. **Выбери роли и группировку.**
   - `target=factory-spec` → `requirements-scope`, `components-scope`, `scenarios-scope`, `data-scope`, `codemap-scope` (5 ролей).
   - `target=factory-change` → те же имена ролей, но с сужением до `anchor_paths` + адаптация формата вывода (§ «Роли для target=factory-change» в `research-roles.md`). По умолчанию 2 группы.

   Группировка по размеру — `research-orchestration.md § 3.1`/`§ 3.2`.

4. **Адаптируй границы.** Подставь реальные пути проекта в плейсхолдеры `<controllers/**>`, `<services/**>`, `<domain/**>` и т. д. Таблица эвристик по стекам (Spring / Go / FastAPI / Django / Express / .NET / Rails) — [`references/invocation-contract.md § 5`](references/invocation-contract.md). Зоны между группами не должны пересекаться.

5. **Создай каталог для результатов (до запуска субагентов).**

   Все пути считаются от ОДНОГО корня: `research_root = <research-dir>/.research/<source>` — и роли, и агрегат, и notes, и `_meta.yaml` пишутся только относительно него. Плоские пути `.research/<role>.yaml` больше не используются: они затирают прогон другого `source`.

   ```bash
   # target=factory-spec
   mkdir -p masterspec/.research/<source>        # code | docs

   # target=factory-change
   mkdir -p masterspec/changes/<name>/.research/<source>
   ```

6. **Запусти субагентов параллельно.**

   Имя tool-а и `subagent_type` — по алгоритму [`references/invocation-contract.md § 3.1`](references/invocation-contract.md). Промпты берутся **дословно** из [`references/research-roles.md`](references/research-roles.md). Параметры: `description` (3–5 слов), `prompt` (полный текст роли с подставленными путями), `task_id` — не использовать.

   Запуск — в одном ответе лида, одним блоком tool-use, несколько tool-вызовов. Последовательные вызовы в разных сообщениях = не параллель, переделать.

   Fallback: tool запуска субагента не найден → sequential sweep по ролям (`research-orchestration.md § 8`).

7. **Собери YAML-выводы.** По возврату каждого субагента — запиши в `<research_root>/<role>[-<batch-id>].yaml` (вариант A из `invocation-contract.md § 8.2`). Шардированная роль — только с `batch-id`, иначе шарды затирают друг друга. Валидация YAML по `invocation-contract.md § 6`.

8. **Агрегация.** Склей коллекции по ролям, сними дубли по ключам `invocation-contract.md § 7`. Запиши `_aggregate.yaml` + `.research-notes.md` (шаблон — `invocation-contract.md § 8.4`).

9. **Проверь полноту.** По таблице `research-orchestration.md § 6.1` (слой фабрики → коллекции агрегата). Пустые коллекции фиксируй в `gaps[]`.

10. **Верни вызывающему короткую сводку + путь к `.research-notes.md`**, не сырой YAML. Вызов от пользователя → покажи ту же сводку и предложи следующий скилл (`derive` / `evolve` / `recover`). См. `references/masterspec-awareness.md § 5`.

---

## Шаги — `source=docs`

Три фазы: опись → извлечение по слоям → стыковка тестов. Порядок не переставляется: без описи нечем нарезать границы, а без кандидатов B1 нечем стыковать тесты.

1. **Awareness и reuse** — по манифесту (см. шаг 1 code-ветки). `source` входит в манифест: docs-прогон не переиспользует code-research и наоборот.

2. **Сайзинг массива (лид считает САМ, до субагентов).** Файлы и слова (`research-orchestration.md § 2.1`): класс = максимум по обеим метрикам. Этот же `find`-список станет `expected` для проверки покрытия на шаге 8 — сохрани его.

3. **Фаза A — опись и разметка.** Один субагент `docs-inventory` (промпт — `references/research-roles.md`), границы = `docs`-пути. Не параллелить.

   Выход: `<research-dir>/.research/docs/docs-inventory.yaml` — классификация каждого файла (тип, объём, `authority`, `status`, слои-мишени, `machine_ready`, `duplicate_of`, срезы для oversized), `conflicts[]`, `totals`, предложение `batches[]`.

4. **Проверь предложение описи.** Батч тяжелее потолка (~40k слов) — дроби по материалам и срезам, роль запускается по шардам (`<role>-<batch-id>.yaml` + манифест шардов, `research-orchestration.md § 5.1`). Материал со `status: raw|blocked` в батчи НЕ включается — он не принят человеком. Материал с `duplicate_of` не читается.

5. **Фаза B1 — извлечение по слоям.** Роли `requirements-scope`, `components-scope`, `scenarios-scope`, `data-scope` в docs-варианте (`research-roles.md § Фаза B1`), запуск параллельный, одним блоком tool-use. Границы — срезы из батчей, не пути кода. Каждой роли в промпт: провенанс `<path>#<якорь>`, `declared: true`, запрет пересказывать machine-ready.

   Роли МОГУТ читать один и тот же материал (в одной странице Confluence и требования, и контракт) — это законно. Не пересекается ВЛАДЕНИЕ коллекциями: каждая коллекция агрегата имеет одну роль-владельца (`research-orchestration.md § 5`).

6. **Фаза B2 — стыковка тестов.** Роль `testcases-scope` — ТОЛЬКО после B1 и только если опись пометила `tc-acc`/`tc-int` в `target_artifacts` (хоть в файле, хоть в срезе). В промпт передаётся `<b1_candidates>` — список имён кандидатов из B1 (функции, сценарии, правила), иначе стыковать не с чем.

   `tc-flt` роль НЕ порождает: каталог отказов выводится из спеки (scn × api), а не из чужих тестов. Негативные проверки из материала идут в `fault_observations[]` как подсказка.

7. **Собери YAML-выводы** в `.research/docs/<role>[-<batch-id>].yaml`. Валидация — `invocation-contract.md § 6`. Агрегируй только когда получены ВСЕ ожидаемые шарды; недополученный шард — явный `gap`, не «меньше данных».

8. **Агрегация и покрытие.** Склей коллекции (`research-orchestration.md § 6`), сними дубли. Посчитай `coverage` ДВУМЯ независимыми разностями (одна общая формула прячет потерю): `expected − inventoried` = файлы, до которых не дошла опись; `eligible_inventory − processed` = описанные и допущенные (не raw/blocked, не дубли), но не разобранные фазой B. Файл, попавший в опись и не прочитанный ни одной ролью, обязан всплыть во второй разности. Итог — `coverage: {expected, inventoried, processed, status: complete|partial}` + поимённый список непокрытого.

   **`partial` — законный исход, тихая потеря — нет.** Массив, который не разобран целиком, обязан выглядеть как не разобранный целиком.

9. **Проверь стыковку.** Тесты с `traces_to.confidence: none` — в `gaps[]` поимённо: висячий `tc-` не заводится молча. Конфликты материалов (`conflicts[]` из описи) — в сводку: их решает владелец, не research.

10. **Верни сводку** + пути к `docs-inventory.yaml` и `.research-notes.md`. Статистика: разобрано материалов из скольких, `coverage.status`, сколько machine-ready взято как есть, сколько ТК стыковано / не стыковано.

---

## Выход---

## Выход

Два артефакта на диске + сводка в ответе:

1. `<research-dir>/.research/_aggregate.yaml` — машинный агрегат со всеми коллекциями (`functions[]`, `nfrs[]`, `rules[]`, `entities[]`, `components[]`, `capabilities[]`, `scenarios[]`, `algorithms[]`, `apis[]`, `data_schemas[]`, `component_maps[]`, `scenario_traces[]`, `data_maps[]`) + общий `gaps[]`. Для `source=docs` добавляются `machine_artifacts[]` и `test_cases[]`, а находки несут `declared: true` и провенанс `<path>#<якорь>`.
2. `<research-dir>/.research-notes.md` — человекочитаемая сводка.
3. Только для `source=docs`: `<research-dir>/.research/docs-inventory.yaml` — опись массива (что за материал, объём, куда относится, что machine-ready, что дубль).

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
- **Спец-коллекции docs-ветки потребляет только `recover`.** `machine_artifacts[]` (готовые контракты) и `test_cases[]` требуют импорта сайдкаров и стыковки со спекой — это работа `recover` (`source=docs`/`both`). `derive`/`gen` их не читают. Standalone `explore source=docs` законен как РАЗВЕДКА (посмотреть, что в массиве и что из него выйдет), но артефакты из этих коллекций родит только `recover` — не жди, что `derive` их подберёт.
- **Границы субагентов не пересекаются.** Перекрываются — укрупни задачи, уменьши число агентов.
- **Лид не читает сырьё сам** — ни файлы кода, ни документы: ни до запуска субагентов (кроме сайзинга через `find | wc -l` / `wc -w`), ни после (работай с YAML-сводками; точечный Read/Grep допустим только для уточнения конкретной gap, ≤3 файлов за раз).
- **Fallback если tool недоступен.** Sequential sweep ПОРЦИЯМИ с жёстким лимитом батча, сброс YAML на диск после каждой (`research-orchestration.md § 8`). Понижение класса массив не уменьшает — на крупном массиве (>500 файлов кода / >150k слов) честный STOP, а не «прочитаю сколько влезет».

## Траектория, изоляция и дозапрос
- Веди ТРАЕКТОРИЮ сбора: что и зачем собрано, по какому пути — не только итог. Это аудит-след контекста под правку.
- Research ПЕРСИСТЕНТЕН: `.research/` сохраняется для аудита, не удаляется автоматически после построения артефакта.
- Передавай генератору (`gen`) ИЗОЛИРОВАННЫЙ фокус-набор под его артефакт, а не всю фабрику. Если генератору не хватило — `explore` добирает ТОЛЬКО то, что из КОДА; срез документа/артефакта (в lean) добирает `planner`, не explore (единый маршрут — `../masterspec/references/patterns/context-isolation.md §Дозапрос`). Не более 2 раундов, потом эскалация человеку (открытый вопрос).
