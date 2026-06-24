---
type: component-map
slug: cmap-<component-slug>
factory: <factory-slug>
status: draft            # draft / actual / deprecated
updated: YYYY-MM-DD
generated: true          # этот файл генерируется агентом
---
# Code Map: <название компонента>

<!-- СЛОЙ: кодовая база. Маппинг компонента из спецификации на кодовую базу.
     Генерируется агентом. Перечисляются ТОЛЬКО навигационно значимые точки
     (entry points, реализация возможностей, data access), а НЕ все классы.
     В этом слое ссылки на код (file:line) — обязательны.
     Связи указывайте в формате -> slug. -->

## Расположение
- **Репозиторий:** <repo-name>
- **Корневой путь:** `<path/to/component/>`
- **Язык:** <Kotlin, Java, Go...>
- **Пакет / namespace:** `<com.example.router>`

## Entry Points

<!-- Точки входа: контроллеры, listeners, handlers, main. -->

| Entry Point | Kind | Файл | Описание |
|---|---|---|---|
| | handler / listener / controller / job | `path/file:line` | |

## Маппинг возможностей (capabilities → код)

<!-- Одна секция на каждую возможность из cmp-<slug>.
     Формат заголовка: ### cap-<name> (из -> cmp-<slug>). -->

### cap-<name>
- **Основной модуль / класс:** `path/file:line`
- **Ключевые методы:**
  - `ClassName.methodName()` — `path/file:line` — <что делает>
  - `ClassName.methodName()` — `path/file:line` — <что делает>
- **Вспомогательные code units (если важны):** `path/file:line`

### cap-<name>
- **Основной модуль / класс:** `path/file:line`
- **Ключевые методы:**
  - `ClassName.methodName()` — `path/file:line` — <что делает>

## Data Access

<!-- Через какие классы компонент обращается к данным. -->

| Сущность / таблица | Тип доступа | Code Unit | Файл |
|---|---|---|---|
| | repository / dao / client / cache | | `path/file:line` |

## Внешние вызовы

<!-- Клиенты к другим компонентам и внешним системам. -->

| Куда | Тип | Code Unit | Файл |
|---|---|---|---|
| -> cmp-... / external | HTTP / gRPC / Kafka / ... | | `path/file:line` |

## Конфигурация

<!-- Ключевые конфиг-файлы и переменные окружения. -->

| Параметр | Файл / env | Назначение |
|---|---|---|
| | | |

## Связи
- Компонент (спецификация): -> cmp-...
- Сценарии: -> scn-...
- API: -> api-...
- Scenario traces: -> trace-...
