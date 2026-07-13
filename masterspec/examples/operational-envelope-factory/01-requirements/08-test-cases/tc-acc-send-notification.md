---
type: test-acceptance
slug: tc-acc-send-notification
factory: oe-example
status: draft
criticality: medium
updated: 2026-07-13
---
# Приёмочный тест: отправка уведомления в живом контуре

## Проверяет
- Функция: -> fn-send-notification
- AC: AC-01, AC-02, AC-03, AC-04
- Грани: -> fn-send-notification/OE-LOAD, -> fn-send-notification/OE-INPUT,
  -> fn-send-notification/OE-EVIDENCE, -> fn-send-notification/OE-SOURCES,
  -> fn-send-notification/OE-SECURITY, -> fn-send-notification/OE-RESILIENCE,
  -> fn-send-notification/OE-DELIVERY

## Репрезентативность и граница наблюдения
- Fixture: обезличенные CRM/billing payloads и масштабированный профиль 2026-Q2.
- Fidelity: production-like и live-e2e на договорном канале.
- Граница: конечный получатель и история заказчика.
- Residual risk: N/A — внешний путь включён.

## Предварительные действия
- Зарегистрируйте тестового отправителя CRM и договорного получателя.
- Подготовьте обезличенный peak-набор 2026-Q2.

## Шаги выполнения
1. **Действие:** Отправьте CRM-задание договорному получателю.
   **Тестовые данные:** fixture=crm-v3-unicode; correlation-id=oe-example-001
   **Ожидаемый результат:**
   - История заказчика содержит статус «принято» с correlation-id `oe-example-001`.

2. **Действие:** Проверьте конечный исход у получателя и в истории заказчика.
   **Тестовые данные:** correlation-id=oe-example-001; time-window=5 минут
   **Ожидаемый результат:**
   - Получатель видит исходное содержание, а история содержит конечный статус «доставлено».

## Постусловия
- Задание имеет различимые статусы принятия и конечной доставки.

## Чек-лист соответствия tc
- [x] Шаги атомарны, testData заполнены, expectedResult проверяем.
- [x] Criticality равна criticality функции.
- [x] OE-EVIDENCE проверяется на пользовательской границе.

<!-- Эта ссылка не является покрытием и должна быть удалена до скана: -> fn-ghost/OE-LOAD -->
