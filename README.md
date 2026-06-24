# masterspec-skills

Набор скиллов для описания фабрик (автоматизированных систем) по мета-модели masterspec — и для строгой, мультиагентной генерации спецификаций, пригодных для перехода к коду.

> Скиллы работают напрямую с файловой системой — внешних CLI/зависимостей не требуется.

## Принцип набора (FPF — admissible action)
- **kernel `masterspec` = СПРАВОЧНИК**: мета-модель (3 слоя), 24 шаблона, дисциплина слоёв, паттерны-references. Сам не «делает».
- **операции = скиллы-ГЛАГОЛЫ**. Вариации одного назначения = ПАРАМЕТР скилла, не новый скилл.
- **паттерны процесса = references** внутри kernel, не отдельные скиллы.

## Скиллы

| Скилл | Вызов | Назначение | Статус ветки `rewrite` |
|---|---|---|---|
| `masterspec` (kernel) | 👤 справочник | мета-модель + шаблоны + references | ✅ переписан в справочник |
| `explore` | 👤→🤖 | разведка кодовой базы, изолир. фокус-набор | исходный (доработка: траектория/изоляция — 🔜) |
| `derive layer=req\|spec` | 👤 | породить слой (req: инфо→требования; spec: требования→спека). Поглотил режим design | ✅ layer=req · 🔜 layer=spec |
| `verify scope=req\|spec\|change` | 🤖→👤 | вычитка по 5 осям; поглотил режим audit | ✅ scope=req · 🔜 spec/change |
| `gen type=<артефакт>` | 🤖 | сгенерировать 1 артефакт (узел-исполнение) | ✅ |
| `evolve entry=req\|rule\|ext` | 👤 | изменить фабрику (4 точки входа) | 🔜 (спроектирован) |
| `recover source=docs\|code` | 👤 | восстановить из документов/кода (режимы recover/codemap/reverse) | 🔜 |
| `apply` (apply-change) | 👤 | влить change в фабрику + reindex | исходный |
| `archive` (archive-change) | 👤 | архивация change | исходный |
| `reindex` | 🤖/👤 | перегенерация индекса | исходный |

Граница набора: `impl-plan` / `implement` (кодинг) — отдельный набор скиллов кодинга.

## Мета-модель: три слоя
Требования (`01-`, ЧТО) → Спецификации (`02-`, КАК) → Кодовая база (`03-`, ГДЕ) + `04-decisions/`. Ссылки **снизу вверх** — дисциплина изоляции слоёв. Полная мета-модель — `skills/masterspec/meta_model.md`.

## Жизненный цикл
- **Генерация:** `explore` → `derive layer=req` → `verify scope=req` → human-gate (merge PR) → `apply` → `derive layer=spec` → `verify scope=spec` (codegen_ready) → human-gate → кодоген.
- **Изменение:** `evolve entry=…` → `verify scope=change` → human-gate → `apply`.
- **Hard-gate:** «Согласовано» ставит человек (merge PR), не агент.

## Статус ветки `rewrite`
Первый вертикальный срез — генерация СЛОЯ ТРЕБОВАНИЙ по новой логике: kernel-справочник + `derive layer=req` + `verify scope=req` + `gen` + паттерны (decision-node, element-workflow, enforcement, verification-axes). Дальше — `layer=spec`, `evolve`, `recover`, доработка `explore`. Прежние скиллы (design/propose/implement) пока сосуществуют, мигрируют по мере среза.

## Установка
```bash
claude plugin install <путь до этой директории>
```
Другие harness'ы — скопируй `skills/` в skill-registry.
