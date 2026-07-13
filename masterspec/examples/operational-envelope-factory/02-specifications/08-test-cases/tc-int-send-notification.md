---
type: test-integration
slug: tc-int-send-notification
factory: oe-example
status: draft
criticality: medium
updated: 2026-07-13
---
# Интеграционный тест: отправка и отказ канала уведомлений

## Проверяет
- Сценарий и его канонический OE-маппинг: -> scn-send-notification
- Функция: -> fn-send-notification
- Путь: основной и отказ внешнего канала
- Грани живой эксплуатации: -> fn-send-notification/OE-EVIDENCE, -> fn-send-notification/OE-RESILIENCE
- Строки каталога: -> tc-flt-send-notification/FLT-000,
  -> tc-flt-send-notification/FLT-001, -> tc-flt-send-notification/FLT-002

## Fidelity эксплуатационной проверки
- Профиль: production-like; внешний live-e2e выполняется приёмочным тестом.
- Fidelity: production-like
- Что реально проверяется: основной путь, недоступность и техническая ошибка канала.
- Residual risk: конечный транспорт проверяется отдельно live-e2e.

## Предварительные действия
- Настройте внешний канал на управляемые ответы success, unavailable и tech-error.

## Шаги выполнения
1. **Действие:** Отправьте валидное уведомление при доступном внешнем канале.
   **Тестовые данные:** fixture=notification-valid; correlation-id=int-001; channel-mode=success
   **Ожидаемый результат:**
   - Сценарий фиксирует принятие, затем конечную доставку без повторной отправки.

2. **Действие:** Повторите отправку при недоступном и технически отказавшем канале.
   **Тестовые данные:** correlation-id=int-002; channel-mode=unavailable,tech-error
   **Ожидаемый результат:**
   - История сохраняет статус «ожидает повтора» и специфицированную причину отказа.

3. **Действие:** Проверьте диагностический журнал по идентификатору операции и окну времени.
   **Тестовые данные:** correlation-id=int-002; time-window=5 минут; expected-event=delivery-retry-scheduled
   **Ожидаемый результат:**
   - Найдена ровно одна запись `delivery-retry-scheduled` со статусом `pending` и причиной отказа канала.

## Проверяемые условия
- Внешнее принятие не выдается за конечную доставку; отказ сохраняет пользовательский и логовый след.

## Связи
- Сценарий: -> scn-send-notification
- Функция: -> fn-send-notification
- API: -> api-notification-channel
- Каталог отказов: -> tc-flt-send-notification
