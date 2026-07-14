---
type: api
slug: api-notification-channel
scope: external
factory: oe-example
status: draft
updated: 2026-07-14
sidecar_format: asyncapi-2.x
sidecar: api-notification-channel.asyncapi.yaml
contract_origin: authored
---
# API: канал уведомлений

<!-- schema-first: структура контракта (каналы, операции, payload) живёт в сайдкаре.
     Здесь — только то, чего в AsyncAPI нет. -->

## Тип API
external-async

## Назначение
Доставка уведомлений абоненту через внешний канал и приём подтверждений доставки.

## Операции / события — назначение
| operationId (из сайдкара) | Направление | Назначение |
|---|---|---|
| publishNotification | produce | отдать уведомление во внешний канал |
| consumeDeliveryReceipt | consume | принять подтверждение и снять конечный статус доставки |

## Business-reject codes
- **Business-reject codes:** N/A — контракт канала не содержит синхронных бизнес-отказов

## Подтверждения
Transport ack означает только принятие; конечный статус означает доставку. Основание:
-> fn-send-notification/OE-DELIVERY.
