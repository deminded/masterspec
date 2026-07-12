# Внешние guardrails (корпоративные правила поверх kernel)

## Зачем
Корпоративные нормы (архитектурные требования, глоссарий, безопасность, API-стандарты) разноуровневы по месту применения и по источнику и НЕ входят в masterspec: kernel даёт только механизм их подключения и применения. Пакеты подкладываются per-project.

## Пакет
Каталог вне masterspec:
```
<pack>/
  manifest.yaml        # id, source, version, owner, rules[] с селекторами
  rules/<rule-id>.md   # карточки: statement, rationale (кратко), conformance_checklist
                       # (пункты с пометкой machine|llm), anti_patterns, criticality
```
`source`: universal | corporate | domain | factory. При конфликте правил выигрывает более специфичный источник (factory > domain > corporate > universal); конфликт ФИКСИРУЕТСЯ в route-run как дефект пакетов, не глотается.

Пакет собирается из сырого корпоративного документа скиллом `masterspec-pack` (документ → manifest + карточки по этой схеме); подключение пути к фабрике — там же.

## Подключение (per-project, файлом)
В корне фабрики `masterspec-config.yaml`:
```yaml
guardrail_packs:
  - path: ../corp-guardrails
  - path: /opt/packs/rbre-requirements-intake
```
Параметр скиллов `guardrails=auto|off|<paths>`: `auto` (дефолт) — из конфига фабрики; файла нет → пусто, не ошибка. Поставка через MCP — возможное расширение; интерфейс пакета (резолвимый источник карточек) его не исключает.

## Резолв и применение
Перед операцией скилл собирает активный набор: фильтр `applies_to` по контексту (operation, layer, element_type, input_type, tags; И-логика внутри правила). Применение:
- генерация: conformance-пункты активных правил входят в приёмочные критерии элемента (`patterns/generation-loop.md`);
- verify: чек-листы активных правил = дополнительные оси (пометка происхождения: `guardrail:<pack>/<rule-id>`);
- intake: чек-листы достаточности входящих (`patterns/intake-gate.md`).

## Аудит-след (обязательный)
В route-run секция:
```
## Guardrails applied
- <pack>/<rule-id> (source, criticality) — где применён
- conflicts: [...] / skipped: [...]
```
Прогон без этой секции при `guardrails≠off` — неполный.

## Severity-политика
Пакет НЕ знает, как его используют: политика отсечки живёт у фабрики (конфиг) или в дефолте паттерна использования. Дефолт: critical/major — ноль на выходе; minor — не более 2 итераций доработки, остаток фиксируется в run.
