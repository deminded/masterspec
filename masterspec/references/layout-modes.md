# Раскладки фабрики (layout): где живут слои и changes

Справочник читают ВСЕ скиллы-операции при старте: он определяет, где искать артефакты
фабрики и куда класть changes. До этого файла знание о корнях жило в каждом скилле
по-своему (derive принимал `root=`, apply-change хардкодил `masterspec/changes/`) —
и разъезжалось. Теперь корней ДВА, и оба выводятся из одного факта.

## 1. Два корня

| Термин | Что это | Примеры |
|---|---|---|
| **specs-root** | каталог, где лежит `00-masterspec-index.md` и слои `01-…`/`02-…`/`03-…`/`04-…`; в старых текстах скиллов это же звалось «корень фабрики» / `<factory-root>` — термины эквивалентны | `.` · `masterspec/` · `openspec/specs/` |
| **changes-root** | каталог change-директорий (`<name>/change.md`, `archive/`) | `changes/` · `masterspec/changes/` · `openspec/changes/` |

Внутри specs-root раскладка ЕДИНА для всех режимов и задана `artifact-routing.md`.
Режим меняет только положение корней, не дерево внутри них.

🔴 Граница, оплаченная вычиткой: `changes/` — НЕ часть дерева specs-root. В classic
changes-root СЛУЧАЙНО выглядит подкаталогом specs-root (`<specs-root>/changes/`), в
openspec он сосед (`openspec/changes/`). Скелет фабрики при инициализации — это слои
`00-…`/`01-…`—`04-…` в specs-root ПЛЮС отдельно changes-root по режиму; буквальное
«скелет целиком в specs-root» в openspec-режиме породило бы дефектный
`openspec/specs/changes/`.

## 2. Резолвинг: один факт — положение индекса

Алгоритм для любого скилла (шаг «найди фабрику»):

1. Найди `00-masterspec-index.md`. Алгоритм ДЕТЕРМИНИРОВАННЫЙ, без short-circuit:
   собери ВСЕХ кандидатов одним проходом — `Glob("**/00-masterspec-index.md")` по репо
   (архивы и `.work/` не в счёт). Ровно один найден — он и есть фабрика. Ноль — фабрики
   нет (инициализация). Больше одного — остановись и спроси человека, какая фабрика
   рабочая: молчаливый выбор «первого по приоритету» прячет полупереехавшую фабрику
   (перенос §5, брошенный на середине, оставляет индекс и в `masterspec/`, и в
   `openspec/specs/`). Порядок `./` → `masterspec/` → `openspec/specs/` — это порядок
   ПЕРЕЧИСЛЕНИЯ кандидатов человеку, не порядок выбора.
   Референс-реализация ИСПОЛНЯЕМАЯ: `scripts/check-layout.py <repo-root> --resolve-roots`
   печатает specs-root/changes-root/layout, при неоднозначности выходит кодом 2 с перечнем.
   Скилл может звать её вместо пересказа алгоритма; тесты гоняют её на четырёх раскладках.
2. `specs-root` = каталог найденного индекса.
3. `layout` = строка `Раскладка (layout)` из §1 «Паспорт» индекса (форма — plain, как соседние строки паспорта: `- Раскладка (layout): openspec`; резолвинг ищет ПОДСТРОКУ «Раскладка (layout)», так что жирное начертание не ломает, но канон — plain); если строки нет —
   выведи по пути: specs-root оканчивается на `openspec/specs` → `openspec`, иначе `classic`.
4. `changes-root`:
   - `classic` → `<specs-root>/changes/`
   - `openspec` → `<specs-root>/../changes/` (то есть `openspec/changes/` — СОСЕД specs,
     как того требует раскладка OpenSpec)

`classic` покрывает и «в корне репо», и «подпапкой masterspec/» — различие только в том,
где лежит индекс, отдельного имени ему не нужно.

Параметры инициализации: `layout=openspec` задаёт ОБА корня сам; задавать его вместе с
`root=` — конфликт (два источника одного факта), остановись и спроси человека. Это правило
живёт здесь и действует для ЛЮБОГО скилла, принимающего оба параметра.

## 3. Режим `layout=openspec` — совместимость с OpenSpec

Назначение: фабрика живёт внутри структуры инструмента OpenSpec
(github.com/Fission-AI/OpenSpec), так что `openspec` CLI и его slash-команды видят
дерево и не ломаются, а masterspec остаётся ИСТОЧНИКОМ ИСТИНЫ.

```
<repo>/
├── openspec/
│   ├── config.yaml              ← дескриптор для openspec (schema + context), создаёт init
│   ├── specs/                   ← specs-root фабрики
│   │   ├── 00-masterspec-index.md
│   │   ├── 00-glossary.md
│   │   ├── 01-requirements/…    ← дерево по artifact-routing.md, БЕЗ изменений
│   │   ├── 02-specifications/…
│   │   ├── 03-codemap/…
│   │   └── 04-decisions/
│   └── changes/                 ← changes-root фабрики
│       ├── <name>/
│       │   ├── change.md        ← источник истины (канонический 8-секционный формат)
│       │   ├── proposal.md      ← МОСТ: проекция §1/§2 для openspec (см. §4)
│       │   ├── .openspec.yaml   ← МОСТ: `schema: spec-driven` + `skip_specs: true`
│       │   ├── tasks.md         ← создаёт impl-plan (имя уже совместимо)
│       │   └── new/…            ← карантин новых артефактов, как обычно
│       └── archive/YYYY-MM-DD-<name>/   ← openspec игнорирует archive/ — совпадение форматов
```

Служебные каталоги фабрики (`.work/<run-id>/`, `.research/`, `00-source-data/`) живут в
specs-root, как и в classic (скрипты `check-layout.py`/`check-operational-envelope.py`
принимают specs-root первым аргументом — им всё равно, где он лежит): для openspec CLI они безвредны — он игнорирует всё, что не
`specs/**/spec.md` и не каталог change.

Почему это работает (проверено живым CLI 1.8.0, 2026-08-06;
повторено приёмочными тестами на CLI 1.13.2, 2026-09-27):
- `openspec list/validate` видят спеками ТОЛЬКО `specs/**/spec.md` — деревья артефактов
  masterspec игнорируются молча, не ломая команд;
- каталог в `changes/` без файлов openspec падал бы в `validate` («no deltas»), поэтому
  каждый change несёт `.openspec.yaml` с `skip_specs: true`; маркер честен — деталь
  поведения описывают артефакты masterspec, а не spec-дельты openspec;
- `.openspec.yaml` ОБЯЗАН содержать `schema: <имя известной схемы>` (без него маркер
  не признаётся): пишем `schema: spec-driven`;
- `changes/archive/` openspec не сканирует — архивирование masterspec совместимо как есть.

## 4. Мосты: что создаётся в openspec-режиме сверх обычного

| Артефакт | Кто создаёт | Содержимое |
|---|---|---|
| `openspec/config.yaml` | `derive`/`recover` при инициализации (если файла нет — создать по шаблону; если ЕСТЬ — не перезаписывать, но проверить `schema:`: отсутствует или не `spec-driven` — остановись и предложи владельцу явный merge, паспорт `layout: openspec` без валидного дескриптора не ставится) | `schema: spec-driven` + `context:` с картой мета-модели masterspec (шаблон `tpl-openspec-config.md`) |
| `changes/<name>/.openspec.yaml` | `evolve` шаг 3 | две строки: `schema: spec-driven`, `skip_specs: true` |
| `changes/<name>/proposal.md` | `evolve` шаг 3; обновляет тот, кто правит §1/§2/§7 change.md | проекция: `## Why` ← §1.1–1.2 сжато; `## What Changes` ← §2 списком; `## Impact` ← §7. Первая строка: `> Источник истины — change.md; этот файл — мост для OpenSpec.` |

Инвариант моста ДВУСТОРОННИЙ: proposal.md не содержит фактов, которых нет в change.md,
И отражает ВСЕ пункты §1/§2/§7 (Why/What Changes/Impact). Устаревший proposal — подмножество
change.md — тоже дефект: OpenSpec показал бы неполное изменение. Проверяют обе стороны
(`verify`, ось O0; результат входит в cascade_ready). Расхождение —
дефект change (ловится `verify scope=change`, ось O0 single-source).

## 5. Что режим НЕ делает (граница, названная явно)

- НЕ конвертирует артефакты masterspec в openspec-спеки (`spec.md` с Requirement/Scenario).
  Мост форматов — отдельная работа; эскиз: scn-* → capability-спеки, постусловия → Scenario.
  До неё `openspec list --specs` в фабрике openspec-режима штатно показывает пусто.
- НЕ переносит существующие фабрики автоматически. Перенос classic → openspec: переместить
  дерево слоёв в `openspec/specs/`, `changes/` в `openspec/changes/`, дописать паспорт,
  создать мосты для АКТИВНЫХ changes (архивные не трогать), прогнать
  `check-layout.py openspec/specs --check` и `openspec validate --all`.

## 6. Приёмка режима (что считается «работает»)

1. `openspec validate --all` на фабрике зелёный (мосты признаны, деревья не мешают);
2. `openspec list` показывает changes фабрики с task-прогрессом из tasks.md;
3. `check-layout.py <specs-root> --check` зелёный — раскладка внутри specs-root канонична;
4. дефолтное поведение (classic) не изменилось ни в одном скилле: без строки в паспорте и
   без `layout=` всё работает как до этого файла.
