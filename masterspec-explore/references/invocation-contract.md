# Контракт вызова `masterspec-explore`

Для лид-скилов (`masterspec-derive`, `masterspec-evolve`, `masterspec-recover`), которые делегируют исследование в `masterspec-explore`. Цель файла — убрать двусмысленность в точках, где слабая модель (Qwen 9B, окно 200к) чаще всего ломается: невалидный YAML, адаптация плейсхолдеров, fallback, передача промптов, потеря промежуточных результатов при compact.

---

## 1. Пути к explore-справочникам

Лид-скил читает **три файла** перед запуском ролей:

```
masterspec-explore/references/invocation-contract.md  # этот файл
masterspec-explore/references/research-orchestration.md
masterspec-explore/references/research-roles.md
```

**Резолв пути.** Если harness передал `Skill directory: <abs>` в обёртке активации — бери от него. Иначе один раз `Glob("**/masterspec-explore/references/<file>")` и бери первый результат. Пусто → спроси пользователя путь установки, не ищи вручную по `~`/cwd.

---

## 2. Передача промптов субагентам: КОПИРУЙ ДОСЛОВНО

**Главное правило:** промпт роли из `research-roles.md` передаётся субагенту **без переписывания** — это YAML-контракт, от которого зависит агрегация.

Разрешено только:

1. **Подставить плейсхолдеры** `<dir/**>` на реальные пути проекта (см. § 5).
2. **Подставить anchor** в роли `requirements-scope`, `components-scope`, `scenarios-scope` при `target=factory-change`: `<anchor_paths>` → реальные пути/символы/slug'и из change.
3. **Указать thoroughness**: если роль в шаблоне предполагает переменную — поставь `quick` или `medium`.
4. **Добавить инструкцию про запись результата** — см. § 8.

Запрещено:

- Переформулировать «Цель», «Границы», «Формат вывода».
- Удалять поля из YAML-контракта, даже если кажутся лишними.
- Добавлять свои поля — субагент не даст их на выходе.
- «Упрощать» промпт — слабая модель не сможет восстановить YAML-схему.

Если кажется, что в шаблоне ошибка — зафиксируй в `gaps[]` результата и **не правь промпт на лету**.

---

## 3. Параллельный запуск субагентов — строгое требование

### 3.1. Обнаружение tool-а запуска субагента (case-sensitive!)

Имя tool-а и значения `subagent_type` **различаются по harness'ам и регистру**. Слабая модель 9B должна определить параметры из списка доступных в текущем harness'е инструментов и взять его форму — не угадывать по памяти.

**Известные варианты имён tool-а запуска read-only субагента:**

| Имя tool-а (регистр важен) | subagent_type read-only | subagent_type general (fallback) |
|----------------------------|-------------------------|----------------------------------|
| `Agent` | `Explore` | `general-purpose` |
| `task` | `explore` | `general` |
| `Task` | `Explore` или `explore` | `general-purpose` или `general` |
| `spawn_agent` / `spawn_subagent` | обычно `explore` | обычно `general` |

**Алгоритм обнаружения (выполни один раз перед параллельным запуском):**

1. Пройдись по списку доступных инструментов harness'а (tool registry / system-reminder / документация harness'а).
2. Найди первый матч по регексу case-insensitive: `^(agent|task|spawn_agent|spawn_subagent)$`. Используй имя **в том регистре, в котором его отдаёт harness** (`Agent` ≠ `agent` ≠ `task`).
3. Для `subagent_type` попробуй по приоритету (первый принятый harness'ом — используй):
   - read-only дефолт: `Explore` → `explore`
   - general fallback: `general-purpose` → `general`
4. Запомни пару `(tool_name, subagent_type)` и используй одну и ту же во всех параллельных вызовах в сессии.
5. Если ни один tool из списка не доступен → sequential sweep лидом (см. § 4 шаг 3).

### 3.2. Параметры каждого вызова

- `subagent_type` — из § 3.1, таблица выше.
- `description` — короткая строка 3-5 слов, например `"Research requirements+components"`. Используется для UI.
- `prompt` — полный текст роли из `research-roles.md` дословно, с подставленными путями.
- `task_id` — **не использовать**. Скил запускает субагентов one-shot; возвращаемый результат (YAML) — единственное, что лиду нужно. Сессионность (продолжение `task_id`) не применяется.

### 3.3. Параллельный запуск (MUST)

Все субагенты стартуют **в одном ответном сообщении лида**, в котором последовательно идут несколько tool-вызовов без промежуточного текста между ними и без ожидания ответа. Это единственный способ получить настоящую параллель — harness запускает их одной волной и возвращает результаты одним пакетом.

Корректно (параллельно, одно ответное сообщение лида, несколько tool-вызовов в одном блоке) — **псевдокод, не буквальный синтаксис**, настоящий вызов делаешь через native tool-call API своего harness'а с именем и параметрами из § 3.1:

```
tool: <имя из § 3.1>
  subagent_type: <значение read-only из § 3.1>
  description: Research api
  prompt: |
    <роль api>

tool: <имя из § 3.1>
  subagent_type: <значение read-only из § 3.1>
  description: Research business-logic+data
  prompt: |
    <роль business-logic + data>

tool: <имя из § 3.1>
  subagent_type: <значение read-only из § 3.1>
  description: Research integrations+config+obs+sec+nfr
  prompt: |
    <роль integrations + config + observability + security + nfr>
```

Конкретный вызов — после § 3.1: подставь обнаруженное имя tool-а и subagent_type. Например, если в текущем harness'е зарегистрирован tool `Agent` с типом `Explore` — вызовы будут `Agent(subagent_type="Explore", ...)`; если `task` с `explore` — `task(subagent_type="explore", ...)`. Формат параметров одинаков: `description`, `prompt`, без `task_id`.

Неправильно (последовательно — каждое в отдельном сообщении лида):

```
# сообщение 1 → [ждёт возврата] → сообщение 2 → [ждёт] → сообщение 3
```

Второй вариант съедает время кратно числу ролей и забивает окно лида сырыми выводами по одному — вместо одной «волны».

Проверка: если ты написал несколько вызовов tool-а запуска субагента и **каждый в отдельном ответном сообщении лида** — это последовательно, переделай.

---

## 4. Fallback-цепочка для subagent_type

Порядок попыток — сверху вниз. На каждой ступени — одна попытка, без ретраев:

| Шаг | subagent_type (по § 3.1) | Условие применения |
|-----|-------------------------|--------------------|
| 1 | read-only (`Explore` или `explore`) | встроен и доступен — используй как дефолт |
| 2 | general (`general-purpose` или `general`) | read-only вариант отсутствует или вернул ошибку «unknown subagent type» |
| 3 | sequential sweep (лид сам) | Tool запуска субагента вообще не найден — пройди по ролям последовательно, как в `research-orchestration.md § 8` |

При fallback на general-тип (он обычно НЕ read-only) — **явно добавь в промпт** блок запретов:

```
## Дополнительные запреты
- Ты работаешь в read-only режиме. Никаких Edit, Write, Bash с записью, git-операций.
- Разрешены только инструменты чтения: Read, Glob, Grep; Serena find_symbol / get_symbols_overview / find_referencing_symbols.
```

Это не дублирование — у read-only-субагента (`Explore`/`explore`) запрет уже встроен; у `general-purpose`/`general` — нужно прописать. **Исключение:** если задействован сценарий записи промежуточного результата по § 8 (субагент пишет свой YAML сам) — тогда в промпте general-субагента добавляется **один разрешённый Write** на указанный путь.

---

## 5. Адаптация плейсхолдеров путей под стек

В шаблонах ролей пути записаны как `<controllers/**>`, `<services/**>` и т. д. Лид заменяет их на реальные пути **до** запуска субагента. Если не адаптировать — Qwen оставит литералы `<controllers/**>` и субагент ничего не найдёт.

Мини-таблица эвристик по стекам. Проверяй по дереву проекта; если стек не распознаётся — делай Glob по типовым маркерам.

| Стек | Маркеры | `<controllers/**>` | `<services/**>` | `<entity/**>` | `<integration/**>` | Конфиги |
|------|---------|--------------------|------------------|--------------|--------------------|---------|
| **Spring Boot (Java/Kotlin)** | `pom.xml`/`build.gradle` + `spring-boot`, `@RestController` | `**/controller/**`, `**/rest/**`, `**/api/**`, `**/web/**` | `**/service/**`, `**/usecase/**`, `**/application/**` | `**/entity/**`, `**/domain/**`, `**/model/**`, `**/repository/**` | `**/kafka/**`, `**/grpc/**`, `**/integration/**`, `**/client/**` | `**/resources/application*.{yml,yaml,properties}` |
| **Go (стандартный проект)** | `go.mod`, `main.go` | `**/handler/**`, `**/api/**`, `**/transport/**`, `**/cmd/**` | `**/service/**`, `**/usecase/**`, `**/internal/app/**` | `**/model/**`, `**/store/**`, `**/repository/**`, `**/entity/**` | `**/client/**`, `**/broker/**`, `**/kafka/**`, `**/grpc/**` | `**/config/*.{yml,yaml}`, `.env*`, `**/configs/**` |
| **FastAPI (Python)** | `pyproject.toml` + `fastapi`, `main.py`/`app.py` | `**/routers/**`, `**/api/**`, `**/endpoints/**` | `**/services/**`, `**/usecases/**` | `**/models/**`, `**/schemas/**`, `**/db/**`, `**/crud/**` | `**/clients/**`, `**/integrations/**`, `**/tasks/**` | `**/settings.py`, `**/config.py`, `.env*` |
| **Django** | `manage.py`, `settings.py` | `**/views.py`, `**/views/**`, `**/viewsets/**` | `**/services.py`, `**/services/**` | `**/models.py`, `**/models/**`, `**/migrations/**` | `**/tasks.py`, `**/clients/**`, `**/integrations/**` | `**/settings.py`, `**/settings/*.py`, `.env*` |
| **Express/NestJS (TS/JS)** | `package.json` + `express`/`@nestjs/core` | `**/*.controller.ts`, `**/routes/**`, `**/controllers/**` | `**/*.service.ts`, `**/services/**` | `**/*.entity.ts`, `**/entities/**`, `**/schemas/**`, `**/repositories/**` | `**/*.client.ts`, `**/clients/**`, `**/integrations/**` | `**/config/**`, `.env*`, `nest-cli.json` |
| **.NET / ASP.NET** | `*.csproj`, `Program.cs` | `**/Controllers/**` | `**/Services/**`, `**/Handlers/**` | `**/Models/**`, `**/Entities/**`, `**/Data/**` | `**/Clients/**`, `**/Integrations/**` | `appsettings*.json`, `**/Configuration/**` |
| **Rails (Ruby)** | `Gemfile` + `rails`, `config/routes.rb` | `app/controllers/**` | `app/services/**`, `app/use_cases/**` | `app/models/**`, `db/migrate/**` | `app/jobs/**`, `app/clients/**` | `config/*.yml`, `config/environments/**` |

Правила адаптации:

1. Сначала подтверди стек одним Glob (например, `pom.xml` → Spring). Если маркеров нет — делай универсальный Glob по обоим рукам эвристик.
2. Подставляй **все** подходящие пути через запятую: `**/controller/**, **/rest/**, **/api/**`. Лучше лишние пути, чем пропущенный слой.
3. Для **монорепо** добавляй префикс модуля: `services/orders/**/controller/**`.
4. Плейсхолдеры `openapi*.{yaml,yml,json}`, `*.proto`, `*.avsc`, `*.sql` — **не трогай**, они уже универсальные.
5. Если плейсхолдер не подошёл ни к чему — удали строку из промпта и зафиксируй в комментарии «нет такого слоя в проекте».

---

## 6. Валидация YAML-выводов субагентов

После возврата каждого субагента — лид делает **одну проверку** перед склейкой:

1. **Парсинг YAML.** Если не парсится — считай вывод невалидным.
2. **Ключевые поля.** Для каждой роли должны быть `summary`, `key_files`, плюс доменные коллекции из контракта роли (например, `functions[]`, `components[]`, `scenarios[]`, `apis[]`, `data_schemas[]` — перечень полей — в `research-roles.md` под каждой ролью).
3. **Лимит summary ≤200 слов.** Если сильно больше — считай, что субагент вышел за контракт.

### Что делать при невалидном YAML

**Ровно одна попытка повтора**, без бесконечного цикла:

```
Твой предыдущий вывод не прошёл валидацию YAML по следующим причинам:
<перечисли>

Пожалуйста, переотправь ТОЛЬКО YAML-блок, строго по контракту роли <role-name> из шаблона. Без markdown-окантовки, без комментариев до/после блока.
```

Если после повтора снова невалидно — зафиксируй роль в `gaps[]` как `"role <name>: invalid YAML after retry, <reason>"` и продолжи агрегацию без этой роли.

**Не пытайся восстановить YAML вручную** — слабая модель сделает это неправильно.

---

## 7. Дедупликация на стыке ролей

Три роли (`data-scope`, `components-scope`, `codemap-scope`) обязаны искать одни и те же файлы схем (`*.proto`, `*.avsc`, OpenAPI, SQL DDL) и одни и те же файлы кода при определении границ компонентов. Это **ожидаемое** частичное пересечение — дубли снимает лид при агрегации.

Правила дедупликации:

| Коллекция | Ключ дедупликации |
|-----------|-------------------|
| `functions[]` (кандидаты в `fn-`) | `name` |
| `nfrs[]` | `category` + `metric` |
| `rules[]` | `id` (или нормализованный `statement`) |
| `entities[]` (кандидаты в `cdm-`) | `name` |
| `dictionaries[]` (кандидаты в `dict-`) | `name` |
| `components[]` (кандидаты в `cmp-`) | `name` |
| `capabilities[]` (подразделы `cap-*`) | `component` + `name` |
| `scenarios[]` (кандидаты в `scn-`) | `name` |
| `algorithms[]` (кандидаты в `alg-`) | `name` |
| `apis[]` (кандидаты в `api-`) | `method` + `path` (REST), `service` + `method` (gRPC) |
| `data_schemas[]` (кандидаты в `data-`) | `file` + `name` |
| `openapi_specs[]` / `proto_files[]` / `avsc_files[]` | `path` |
| `migrations[]` | `file` + `version` |
| `component_maps[]` (для `cmap-`) | `component_slug` |
| `scenario_traces[]` (для `trace-`) | `scenario_slug` |
| `data_maps[]` (для `dmap-`) | `entity_slug` |
| `repo_entries[]` | `repo` + `root_path` |

Если две записи с одним ключом отличаются по содержимому — оставь **более полную**, а расхождение **не выкидывай**: добавь в `gaps[]` как `"divergence in <collection>/<key>: role A says X, role B says Y"`.

---

## 8. Персистентность промежуточных результатов

**Проблема.** Окно лида 200к. При исследовании Крупного проекта сумма сырых YAML-выводов может уйти в compact — и агрегат теряется. Ошибка в одном из субагентов, ретрай — лид забыл уже склеенные поля. Нужна страховка на диске.

**Правило.** Все промежуточные результаты пишутся в файлы сразу, без задержки. В контексте лида остаются только ссылки и итоговый агрегат.

### 8.1. Структура каталога `.research/`

Для **factory-spec** (`target=factory-spec` — картируем всю фабрику):

```
masterspec/
├── .research/
│   ├── requirements-scope.yaml
│   ├── components-scope.yaml
│   ├── scenarios-scope.yaml
│   ├── data-scope.yaml
│   ├── codemap-scope.yaml
│   └── _aggregate.yaml          # итоговая склейка после дедупа
├── .research-notes.md            # markdown-сводка для интервью (human-readable)
└── 00-masterspec-index.md           # индекс фабрики (если уже есть)
```

Для **factory-change** (`target=factory-change` — картируем зону изменения):

```
masterspec/changes/<name>/
├── .research/
│   ├── requirements-scope.yaml
│   ├── components-scope.yaml
│   ├── scenarios-scope.yaml
│   └── _aggregate.yaml
├── .research-notes.md
└── change.md                     # финальный change (создаётся позже)
```

Директорию создать через `mkdir -p masterspec/.research` (для factory-spec) или `mkdir -p masterspec/changes/<name>/.research` (для factory-change) **до** запуска субагентов.

### 8.2. Кто пишет — лид или субагент

Два варианта. Выбор — по доступности Write у субагента.

**Вариант A (предпочтительный): лид пишет сам сразу после возврата субагента.**

```
# Один ответ лида (параллельно, несколько вызовов tool-запуска-субагента в одном tool-use блоке):
# <TOOL> и <ST> — обнаруженные по алгоритму § 3.1.
<TOOL>(subagent_type="<ST>", description="Research api", prompt="<роль api>")
<TOOL>(subagent_type="<ST>", description="Research business-logic+data", prompt="<роль business-logic+data>")
...

# Следующий ответ лида (после возврата всех субагентов):
Tool: Write
  file_path: <abs-path>/.research/api.yaml
  content: <raw YAML от субагента api>

Tool: Write
  file_path: <abs-path>/.research/business-logic.yaml
  content: <raw YAML от business-logic>
...
```

Запись идёт **до** валидации и дедупа. Валидируем уже по файлу: если YAML-файл не парсится — запускаем retry-промпт (см. § 6), новый результат перезаписывает файл.

**Вариант B: субагент пишет сам (когда subagent_type поддерживает Write).**

Добавь в промпт роли блок:

```
## Запись результата

После подготовки YAML-ответа:
1. Сначала запиши YAML в файл `masterspec/.research/<role>.yaml` (для factory-spec) или `masterspec/changes/<name>/.research/<role>.yaml` (для factory-change) через Write.
2. Затем верни в stdout только одну строку: `RESULT_WRITTEN_TO: <путь>`.

Не возвращай YAML дважды (и в файл, и в stdout) — это удваивает токены лида.
```

Вариант B эффективнее по токенам лида, но требует Write у субагента. Если subagent_type = `Explore` (read-only) — используй **только** Вариант A. Если `general-purpose` + явно разрешённый Write — можно B.

### 8.3. Когда это обязательно

| Размер проекта | Персистентность |
|---------------|-----------------|
| Малый (2 агента) | **рекомендуется** — стоит дёшево, страхует от ошибок |
| Средний (2–3 агента) | **обязательно** |
| Крупный (3–6 агентов) | **обязательно + вариант B при возможности** (экономит окно лида) |

Для factory-change: обязательно всегда, независимо от размера — интервью опирается на находки из разных ролей (затронутые компоненты, сценарии, данные), терять их дорого.

### 8.4. `_aggregate.yaml` и `.research-notes.md`

После валидации и дедупа лид **всегда** пишет два файла:

- `.research/_aggregate.yaml` — машинный агрегат, сырой YAML со всеми коллекциями, склеенными по ключам § 7.
- `.research-notes.md` — human-readable markdown-сводка: что нашли, сколько endpoints/entities/integrations/params, список `gaps[]`. Это то, что лид перечитает после compact.

Шаблон `.research-notes.md`:

```markdown
# Research notes: <factory или change name>

- **Target**: factory-spec | factory-change
- **Generated**: <ISO timestamp>
- **Size class**: Малый | Средний | Крупный
- **Roles run**: [requirements-scope, components-scope, scenarios-scope, ...]

## Аггрегат
<краткая статистика: 8 fn-кандидатов, 4 cmp-кандидата, 3 scn, 12 file:line codemap-привязок, ...>

## Gaps (вопросы для Этапа 2 интервью)
- [ ] <gap 1>
- [ ] <gap 2>

## Файлы
- Полный агрегат: `.research/_aggregate.yaml`
- По ролям: `.research/requirements-scope.yaml`, `.research/components-scope.yaml`, ...
```

### 8.5. Восстановление после compact

Если контекст лида усечён и нужно продолжить:

1. Прочитать `.research-notes.md` — получить список gaps и состояние.
2. При необходимости — открыть `.research/_aggregate.yaml` для конкретной коллекции.
3. Не перезапускать субагентов, если их результаты валидны в `.research/<role>.yaml`.

### 8.6. Очистка

После создания финального артефакта (`<service>.md` или `change.md` готов и прошёл ревью) каталог `.research/` и `.research-notes.md` можно удалить. Они не коммитятся — добавить в `.gitignore`:

```
masterspec/.research/
masterspec/.research-notes.md
masterspec/changes/*/.research/
masterspec/changes/*/.research-notes.md
```

Если `.gitignore` отсутствует — создать или предупредить пользователя, что эти пути не должны попасть в коммит.

---

## 9. Когда лид вообще не запускает `masterspec-explore`

Правило по умолчанию: **всегда запускай**. Исключений ровно два:

1. **tool запуска субагента недоступен** — переход на sequential sweep (§ 4, шаг 3). Это **fallback**, не оптимизация. Уведоми пользователя явно: «tool запуска субагента недоступен, перехожу на последовательное чтение по ролям». Даже при sweep лид пишет результаты по ролям в `.research/<role>.yaml` — чтобы не потерять прогресс.
2. **Уже есть свежий `.research-notes.md`** рядом с артефактом. Проверь `mtime` (не старше 24 часов) и что `target` совпадает с текущим. Если да — переиспользуй агрегат из файла, субагентов не запускай повторно.

**Размер проекта НЕ является основанием пропустить субагентов.** Даже для Малого (<50 файлов, 1 модуль) запускаются 2 субагента — группировка в `research-orchestration.md § 3`. Причина — лид не должен читать исходный код, иначе ломается контракт и дедупликация. Если проект реально крошечный (≤10 файлов) — один субагент с объединённым промптом всех ролей, но **не** «лид читает сам».

---

## 10. Сжатая шпаргалка для лида (порядок действий)

1. Определить `target` (`factory-spec` | `factory-change`), `factory` (slug), `anchor` (для factory-change). Нет параметров → выйти.
2. Прочитать `masterspec-explore/SKILL.md` + `research-orchestration.md` + `research-roles.md` — именно по путям из § 1.
3. Проверить наличие tool запуска субагента. Нет → fallback на sequential sweep (§ 4). Есть → дальше.
4. Проверить наличие свежего `.research-notes.md` (§ 9, п. 2). Есть и свежий → переиспользовать, субагентов не запускать.
5. Классифицировать размер (§ 2 в orchestration).
6. Подобрать роли и группировку (§ 3 в orchestration).
7. Адаптировать плейсхолдеры под стек (§ 5 этого файла).
8. Создать каталог `.research/` (`mkdir -p`) — § 8.
9. Запустить субагентов **одним сообщением, параллельно** (§ 3). Имя tool-а и `subagent_type` — обнаружить по алгоритму § 3.1 (регекс по списку доступных инструментов harness'а). Параметры: `description=<короткое>`, `prompt=<ВЕРБАТИМ из research-roles.md>`.
10. Сразу записать каждый возвратный YAML в `.research/<role>.yaml` (§ 8.2, вариант A).
11. Валидировать каждый YAML (§ 6). При ошибке — одна попытка повтора, файл перезаписывается.
12. Склеить, дедуп по ключам (§ 7), проверить полноту по таблице § 6.1 в orchestration.
13. Записать `_aggregate.yaml` и `.research-notes.md` (§ 8.4).
14. Отдать агрегат вызывающему лиду (= себе) для Этапа 2 интервью.
