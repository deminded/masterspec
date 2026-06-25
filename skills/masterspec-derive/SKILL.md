---
name: masterspec-derive
description: >
  Породить слой фабрики по мета-модели masterspec. layer=req — из бизнес-запроса (и, если есть код,
  из агрегата explore) в слой требований; layer=spec — из согласованных требований в слой спецификаций.
  При отсутствии фабрики инициализирует её (скелет каталога, глоссарий). Оркестратор слоя:
  разворачивает слой на элементы, на каждый зовёт gen (узел-исполнение) или узел-решение, гонит verify,
  ставит human-gate.
when_to_use: >
  спроектировать слой требований или спецификаций, описать фабрику с нуля,
  derive <factory> layer=req, derive <factory> layer=spec, сгенерировать as/fn/nfr/rules/cdm или cmp/scn/api/data
argument-hint: "<factory-slug> layer=req|spec [pass=linear|parallel] [verify=core|full] [context=full|lean]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
---

# masterspec-derive — породить слой

Route-скилл: бизнес-запрос/требования → слой артефактов. Читай kernel-справочник (`../masterspec/meta_model.md`, `../masterspec/references/layer-discipline.md`, `../masterspec/references/artifact-routing.md`) и паттерны (`../masterspec/references/patterns/`).

## Параметры
- `<factory-slug>` — обязателен: kebab-case имя фабрики; идёт в поле `factory:` фронтматтера всех артефактов. Раскладка плоская — один корень `masterspec/` на проект (мета-модель §3).
- `layer=req` — вход: бизнес-запрос (из `_input/` или текста пользователя). Если у фабрики есть код — дополнительно агрегат `explore`. Выход: `01-requirements/`.
- `layer=spec` — вход: согласованный слой требований. Выход: `02-specifications/` (контракт и физмодель рождаются здесь).
- `pass=linear` (дефолт) — по одному элементу, человек контролирует каждый шаг. `pass=parallel` — независимые элементы разом субагентами, человек на финальной вычитке. parallel — явный выбор аналитика.
- `verify=core` (дефолт) — дешёвое ядро осей; `verify=full` — все оси на слое и критичных элементах.
- `context=full` (дефолт) / `context=lean` — изоляция контекста оркестратора (`patterns/context-isolation.md`). В `lean` оркестратор сам не читает мета-модель/research/артефакты, а делегирует planner-субагенту (раскладывает план и фокус-наборы в `.work/<run-id>/`), `gen` и `verify`-субагентам; держит в контексте только план, пути и сводки. Для моделей с ограниченным контекстом (рост контекста не зависит от размера фабрики).

## Метод
> **В `context=lean`** шаги ниже делегируются по `patterns/context-isolation.md`: planner-субагент раскладывает план и фокус-наборы в `.work/<run-id>/`, оркестратор вызывает `gen` по путям (не читая содержимое), `verify` и приёмщик — субагенты с файл-отчётом. По завершении прогона (после согласования) `.work/<run-id>/` ОБЯЗАТЕЛЬНО удаляется — фокус-наборы содержат срезы содержания фабрики; `route-run` сохраняется отдельно. В `context=full` оркестратор может выполнять чтение сам (как описано ниже).

0. **Инициализация (если фабрики ещё нет).** Создай скелет `masterspec/` по полной раскладке (`../masterspec/meta_model.md §3`): подпапки `01-requirements/{01-system,02-functions,03-nfr,04-rules,05-landscape,06-data-model,07-dictionaries,08-test-cases}`, `02-specifications/{01-components,02-scenarios,03-algorithms,04-apis/{internal,external},05-data,06-diagrams,07-load-profiles,08-test-cases,09-ui-views}`, `03-codemap/{01-component-maps,02-scenario-traces,03-data-maps}`, `04-decisions/`, `changes/`. Заведи `00-masterspec-index.md` (шаблон `tpl-masterspec-index`) и пустой `00-glossary.md`.
1. **Контекст.** Если у фабрики есть код — собери агрегат через `explore` (target=factory-spec). Если кода нет (фабрика с нуля или только слой требований) — `explore` НЕ нужен: контекст берётся из бизнес-запроса; обратный индекс ссылок при необходимости строится `Grep` по `-> ` в уже созданных артефактах.
2. **Состав и порядок слоя.** layer=req: `as` → черновой `cdm` (сущности) → `rules` → `fn` (use-case по cdm и rules) → вернись к `cdm` и заполни «Состояния и переходы» (по событиям из fn) → `nfr` → `dict` (если есть) → `tc-acc`. Глоссарий пополняй по ходу (каждый новый термин). layer=spec: `cmp` (cap-*) → `scn` → `alg` → `api`/`data` → `cd`/`lp` → (`ui-view` + `nav` — для систем с пользовательским интерфейсом) → `tc-int`. Это «route внутри слоя»; цикл cdm↔fn разрывается итеративно (черновой cdm без состояний → fn → состояния cdm).
3. **На каждый элемент — узел.** Оцени decision-worthiness (`patterns/decision-node.md`): есть реальная развилка (модель данных, набор сущностей, для spec — форма контракта/алгоритм) → **узел-РЕШЕНИЕ** (2-3 варианта → выбор → запись `adr-`/`dr-`). Нет → **узел-ИСПОЛНЕНИЕ** (`patterns/element-workflow.md`): планировщик → `gen type=<элемент>` (изолир. фокус-набор) → приёмщик.
4. **Параллельность.** pass=parallel: независимые элементы (несколько fn) — батч `gen`-субагентов; приёмщик сводит редакции. pass=linear: по одному.
5. **Дозапрос.** gen не хватило фокус-набора — явный запрос «не хватает X», по единому маршруту (`patterns/context-isolation.md §Дозапрос`): нужен факт из КОДА → `explore`; нужен срез ДОКУМЕНТА/артефакта (в lean) → `planner` дописывает `.focus`; нет ни там, ни там → открытый вопрос человеку. ≤2 раунда, потом человек. Не выдумывать.
6. **Вычитка.** `verify scope=<layer>` (preset по `verify=`). Негатив-ось (O5) — отдельным проверяющим. Критерий: scope=req → spec_ready; scope=spec → codegen_ready (`patterns/verification-axes.md`).
7. **route-run.** `route-run-<ts>.md` (шаблон `../masterspec/templates/tpl-route-run.md`; в корне фабрики при генерации с нуля): вход · pass · по элементам (дозапросы/оси/итерации) · метрики · открытые вопросы · кто принял.
8. **Индекс.** После генерации слоя перестрой `00-masterspec-index.md` полной перегенерацией по `../masterspec/references/index-canonical.md` — чтобы он отражал созданные артефакты (§3–§6 по реальным файлам, §1/§7 сохраняются дословно).
9. **Карантин и hard-gate** (`patterns/enforcement.md`). При генерации с нуля черновики пишутся прямо в `01-`/`02-` со `status: draft` (это и есть карантин — статус, не отдельная папка). Согласование: человек ревьюит (merge PR) и переводит `status: draft → actual`, затем перестраивает индекс (полная перегенерация подхватит `actual`-маркеры). Агент сам actual не ставит.

> **Без субагентов (`Task`):** если механизма параллельных субагентов нет — выполняй элементы последовательно, по одному; результат тот же, дольше по времени.

## Выход
- слой (`01-requirements/` или `02-specifications/`), `status: draft`;
- `00-glossary.md`, `00-masterspec-index.md`;
- `route-run-<ts>.md` с отчуждаемыми метриками;
- открытые вопросы человеку.

## Чек перед отдачей
Общий чек-лист артефакта — `../masterspec/SKILL.md §3`. Для layer=spec вычитка обязана пройти O0 single-source и O6/O7 (`patterns/verification-axes.md`).
