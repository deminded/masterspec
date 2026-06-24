# Пример заполненного change.md

Пример для ориентации по формату. **Не копируй целиком** — используй как шаблон структуры.

---

```markdown
# Change: add-retry-for-failed-delivery

> **Статус**: На согласовании
>
> **Дата создания**: 2026-04-23
>
> **Автор**: Иванов И. И.
>
> **Версия**: 1.0
>
> **Фабрика**: notifier
>
> **Целевой индекс**: masterspec/00-masterspec-index.md

---

## 1. Мотивация

### 1.1. Цель изменения
Добавить механизм ретраев для неудачных отправок уведомлений, чтобы транзиентные отказы внешних каналов не приводили к потере сообщения.

### 1.2. Инициатор
Инцидент INC-2026-0342 (24% сообщений потерялись при отказе SMS-шлюза 2026-04-15).

### 1.3. Приоритет
высокий

### 1.4. Слой(и) изменения

- [x] требования (`01-requirements/`)
- [x] спецификации (`02-specifications/`)
- [ ] кодовая база (`03-codemap/`)
- [x] решения (`04-decisions/`)

### 1.5. Контекст
- Инцидент: INC-2026-0342
- ADR (новый): `adr-backoff-policy`

---

## 2. Затронутые артефакты

### 2.1. MODIFIED (diff-правки в §4)

| # | Тип | Slug | Путь | Что меняется |
|---|-----|------|------|---------------|
| 1 | fn | fn-send-notification | 01-requirements/02-functions/sending/fn-send-notification.md | AC-03: добавить поведение при таймауте |
| 2 | cmp | cmp-delivery-router | 02-specifications/01-components/cmp-delivery-router.md | Новая cap-retry в разделе Возможности |

### 2.2. ADDED (новые артефакты, файлы в `new/`)

| # | Тип | Slug | Путь (куда будет положен) | Шаблон |
|---|-----|------|---------------------------|--------|
| 1 | scenario | scn-retry-flow | 02-specifications/02-scenarios/scn-retry-flow.md | tpl-scenario.md |
| 2 | adr | adr-backoff-policy | 04-decisions/adr-backoff-policy.md | tpl-adr.md |

### 2.3. REMOVED

Нет изменений.

---

## 3. Обратная совместимость

да — поведение расширяется, не ломает существующих потребителей.

---

## 4. MODIFIED — diff-блоки

### 4.1. fn-send-notification — уточнение AC-03

**Файл**: `01-requirements/02-functions/sending/fn-send-notification.md`
**Раздел**: `## Критерии приёмки`
**Тип правки**: modify-bullet

ДО:
\`\`\`
- AC-03. Система возвращает статус доставки в течение 30 секунд.
\`\`\`

ПОСЛЕ:
\`\`\`
- AC-03. Система возвращает статус доставки в течение 30 секунд.
  При таймауте внешнего канала система ДОЛЖНА выполнить ретрай до 3 раз
  с нарастающим backoff. Финальный статус возвращается после исчерпания
  попыток или успешной доставки.
\`\`\`

### 4.2. cmp-delivery-router — новая возможность cap-retry

**Файл**: `02-specifications/01-components/cmp-delivery-router.md`
**Раздел**: `## Возможности`
**Тип правки**: add-subsection

ПОСЛЕ:
\`\`\`
### cap-retry — ретрай неудачных отправок

**Вход**: неуспешный исход отправки (-> scn-retry-flow).

**Поведение**: повторить отправку через тот же канал с backoff-стратегией.

**Ограничения**: максимум 3 попытки; backoff 1s/5s/15s.

**Ошибки**: `retry-budget-exhausted` при исчерпании попыток.
\`\`\`

---

## 5. ADDED — новые файлы

- `new/scn-retry-flow.md` — сценарий ретрая по cap-retry компонента cmp-delivery-router.
- `new/adr-backoff-policy.md` — решение о стратегии backoff (1s/5s/15s, экспоненциальная) с обоснованием.

---

## 6. REMOVED — артефакты к удалению

Нет изменений.

---

## 7. Влияние на направление ссылок

- Новая ссылка: `fn-send-notification` AC-03 → никакой (изменение AC внутри того же артефакта).
- Новая ссылка: `scn-retry-flow` → `cmp-delivery-router/cap-retry` (в пределах слоя спецификаций, OK).
- Новая ссылка: `cmp-delivery-router/cap-retry` → `rules-retry-budget` (если правило существует — проверить; если нет — добавить в отдельный change).

Обратных ссылок не появляется.

---

## 8. Критерии приёмки изменения

- [ ] После `apply-change` запущен `masterspec reindex`; в `masterspec/00-masterspec-index.md` появились строки для `scn-retry-flow` (§4.2) и `adr-backoff-policy` (§6).
- [ ] Нет обратных ссылок.
- [ ] Новые slug'и уникальны.
- [ ] `new/scn-retry-flow.md`, `new/adr-backoff-policy.md` — `status: draft`, `updated: 2026-04-23`.
- [ ] В `fn-send-notification.md` поле `updated:` обновлено на `2026-04-23`.
- [ ] `tc-acc-send-notification` проверен: покрывает ли AC-03 с ретраями. Если нет — отдельный change на `tc-acc-`.
```
