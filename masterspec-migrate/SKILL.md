---
name: masterspec-migrate
description: >
  Переразложить отдельный артефакт фабрики на текущую schema-first / нотационную форму:
  api/data → машинный сайдкар (OpenAPI/AsyncAPI/JSON Schema), scn → notation, alg → form.
  Трансформация ФОРМЫ без обогащения — содержание артефакта уже полно, migrate детерминированно
  переразлагает его по новой форме, не домысливая ни одного нового факта. Всё неоднозначное или
  отсутствующее → MIGRATE-TODO в human-gate. Исполнитель форма-шага контура migration.md;
  версию (meta_model_version) НЕ штампует — её ставит сертификация по состоянию.
when_to_use: >
  перевести артефакт на schema-first форму, догенерировать машинный сайдкар к готовой спеке
  (api/data без sidecar), определить notation сценария или form алгоритма, переразложить legacy
  md-first артефакт (api-, data-, scn-, alg-) на текущую форму, migrate scn/alg
argument-hint: "artifact=<путь к .md> | factory=<путь к папке фабрики> [dry-run]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
---

# masterspec-migrate — переразложение формы артефакта

Перевожу существующий артефакт на текущую schema-first / нотационную форму. Принципиальное отличие
от `recover`: содержание артефакта уже **полно** — моя задача детерминированно переразложить его по
новой форме, а не домыслить недостающее.

> **Главный контракт:** MIGRATE-TODO — не пробел внимания, а осознанный сигнал.
> Я не угадываю то, чего в исходнике нет или что неоднозначно. Я называю это явно и оставляю человеку.

Таблицы маппинга полей, правила пометки и источники неоднозначности — в `references/migration-rules.md`.
Целевая форма — в мета-модели пакета `../masterspec/meta_model.md` (§6.3.2 scn, §6.3.3 alg, §6.3.4 api,
§6.3.5 data), шаблоны `../masterspec/templates/tpl-*.md`, реестр нотаций
`../masterspec/references/scenario-notation-registry.md`, форматы сайдкаров
`../masterspec/references/patterns/sidecar-formats.md`, дисциплина слоёв
`../masterspec/references/layer-discipline.md`.

---

## Место в контуре миграции

В 3.0 три разных «migrate» — не путать:

- **`../masterspec/references/migration.md`** — контур доведения ФАБРИКИ до текущего
  `meta_model_version` ОТ СОСТОЯНИЯ (детектор дельты → OE-дозаполнение `fn-` → перепрогон →
  сертификация версии). Работает на слое требований (OE-грани, `criticality`).
- **Migration-класс change** (`../masterspec/references/change-format.md §4.1`) — как оформляется
  миграционное изменение в дереве.
- **`masterspec-migrate` (этот скилл)** — ИСПОЛНИТЕЛЬ форма-переразложения ОТДЕЛЬНОГО артефакта
  слоя спецификаций: тело в старой форме (api/data в `.md` без сайдкара; scn/alg без `notation`/`form`)
  → schema-first / нотационная форма. Контур `migration.md` вызывает migrate на шаге «применение
  дозаполнения», когда детектор показал, что артефакт в старой ФОРМЕ, а не только неполон по OE.

> **Версию migrate НЕ штампует.** `meta_model_version` — сертификат состояния; его ставит
> сертификация (`migration.md` шаг 5, `apply-change §11`) после того, как ВСЕ применимые детекторы
> зелёные. migrate лишь переводит форму, ставит `status: draft` (human-gate обязателен) и
> `produced_by: migrate` (аудит происхождения).

---

## Scope

Переразлагаю форму: **`type: api`**, **`type: data-schema`** (тело → машинный сайдкар),
**`type: scenario`**, **`type: algorithm`** (тело → `notation` / `form`).

Остальные типы (`fn`, `cmp`, `dr`, `adr`, `cdm`, `dmap`, …) — форма не менялась. migrate их
**пропускает с пометкой в migration-report**: «вне scope формы».

> **boundary исключён из scope.** Атрибут `boundary` api (intra/inter/perimeter) migrate НЕ
> проставляет — реестр boundary и security-guardrails идут ОТДЕЛЬНЫМ тактом (Фаза 5). До него
> migrate не заводит `boundary` (ни значением, ни MIGRATE-TODO).

---

## Шаг 0 — подготовка

1. Прочитать артефакт (или обойти папку фабрики через Glob `**/*.md`).
2. Для каждого файла: определить `type` из фронтматтера.
3. Если форма уже целевая (api/data имеет `sidecar:`; scn имеет `notation:`; alg имеет `form:`) →
   пропустить, записать «уже в целевой форме» в report.
3a. Если артефакт несёт ЯВНОЕ записанное решение владельца о форме (напр. «.md-only — сайдкар не
   ведём», «форма заморожена») — НЕ переопределять молча: записать в report «решение владельца,
   migrate пропускает форму», оставить файл как есть. Снять/изменить такое решение — право владельца
   (human-gate), не migrate.
4. Если тип не api/data/scn/alg → «вне scope формы» в report, файл не трогать.
5. Если `dry-run` — только вывести план, без записи файлов.

---

## Алгоритм — api

**Фронтматтер** (детали — `references/migration-rules.md §1`):
- `type/slug/factory/owner/updated` — сохранить; `status: actual` → `status: draft` (downgrade
  обязателен: после migrate всегда draft до human-gate).
- `scope: internal | external` — СОХРАНИТЬ как есть. В 3.0 `scope` — это размещение (каталог
  internal/external), он НЕ переименовывается в `direction` (это был v2-концепт, 3.0 его не вводит).
  Тип взаимодействия уточняется в теле «## Тип API» (internal/external × sync/async) и per-операция
  для async (`produce`/`consume`) — migrate переносит их из исходника as-is, не синтезирует.
- добавить `sidecar_format` + `sidecar` по ПРИРОДЕ контракта (§1 / `patterns/sidecar-formats.md`,
  список открыт): sync HTTP/REST → `openapi-3.1`; event-driven (очереди/вебхуки/поллинг) →
  `asyncapi-2.x`; иной транспорт (gRPC→protobuf, SOAP→WSDL, GraphQL→SDL, …) — свой стандарт.
  **Транспорт без готового стандарта (напр. MTProto RPC) — НЕ синтезировать OpenAPI с фиктивными
  путями/методами:** оставить только компаньон + `# MIGRATE-TODO: машинная проекция — стандарт под
  транспорт не определён` (правило sidecar-formats «нотацию не выдумывай»).
- добавить `produced_by: migrate`.
- потребляемый внешний контракт (в исходнике есть recover-поле `provenance`) — блок `provenance:`
  целиком в MIGRATE-TODO (§1); migrate его не реконструирует.

**Тело → сайдкар:** разделы «Операции/события» и «Контракт» переносятся в машинный файл (operationId,
schemas). Логические типы → JSON Schema типы (`§3`). Где исходник неформален (тип прозой, путь/метод
не заданы) → `# MIGRATE-TODO: <цитата>`, НЕ синтезировать транспорт/тип. Компаньон `.md` становится
тонким: назначение, маппинги полей (YAML-блок, `§4`), ограничения (SLA/идемпотентность/ретраи), связи +
ссылка на сайдкар.

## Алгоритм — data

- `type/slug/factory/owner/updated` — сохранить; `status: actual` → `draft`.
- добавить `sidecar_format: json-schema-2020-12` + `sidecar: <slug>.schema.json`; `produced_by: migrate`.
- **Тело → сайдкар:** «Сущности»/«Ключевые атрибуты»/«Связи» → `$defs`/`properties`/`$ref` (`§2`).
  Тип не указан → `"x-migrate-todo"` рядом с полем (JSON не имеет `#`-комментариев). Стейт-машина
  (матрица состояние×событие) остаётся в компаньоне YAML-блоком (`§5`), схемой не выражается.

## Алгоритм — scn

- Определить `notation` ТОЛЬКО по фактическому содержимому (детекторы — `references/migration-rules.md §9`):
  готовый `plantuml`-sequence → `sequence` (as-is); `mermaid`-flowchart → `workflow` (as-is);
  строгая markdown-нумерация + полные ветвления → `yaml-graph` (детерминированная конвертация
  шаг→узел); иначе (нет нумерации ИЛИ неполное ветвление) → **holding route**: проза as-is +
  фиксированное `notation: yaml-graph` + `<!-- MIGRATE-TODO: переоформите по нотации (кандидат: X) -->`.
- `bpmn` migrate НЕ порождает (исходник не имел машинного `.bpmn`); ссылку на внешний BPMN — as-is + TODO.
- `pull-rules` НИКОГДА не выводить из прозы (§9).
- `status: actual` → `draft`; добавить `notation`, `produced_by: migrate`. Для `notation: bpmn` (только
  подтверждённое решение владельца) — `sidecar_format: bpmn-2.0` + `sidecar: <slug>.bpmn`.
- Участник со slug-ссылкой `-> cmp/cap` — перенести инлайн (yaml-graph/pull-rules) или в секцию
  «Участники» (диаграммные нотации). Участник прозой без slug → `<!-- MIGRATE-TODO: не резолвится -->`,
  маппинг НЕ выдумывать.

## Алгоритм — alg

- Определить `form` ТОЛЬКО по содержимому (`references/migration-rules.md §10`): «Правила» уже
  markdown-таблица «условия → результат» → `form: decision-table` (детерминированная конвертация в
  DMN-таблицу; Hit policy проставляется ТОЛЬКО если очевидна из исходника, иначе
  `**Hit policy:** <!-- MIGRATE-TODO -->`); иначе → `form: procedural` (проза as-is, безопасный дефолт).
- Кандидат в decision-table (классификатор прозой, но не таблицей) → `form: procedural` + TODO, НЕ
  конвертировать самостоятельно (синтез формы = домысел).
- `status: actual` → `draft`; добавить `form`, `produced_by: migrate`.
- `procedural`: «если X» без «иначе» → `<!-- MIGRATE-TODO: ветка "иначе" не описана -->`, не дописывать.

---

## Migration report

Для каждого артефакта — запись в `migration-report.md` (в папке фабрики): статус (переразложен /
пропущен как уже-в-форме / вне scope формы), созданные файлы, перечень MIGRATE-TODO, «требует
human-gate: да/нет». Для прогона по всей фабрике (`factory=`) — сводка по сценариям (сколько авто в
yaml-graph, сколько holding route, sequence/workflow as-is) и по алгоритмам (procedural /
decision-table), иначе вычитка человеком неуправляема.

---

## Human-gate (обязателен)

Результат migrate для `actual`-артефактов — всегда `status: draft` (downgrade обязателен). Нельзя
сразу ставить `actual`:
- MIGRATE-TODO могут быть критическими (provenance, тип поля, notation, участник, hit policy).
- `verify scope=spec` завалит артефакт с открытыми MIGRATE-TODO: незаполненный обязательный раздел
  формы — блокер **O1** (напр. пустая Hit policy для `decision-table`, отсутствующая секция «Участники»
  для диаграммной нотации); неразрешённая ссылка `-> cmp/cap` — **O2**; неполнота ветвлений/комбинаций
  — **O4a**.

`status: deprecated` на входе ОСТАЁТСЯ `deprecated` — migrate его не поднимает в `draft` («результат
всегда draft» относится к downgrade `actual`-артефактов, не к уже-`deprecated`).

После migrate — передать владельцу migration-report; владелец закрывает MIGRATE-TODO, применяет
`masterspec-verify scope=spec`, затем (когда фабрика целиком зелёная) сертификация штампует
`meta_model_version` — не migrate.

---

## Выход

- `<slug>.openapi.yaml`/`.asyncapi.yaml` (api) или `<slug>.schema.json` (data) — новый сайдкар.
- `<slug>.md` — обновлён: тонкий компаньон (api/data) или переразложенный по `notation`/`form` (scn/alg).
  Для scn/alg машинный файл migrate не создаёт (`bpmn`-сайдкар не порождается).
- `migration-report.md` с перечнем MIGRATE-TODO.

После migrate — вычитка `masterspec-verify scope=spec`.
