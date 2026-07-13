---
type: scenario-trace
slug: trace-send-notification
factory: oe-example
status: draft
generated: true
updated: 2026-07-13
---
# Code Trace: отправка уведомления

## Сценарий
- Спецификация: -> scn-send-notification

## Маппинг контракта живой эксплуатации
| Грань | Code/test evidence |
|---|---|
| -> fn-send-notification/OE-LOAD | `src/notify.py:run`; `tests/test_load.py` |
| -> fn-send-notification/OE-INPUT | `src/input.py:parse`; `tests/test_input.py` |
| -> fn-send-notification/OE-EVIDENCE | `src/history.py:append`; `tests/test_history.py` |
| -> fn-send-notification/OE-SOURCES | `src/auth.py:allow`; `tests/test_sources.py` |
| -> fn-send-notification/OE-SECURITY | `src/auth.py:validate`; `tests/test_security.py` |
| -> fn-send-notification/OE-RESILIENCE | `src/retry.py:run`; `tests/test_retry.py` |
| -> fn-send-notification/OE-DELIVERY | `src/channel.py:send`; `tests/test_delivery.py` |
