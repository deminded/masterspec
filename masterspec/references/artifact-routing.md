# Маршрутизация артефактов: тип → шаблон → путь → slug

Справочник используют `evolve` (при создании change в `changes/<name>/new/`), `apply-change` (при копировании new/ в целевые директории фабрики), `derive` и `recover`.

---

## 1. Таблица маршрутизации

| Тип (`type:` во фронтматтере) | Шаблон | Путь в фабрике | Префикс slug |
|---|---|---|---|
| `masterspec-index` | `tpl-masterspec-index.md` | `00-masterspec-index.md` | — |
| `glossary` | `tpl-glossary.md` | `00-glossary.md` | — |
| `passport-as` / `as` | `tpl-passport-as.md` | `01-requirements/01-system/` | `as-` |
| `function` / `fn` | `tpl-function-as.md` | `01-requirements/02-functions/[<block>/]` | `fn-` |
| `nfr` | `tpl-nfr.md` | `01-requirements/03-nfr/` | `nfr-` |
| `rules` | `tpl-rules.md` | `01-requirements/04-rules/` | `rules-` |
| `context-diagram` / `context` | `tpl-context-diagram.md` | `01-requirements/05-landscape/` | `context-` |
| `func-diagram` / `fd` | `tpl-func-diagram.md` | `01-requirements/05-landscape/` | `fd-` |
| `conceptual-data-model` / `cdm` | `tpl-conceptual-data-model.md` | `01-requirements/06-data-model/` | `cdm-` |
| `dictionary` / `dict` | `tpl-dictionary.md` | `01-requirements/07-dictionaries/` | `dict-` |
| `test-acceptance` / `tc-acc` | `tpl-test-acceptance.md` | `01-requirements/08-test-cases/` | `tc-acc-` |
| `usage-contract` / `uc` | `tpl-usage-contract.md` | `01-requirements/09-public-contract/` | `uc-` (`generated`, проекция `expose`) |
| `component` / `cmp` | `tpl-component.md` | `02-specifications/01-components/` | `cmp-` (разделы `cap-`) |
| `scenario` / `scn` | `tpl-scenario.md` | `02-specifications/02-scenarios/` | `scn-` |
| `algorithm` / `alg` | `tpl-algorithm.md` | `02-specifications/03-algorithms/` | `alg-` |
| `api` (внутренний) | `tpl-api.md` | `02-specifications/04-apis/internal/` | `api-` |
| `api` (внешний) | `tpl-api.md` | `02-specifications/04-apis/external/` | `api-` |
| `data-schema` / `data` | `tpl-data-schema.md` | `02-specifications/05-data/` | `data-` |
| `component-diagram` / `cd` | `tpl-component-diagram.md` | `02-specifications/06-diagrams/` | `cd-` |
| `nav` | `tpl-nav.md` | `02-specifications/06-diagrams/` | `nav-` |
| `load-profile` / `lp` | `tpl-load-profile.md` | `02-specifications/07-load-profiles/` | `lp-` |
| `test-integration` / `tc-int` | `tpl-test-integration.md` | `02-specifications/08-test-cases/` | `tc-int-` |
| `test-fault-catalog` / `tc-flt` | `tpl-test-fault-catalog.md` | `02-specifications/08-test-cases/` | `tc-flt-` |
| `ui-view` | `tpl-ui-view.md` | `02-specifications/09-ui-views/` | `ui-view-` |
| `repo-map` | `tpl-repo-map.md` | `03-codemap/00-repo-map.md` | — |
| `component-map` / `cmap` | `tpl-component-map.md` | `03-codemap/01-component-maps/` | `cmap-` |
| `scenario-trace` / `trace` | `tpl-scenario-trace.md` | `03-codemap/02-scenario-traces/` | `trace-` |
| `data-map` / `dmap` | `tpl-data-map.md` | `03-codemap/03-data-maps/` | `dmap-` |
| `adr` | `tpl-adr.md` | `04-decisions/` | `adr-` |
| `decision-record` / `dr` | `tpl-dr.md` | рядом с артефактом-владельцем (на ЕГО слое: 01-/02-) | `dr-` |

`OE-*` не маршрутизируется и не получает `type:`/отдельный файл: это обязательные стабильные
подразделы external-I/O `fn-`; internal-only `fn-` содержит одну N/A-строку без подразделов.
Внутренняя ссылка имеет вид `-> fn-<slug>/OE-<ID>` и разрешается в файл владельца
`fn-<slug>.md`. Не путать с `usage-contract` (`uc-`): `uc-` — генерируемая публичная проекция
библиотеки, OE — исходный пофункциональный контракт реальной эксплуатации любой фабрики.

---

## 2. Уточняющие поля фронтматтера

- **`block:`** для `function` — имя функционального блока, определяет вложенную поддиректорию в `01-requirements/02-functions/`. Если отсутствует — файл кладётся в корень `01-requirements/02-functions/`.
- **`scope:`** для `api` — значения `internal` | `external`. Определяет выбор между `internal/` и `external/` в пути.
- **`generated: true`** — обязательно для всех артефактов кодового слоя (`cmap-`, `trace-`, `dmap-`, `repo-map`).
- **`immutable: true | false`** для `rules` и `nfr` — фиксирует, пересматривается ли правило/НФТ фабрикой. `true` — внешнее обязательство (регуляторка, контракт, ключевой инвариант), противоречащее требование блокирует (CONFLICT); `false` — обычное правило, противоречащее требование инициирует эволюцию (EVOLUTION). Дефолт при отсутствии — `false`. Подробнее — `meta_model.md § 6.2.3` и `§ 6.2.4`.

---

## 3. Обязательные поля YAML-фронтматтера

Все артефакты (кроме index и glossary):

```yaml
---
type: <из таблицы>
slug: <префикс>-<kebab-case>
factory: <slug-фабрики>
status: draft | actual | deprecated
updated: YYYY-MM-DD
---
```

Для кодового слоя добавить `generated: true`. Для `function` — опционально `block: <имя-блока>`. Для `api` — `scope: internal | external`.
Для `function`, `test-acceptance`, `test-integration`, `test-fault-catalog` обязательно
`criticality: high | medium | low`; веса покрытия — `5 | 3 | 1`.

---

## 4. Имя файла

Имя файла = slug. Расширение — `.md`. Исключения:
- `00-masterspec-index.md` — фиксированное имя в корне фабрики;
- `00-glossary.md` — фиксированное имя в корне фабрики;
- `00-repo-map.md` — фиксированное имя в `03-codemap/`.
