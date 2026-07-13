---
type: test-acceptance
slug: tc-acc-send-notification-live
factory: notification-factory
status: draft
criticality: high
owner: Команда коммуникаций
updated: 2026-07-13
---
# Приёмочный тест: реальный контур транзакционного уведомления

## Проверяет
- Функция: -> fn-send-notification
- AC: AC-01, AC-02, AC-03, AC-04, AC-05
- Грани живой эксплуатации: -> fn-send-notification/OE-LOAD,
  -> fn-send-notification/OE-INPUT, -> fn-send-notification/OE-EVIDENCE,
  -> fn-send-notification/OE-SOURCES, -> fn-send-notification/OE-SECURITY,
  -> fn-send-notification/OE-RESILIENCE, -> fn-send-notification/OE-DELIVERY

## Репрезентативность и граница наблюдения
- Fixture / среда и provenance: обезличенные CRM v3/billing v2 payloads и счётчики 2026-Q2.
- Fidelity: production-like для входа/нагрузки/отказов; live-e2e для конечного результата.
- Граница наблюдения: содержание у получателя и долговечная история заказчика.
- Residual risk: N/A — проверка включает реального договорного провайдера и поздний статус.

## Предварительные действия
- Зарегистрируйте CRM и billing как разрешённых отправителей.
- Подготовьте договорного тестового получателя и обезличенный peak-набор.

## Шаги выполнения
1. **Действие:** Отправьте образцы CRM и billing, затем задание неизвестного отправителя.
   **Тестовые данные:** fixtures=crm-v3-unicode,billing-v2-empty,unknown-source; correlation-id=live-001
   **Ожидаемый результат:**
   - Два разрешённых задания приняты без искажения, неизвестный источник отклонён с кодом `SOURCE_DENIED`.

2. **Действие:** Отправьте peak-набор и backlog.
   **Тестовые данные:** profile=2026-Q2-peak; backlog=40000; correlation-prefix=live-load
   **Ожидаемый результат:**
   - Все принятые задания имеют уникальный исход без потерь и технических дублей.

3. **Действие:** Проверьте доставку у получателя и историю заказчика.
   **Тестовые данные:** correlation-id=live-001; time-window=15 минут
   **Ожидаемый результат:**
   - История различает принятие и конечную доставку, а получатель видит исходное содержание.

4. **Действие:** Инициируйте документированный поздний отказ внешнего канала.
   **Тестовые данные:** correlation-id=live-002; channel-mode=late-reject
   **Ожидаемый результат:**
   - История содержит конечный статус «отказ» с причиной, а статус «доставлено» отсутствует.

5. **Действие:** Проверьте диагностический журнал по идентификатору операции и окну времени.
   **Тестовые данные:** correlation-id=live-002; time-window=15 минут; expected-event=delivery-late-reject
   **Ожидаемый результат:**
   - Найдена ровно одна запись `delivery-late-reject` с конечным статусом `rejected`.

## Постусловия
- Каждое принятое задание имеет временную шкалу и последний подтверждённый исход.

## Связи
- Функция: -> fn-send-notification
- Справочники: -> dict-channels
- Концептуальная модель: -> cdm-notifications
