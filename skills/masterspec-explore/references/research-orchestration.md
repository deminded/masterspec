# Оркестрация исследования (masterspec)

Инструкция для лид-агента: как провести structured research кодовой базы под фабрику (картирование новой или зоны изменения), чтобы собрать достаточно данных для заполнения артефактов трёх слоёв (требования / спецификации / кодовая база).

Правила написаны так, чтобы их могла применять слабая модель (окно 200к): числа заданы явно, промпты — в [research-roles.md](research-roles.md) как готовые шаблоны, рекурсия субагентов запрещена.

---

## 1. Вход

Лид-агент передаёт:
- **target**: `factory-spec` (картируем всю фабрику под её описание) или `factory-change` (картируем зону изменения)
- **factory**: slug фабрики (kebab-case) — определяет корень `masterspec/...`
- **roots**: корневые пути исходного кода (для монорепо — путь модуля; для одного корня — `.`)
- **anchor** (только для `factory-change`): пути/символы/slug'и из change, попадающие в скоуп
- **thoroughness** (опционально): `quick` (default) / `medium`

Без `target`, `factory` и `roots` — не запускаемся.

---

## 2. Классификация размера

Быстрые команды:

```bash
find . -type f \( -name "*.java" -o -name "*.kt" -o -name "*.py" -o -name "*.go" -o -name "*.ts" -o -name "*.js" -o -name "*.rs" -o -name "*.rb" -o -name "*.cs" \) \
  | grep -v -E "(node_modules|build|dist|target|\.git)" | wc -l
```

| Уровень | Критерий | Кол-во субагентов |
|---------|----------|-------------------|
| **Малый** | <50 файлов кода ИЛИ 1 модуль/пакет | **2** параллельных субагента |
| **Средний** | 50–500 файлов ИЛИ 2–10 модулей | **2–3** параллельных субагента |
| **Крупный** | >500 файлов ИЛИ multi-module / multi-repo | **3–5** параллельных субагентов |

> **Субагенты обязательны всегда, когда tool запуска субагента доступен.** Лид не должен читать исходный код в своё окно — ломается дедупликация и рассинхронизируется YAML-контракт. Вариант «0 агентов» допустим только как fallback (§ 8).

Границы нестрогие: 200 файлов без внутренних границ = Средний (2 агента); 80 файлов с 5 bounded-context = Средний.

---

## 3. Оси декомпозиции

### 3.1. `target=factory-spec` — ось «по слоям мета-модели»

Каталог ролей для описания новой фабрики (или обновления картирования существующей). Полный список — [research-roles.md § Роли для factory-spec](research-roles.md).

| Роль | Слой | Целевые артефакты |
|------|------|-------------------|
| `requirements-scope` | Требования | `fn-*`, `nfr-*`, `rules-*`, `cdm-*`, `dict-*` |
| `components-scope` | Спецификации | `cmp-*` (с разделами `cap-*`) |
| `scenarios-scope` | Спецификации | `scn-*`, `alg-*` |
| `data-scope` | Спецификации | `data-*`, `api-*` (internal/external) |
| `codemap-scope` | Кодовая база | `repo-map`, `cmap-*`, `trace-*`, `dmap-*` |

**Группировка по размеру проекта**:

| Размер | Группы (каждая = один субагент) |
|--------|---------------------------------|
| Малый (2 агента) | [requirements-scope + components-scope], [scenarios-scope + data-scope + codemap-scope] |
| Средний (3 агента) | [requirements-scope + components-scope], [scenarios-scope + data-scope], [codemap-scope] |
| Крупный (5 агентов) | [requirements-scope], [components-scope], [scenarios-scope], [data-scope], [codemap-scope] |

### 3.2. `target=factory-change` — ось «по зоне изменения»

Каталог ролей для картирования зоны change.md. Работаем в пределах `anchor_paths` и смежных файлов.

| Роль | Что картируем |
|------|---------------|
| `requirements-scope` | Затронутые `fn-*`/`nfr-*`/`rules-*` — текущие AC, инварианты, правила в коде |
| `components-scope` | Затронутые `cmp-*`/`cap-*` — ответственности, границы модулей в zone |
| `scenarios-scope` | Затронутые `scn-*`/`alg-*` — текущие цепочки вызовов |
| `data-scope` | Затронутые `data-*`/`api-*` — схемы/API в zone |
| `codemap-scope` | Только если change затрагивает кодовый слой фабрики — обновление существующих `cmap-*`/`trace-*`/`dmap-*` |

**Группировка по размеру**:

| Размер | Группы |
|--------|--------|
| Малый (2 агента) | [requirements-scope + components-scope], [scenarios-scope + data-scope] |
| Средний (3 агента) | [requirements-scope], [components-scope + scenarios-scope], [data-scope] |
| Крупный (4 агента) | [requirements-scope], [components-scope], [scenarios-scope], [data-scope (+ codemap-scope при необходимости)] |

Для простых change (правка одного AC, редактирование строки таблицы) исследование кода вообще можно пропустить — пользовательский чек `Нужно ли картировать код?` на стороне `propose`.

---

## 4. Запуск

1. **Выбери роли** по `target` и размеру (таблицы выше).
2. **Для каждой группы** — один субагент. Промпт берётся из [research-roles.md](research-roles.md). Если группа — несколько ролей, склей их YAML-контракты в один промпт с пометкой `## Роли`.
3. **Запуск в одном батче** tool-вызовов — несколько вызовов tool'а запуска субагента в одном ответном сообщении. Имя tool-а и `subagent_type` — по алгоритму [invocation-contract.md § 3.1](invocation-contract.md).
4. **subagent_type**:
   - Если доступен read-only субагент (`Explore` / `explore`) — используй его.
   - Иначе — `general-purpose` / `general` с явным запретом записи в промпте (см. invocation-contract.md § 4).
5. **Thoroughness**: `quick` по умолчанию. `medium` — только если пользователь явно сказал «подробнее» и проект крупный.

---

## 5. Инвариант scope

- Каждому субагенту — **непересекающийся набор путей**. Если зоны перекрываются — укрупни задачи, уменьши число агентов.
- Зоны задаются явно в промпте (`Границы: читай только <dir/**>, <dir2/**>`). Общие пути (`src/**`) допустимы только когда модулей мало и разделение бессмысленно.
- При `target=factory-change` — зоны ограничены `anchor_paths` и их прямыми импортёрами/вызывателями.

---

## 6. Агрегация

После возврата всех YAML — один проход лид-агента:

1. **Склей поля по ролям** в единые коллекции (ключи дедупа — в [invocation-contract.md § 7](invocation-contract.md)):
   - `functions[]`, `nfrs[]`, `rules[]`, `entities[]`, `dictionaries[]` — из `requirements-scope`
   - `components[]`, `capabilities[]` — из `components-scope`
   - `scenarios[]`, `algorithms[]` — из `scenarios-scope`
   - `apis[]`, `data_schemas[]`, `openapi_specs[]`, `proto_files[]` — из `data-scope`
   - `repo_entries[]`, `component_maps[]`, `scenario_traces[]`, `data_maps[]` — из `codemap-scope`
2. **Сними дубли** по ключам из [invocation-contract.md § 7](invocation-contract.md).
3. **Сводные gaps** — объединить все `gaps[]`. Это вопросы к Этапу 2 интервью в вызывающем скилле.
4. **Проверка полноты**: для каждого слоя фабрики — есть ли хотя бы одна запись? Если слой пуст при `target=factory-spec` — gap, не отсутствие данных. См. § 6.1.

Результат возвращается в вызывающий скил в виде пути к `.research-notes.md` + краткая сводка. Сырой YAML в контекст лида не копируется.

### 6.1. Таблица «слой фабрики → коллекции агрегата»

**target=factory-spec:**

| Слой | Артефакты | Коллекции из агрегата |
|------|-----------|----------------------|
| Требования | `fn-*` | `functions[]` (name, trigger, actors, preconditions, main_flow, acceptance_criteria) |
| Требования | `nfr-*` | `nfrs[]` (category, metric, threshold) |
| Требования | `rules-*` | `rules[]` (id, statement) |
| Требования | `cdm-*` | `entities[]` (domain entities с полями без имплементации) |
| Требования | `dict-*` | `dictionaries[]` (name, values) |
| Спецификации | `cmp-*` | `components[]` (responsibility, boundaries), `capabilities[]` (component, name, contract) |
| Спецификации | `scn-*` | `scenarios[]` (trigger, components_chain, happy_path, alternatives) |
| Спецификации | `alg-*` | `algorithms[]` (steps, branches, decision_rules) |
| Спецификации | `api-*` | `apis[]` (scope=internal/external, method, path, request, response, errors, sla) |
| Спецификации | `data-*` | `data_schemas[]` (logical entities, fields, constraints) |
| Кодовая база | `repo-map` | `repo_entries[]` (root_path, stack, modules) |
| Кодовая база | `cmap-*` | `component_maps[]` (component_slug → file:line/symbol) |
| Кодовая база | `trace-*` | `scenario_traces[]` (scenario_slug → call chain) |
| Кодовая база | `dmap-*` | `data_maps[]` (entity_slug → tables/collections) |

**target=factory-change:**

| Что анализируется | Коллекции |
|-------------------|-----------|
| Текущее поведение в zone | `current_behavior.rules[]`, `current_behavior.flows[]` |
| Текущие ответственности компонентов в zone | `current_components[]` |
| Текущие схемы/API в zone | `current_apis[]`, `current_data_schemas[]` |
| Impact analysis | `callers[]`, `breaking_risk[]` |
| Подсказки для критериев приёмки change | `acceptance_hints[]` |
| Подсказки для плана миграции | `migration_hints[]` |

Если строка таблицы с коллекциями пуста — фиксируй как gap, не выдумывай.

---

## 7. Лимиты для слабой модели

- **Числа — явные**: «2 субагента», «≤15 файлов», «≤200 слов summary».
- **Промпт — копипаст** из [research-roles.md](research-roles.md), без импровизации.
- **Запуск — строго параллельно**: все вызовы tool'а запуска субагента — одним сообщением лида. См. [invocation-contract.md § 3](invocation-contract.md).
- **Рекурсия субагентов запрещена.**
- **Сырые тексты из субагентов в контекст лида не копируются.** Храни только YAML-сводки.
- **Персистентность обязательна для Среднего и Крупного**, рекомендуется для Малого. Каждый возвратный YAML сразу идёт в `.research/<role>.yaml`, итоговый агрегат — в `.research/_aggregate.yaml` и `.research-notes.md`. См. [invocation-contract.md § 8](invocation-contract.md).
- **Близко к 200к** — после записи YAML в файлы выгружай сырые выводы из контекста лида.
- **После финального артефакта** — `.research/` и `.research-notes.md` удаляются (не должны попасть в git — добавить в `.gitignore`).

---

## 8. Fallback: нет tool запуска субагента

Снижаем класс на одну ступень:
- Крупный → стратегия Среднего
- Средний → стратегия Малого

Последовательный sweep по тому же каталогу ролей: для каждой роли — прочитай её YAML-контракт из [research-roles.md](research-roles.md), пройди по указанным путям сам, заполни YAML в рабочих заметках. В конце — та же фаза агрегации.

---

## 9. Связи

- Инструменты внутри субагента — [code-analysis-priority.md](code-analysis-priority.md) (Serena → LSP → embeddings → MCP → Grep/Glob).
- Каталог ролей и YAML-контракты — [research-roles.md](research-roles.md).
- Работа с артефактами фабрики (активные changes, маршрутизация инсайтов) — [masterspec-awareness.md](masterspec-awareness.md).
- Резолв путей к этим файлам из лид-скилов — [invocation-contract.md § 1](invocation-contract.md).
