---
type: test-fault-catalog
slug: tc-flt-send-notification
factory: oe-example
status: draft
criticality: medium
coverage: dependent-pairs
derived_from_scenario: -> scn-send-notification
derived_from_apis: [-> api-notification-channel]
updated: 2026-07-14
---
# Каталог отказов: отправка уведомления

## Область
- Сценарий: -> scn-send-notification
- Функция: -> fn-send-notification
- API: -> api-notification-channel
- Стратегия покрытия: dependent-pairs

## Матрица отказов
| fault-id | Точка инъекции (шаг → api) | Модус | Состояние прочих | Ожидаемый результат | Источник результата | Реализуемость | TC |
|---|---|---|---|---|---|---|---|
| FLT-000 | — | happy-path | healthy | Статусы «принято» и «доставлено» различимы | -> scn-send-notification | feasible | -> tc-int-send-notification |
| FLT-001 | шаг 2 → -> api-notification-channel | unavailable | healthy | История показывает «ожидает повтора» и причину недоступности | -> fn-send-notification/OE-RESILIENCE | feasible | -> tc-int-send-notification |
| FLT-002 | шаг 2 → -> api-notification-channel | tech-error | healthy | История показывает «ожидает повтора» и техническую причину | -> fn-send-notification/OE-EVIDENCE | feasible | -> tc-int-send-notification |

## Сводка генерации
- Строк всего: 3
- Результат взят из спецификации: 3
- TC-TODO: 0
- Infeasible с причиной: 0
- Покрыто tc-int: 3
- Deferred: 0
