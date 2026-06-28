---
type: masterspec-index
factory: notification-factory
updated: 2026-04-17
---
# Индекс фабрики: notification-factory

## 1. Паспорт
- Фабрика: notification-factory (фабрика уведомлений)
- Владелец: Команда коммуникаций
- Дата создания индекса: 2026-04-13
- Статус описания: in-progress

---

## 2. Общие артефакты
 + `00-glossary.md` # Глоссарий

---

## 3. Слой требований

### 3.1. Паспорт АС/ФП
 + `01-requirements/01-system/as-notification-factory.md` # Фабрика уведомлений

### 3.2. Функции АС/ФП

#### Отправка
 + `01-requirements/02-functions/sending/fn-send-notification.md` # Отправить уведомление

#### Мониторинг
 - `01-requirements/02-functions/monitoring/fn-check-delivery-status.md` # Проверить статус доставки

### 3.3. Нефункциональные требования
 + `01-requirements/03-nfr/nfr-notification-factory.md` # Общие НФТ фабрики

### 3.4. Бизнес- и внутренние правила
 + `01-requirements/04-rules/rules-delivery.md` # Правила доставки

### 3.5. Диаграмма окружения и функциональная диаграмма
 + `01-requirements/05-landscape/context-notification-factory.md` # Диаграмма окружения
 - `01-requirements/05-landscape/fd-notification-factory.md` # Функциональная диаграмма

### 3.6. Концептуальная модель данных
 + `01-requirements/06-data-model/cdm-notifications.md` # Уведомления и каналы

### 3.7. Справочники и классификаторы
 + `01-requirements/07-dictionaries/dict-channels.md` # Каналы доставки
 - `01-requirements/07-dictionaries/dict-delivery-statuses.md` # Статусы доставки

### 3.8. Приёмочные тесты
 + `01-requirements/08-test-cases/tc-acc-send-sms-happy.md` # SMS: успешная отправка (-> fn-send-notification, AC-01)
 - `01-requirements/08-test-cases/tc-acc-send-push-unavailable-channel.md` # Push: канал недоступен (-> fn-send-notification, AC-03)

---

## 4. Слой спецификаций

### 4.1. Компоненты и их возможности

 + `02-specifications/01-components/cmp-api-gateway.md` # api-gateway
   · cap-accept-request — приём и валидация запроса на уведомление
   · cap-attach-correlation — присвоение корреляционного идентификатора

 + `02-specifications/01-components/cmp-notification-router.md` # notification-router
   · cap-route-by-channel — выбор канала доставки
   · cap-apply-retry-policy — политика повторных попыток
   · cap-track-delivery-status — учёт статуса доставки

 + `02-specifications/01-components/cmp-template-engine.md` # template-engine
   · cap-render-template — рендер текста по шаблону и параметрам

 - `02-specifications/01-components/cmp-channel-adapter-sms.md` # channel-adapter-sms
   · cap-send-sms — отправка SMS через провайдера

 ? `02-specifications/01-components/cmp-channel-adapter-push.md` # channel-adapter-push

### 4.2. Сценарии
 + `02-specifications/02-scenarios/scn-send-sms.md` # Отправка SMS-уведомления
 - `02-specifications/02-scenarios/scn-send-push.md` # Отправка push-уведомления
 ? `02-specifications/02-scenarios/scn-check-delivery.md` # Проверка статуса доставки

### 4.3. Алгоритмы
 + `02-specifications/03-algorithms/alg-channel-selection.md` # Выбор канала доставки
 - `02-specifications/03-algorithms/alg-retry-policy.md` # Политика повторных попыток

### 4.4. Внутренние API
 + `02-specifications/04-apis/internal/api-notification-router.md` # Маршрутизация уведомлений
 ? `02-specifications/04-apis/internal/api-template-engine.md` # Рендеринг шаблонов

### 4.5. Внешние API
 - `02-specifications/04-apis/external/api-sms-provider.md` # SMS-провайдер (+yaml)
 ? `02-specifications/04-apis/external/api-push-provider.md` # Push-провайдер (+yaml)

### 4.6. Схемы данных
 + `02-specifications/05-data/data-notifications.md` # Уведомления

### 4.7. Диаграммы
 + `02-specifications/06-diagrams/cd-notification-factory.md` # Компонентная диаграмма

### 4.8. Профили нагрузки
 - `02-specifications/07-load-profiles/lp-notification-factory.md` # Профиль нагрузки фабрики

### 4.9. Интеграционные тесты
 + `02-specifications/08-test-cases/tc-int-send-sms-basic.md` # SMS: базовая отправка (-> scn-send-sms)
 ? `02-specifications/08-test-cases/tc-int-send-sms-retry.md` # SMS: повторная попытка при отказе провайдера

---

## 5. Слой кодовой базы (LLD)

### 5.1. Карта репозиториев
 + `03-codemap/00-repo-map.md` # Обзор репозиториев и стека

### 5.2. Component Maps
 + `03-codemap/01-component-maps/cmap-api-gateway.md` # api-gateway -> код
 + `03-codemap/01-component-maps/cmap-notification-router.md` # notification-router -> код
 + `03-codemap/01-component-maps/cmap-template-engine.md` # template-engine -> код
 - `03-codemap/01-component-maps/cmap-channel-adapter-sms.md` # channel-adapter-sms -> код
 ? `03-codemap/01-component-maps/cmap-channel-adapter-push.md` # channel-adapter-push -> код

### 5.3. Scenario Traces
 + `03-codemap/02-scenario-traces/trace-send-sms.md` # scn-send-sms -> цепочка вызовов
 ? `03-codemap/02-scenario-traces/trace-send-push.md` # scn-send-push -> цепочка вызовов
 ? `03-codemap/02-scenario-traces/trace-check-delivery.md` # scn-check-delivery -> цепочка вызовов

### 5.4. Data Maps
 + `03-codemap/03-data-maps/dmap-notifications.md` # Уведомления -> таблицы/ORM

---

## 6. Решения (ADR)
 + `04-decisions/adr-001-separate-channel-adapters.md` # Адаптеры каналов как отдельные сервисы
 + `04-decisions/adr-002-async-delivery.md` # Асинхронная доставка через очередь

---

## 7. Белые пятна и открытые вопросы
- Не описан компонент `channel-adapter-push` — ждём решения по провайдеру push-уведомлений
- Не определён контракт с SMS-провайдером: запрошена документация у вендора
- Профиль нагрузки в черновике — нет данных по пиковым значениям
- Code map для channel-adapter-sms неполный — нет доступа к репо адаптера
- Справочник статусов доставки — ждём согласования с бизнесом по гранулярности

---

### Легенда
 + done — файл создан, содержание актуально
 - draft — файл создан, содержание неполное
 ? planned — артефакт запланирован (заявлен в change ADDED или в §7), файла ещё нет. В §3–6 reindex ставит только +/− по реально существующим файлам; ? сюда не попадает.
 · (точка) — возможность внутри компонента, не отдельный файл
