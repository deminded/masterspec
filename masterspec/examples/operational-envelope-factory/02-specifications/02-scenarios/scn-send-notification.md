---
type: scenario
slug: scn-send-notification
factory: oe-example
status: draft
updated: 2026-07-13
---
# Сценарий: отправить уведомление

## Последовательность шагов
1. Принять валидное задание и зафиксировать статус «принято».
2. Передать уведомление договорному каналу. -> api-notification-channel
3. Зафиксировать конечный статус канала в истории заказчика.

## Реализация контракта живой эксплуатации
| Грань | Владелец |
|---|---|
| -> fn-send-notification/OE-LOAD | -> lp-send-notification |
| -> fn-send-notification/OE-INPUT | этот сценарий |
| -> fn-send-notification/OE-EVIDENCE | этот сценарий |
| -> fn-send-notification/OE-SOURCES | этот сценарий |
| -> fn-send-notification/OE-SECURITY | этот сценарий |
| -> fn-send-notification/OE-RESILIENCE | этот сценарий |
| -> fn-send-notification/OE-DELIVERY | -> api-notification-channel |

## Проверка
- Интеграционный тест: -> tc-int-send-notification
