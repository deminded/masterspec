---
type: test-fault-catalog
slug: tc-flt-<scenario-slug>
factory: <factory-slug>
status: draft            # actual только без TC-TODO и непокрытых feasible-строк
criticality: <high | medium | low>
owner: <team or person>
coverage: <single-fault | dependent-pairs | pairwise>
derived_from_scenario: -> scn-<slug>
derived_from_apis: [-> api-<slug>]
updated: YYYY-MM-DD
---
# Каталог отказов: <сценарий>

<!-- СЛОЙ: спецификации. Один каталог на один scn с внешними вызовами.
     Детерминированная основа — точки вызова scn + модусы api; результат только из явной
     ветки scn/alg/api, иначе TC-TODO. Criticality задаёт минимум глубины:
     low=single-fault, medium=dependent-pairs, high=pairwise. -->

## Область
- Сценарий: -> scn-...
- Функция: -> fn-...
- API: -> api-...
- Стратегия покрытия: single-fault / dependent-pairs / pairwise

## Матрица отказов
<!-- Для каждой точки внешнего вызова обязательны unavailable и tech-error; business-reject —
     по одному на каждый реально описанный business-код API. FLT-000 — happy path.
     `TC` содержит -> tc-int-* либо `DEFERRED — <владелец, причина, срок>`; для codegen_ready
     deferred и TC-TODO блокируют. -->
| fault-id | Точка инъекции (шаг → api) | Модус | Состояние прочих | Ожидаемый результат | Источник результата | Реализуемость | TC |
|---|---|---|---|---|---|---|---|
| FLT-000 | — | happy-path | healthy | <результат основного пути> | -> scn-... | feasible | -> tc-int-... |
| FLT-001 | шаг <N> → -> api-... | unavailable | healthy | <точный внешний и OE-EVIDENCE исход> | -> scn-... | feasible | -> tc-int-... |
| FLT-002 | шаг <N> → -> api-... | tech-error | healthy | <!-- TC-TODO: обработка не специфицирована --> | — | feasible | DEFERRED — <владелец, причина, срок> |

## Сводка генерации
- Строк всего:
- Результат взят из спецификации:
- TC-TODO:
- Infeasible с причиной:
- Покрыто tc-int:
- Deferred:

## Чек-лист O_T
- [ ] O_T1: каждая точка `scn → api` имеет unavailable, tech-error и все заданные business-reject.
- [ ] O_T2: нет одинакового состояния с разными результатами (unique hit policy).
- [ ] O_T3: стратегия соответствует criticality; infeasible/deferred имеют предметную причину.
- [ ] O_T4: каждая строка резолвится в существующие шаг scn и api.
- [ ] O_T5: `derived_from_*` совпадает с текущими источниками; после их изменения каталог обновлён.
- [ ] O_T6: каждая feasible-строка связана с `tc-int-*`; TC-TODO/deferred блокируют codegen_ready.

## Связи
- Сценарий: -> scn-...
- Функция: -> fn-...
- API: -> api-...
- Интеграционные тесты: -> tc-int-...
