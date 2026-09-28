---
name: masterspec-verify
description: >
  Вычитка артефактов фабрики по осям O1–O5 (+O0/O6/O7 для spec). layer=req — слой требований (критерий spec_ready);
  layer=spec — слой спецификаций (+ O0 single-source, O6 контракт, O7 физмодель; критерий codegen_ready);
  layer=change — полнота каскада изменения. Оси — данные (../masterspec/references/patterns/verification-axes.md).
  Выдаёт дыры с severity + обязательную телеметрию verify-report, флагует человеку.
when_to_use: >
  проверить слой требований/спецификаций, аудит покрытия, verify layer=req|spec|change,
  найти дыры до кода, оценить codegen_ready / spec_ready
argument-hint: "layer=req|spec|change [preset=core|full] [context=lean|full]"
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Task
---

# masterspec-verify — вычитка по осям O1–O5

Read-only по отношению к артефактам: я нахожу дыры и считаю метрики, НЕ правлю (правки — `derive`/`evolve`). Оси и дешёвое ядро — `../masterspec/references/patterns/verification-axes.md`.

Определи корни фабрики по `../masterspec/references/layout-modes.md §2` (положение `00-masterspec-index.md` → specs-root, changes-root).

При вычитке применяй `../masterspec/references/spec-writing.md`: проверяй полноту обязательств,
а не число заголовков или объём текста. Условный раздел без предмета не является дырой.
Дубликаты норм, непроверяемые формулировки и догадки вместо `OPEN` — содержательные дефекты.

## Параметры
- `layer=req` — оси O1–O5 над слоем требований. Критерий выхода: **spec_ready** (нет блокеров O1/O4b/O5 и OE hard gates → требования годны как вход для спецификаций). Код-генерабельность тут НЕ проверяется — она на слое спеки.
- `layer=spec` — оси O1–O5 + **O0 single-source (hard-fail при двух редакциях контракта)** + O6 контракт + O7 физмодель + полнота воплощения applicable OE. Критерий: **codegen_ready**.

  **Гейт расхождений (если фабрика восстановлена из двух источников).** Есть `recover/_reconciliation.yaml` — прочитай его: неразрешённые `spec-drift`, `declared-not-implemented` и `ambiguous_matches[]` — **блокеры codegen_ready**. Спека, у которой заявленное и фактическое разошлись, к кодогенерации не готова по определению: неизвестно, какую из двух правд кодировать. Свободный текст §7 оси не читают — читается манифест.
- `layer=change` — полнота каскада: каскад-вниз-к-верификации (правка/подъём → AC), обе стороны контракта, scope-fence (вердикт каждому соседу), правило немого вердикта и немого подъёма; в openspec-режиме — `proposal.md` есть ДВУСТОРОННЯЯ проекция `change.md` §1/§2/§7: не содержит фактов, которых там нет, И не теряет пунктов, которые там есть (устаревшее подмножество — тоже дефект; ось O0 single-source, результат входит в cascade_ready). Критерий выхода: **cascade_ready** (нет немых вердиктов и немых подъёмов, нет недоведённого каскад-AC, каждый сосед покрыт вердиктом scope-fence, нет `contract-both-sides: missing`, нет открытых `blockers` по узлам) — симметричен spec_ready/codegen_ready, делает результат change-аудита однозначным для gate. Покрывает ВЕСЬ контракт layer=change (включая обе стороны контракта и блокеры узлов), не только четыре списка-метрики.
- `context=full` / `context=lean` (дефолт) — при standalone-аудите большого слоя в `lean` проверка декомпозируется по файловому контракту (`../masterspec/references/patterns/context-isolation.md §Lean в других скиллах`): `layer=req|spec` — субагент на ЭЛЕМЕНТ (оси элемента разделами в `verify/<elem>.md`), негатив-ось O5 и O0/O6/O7 — отдельными `verify/_negative.md` / `verify/_spec-o0o6o7.md`; `layer=change` — discovery узлов каскада (отдельный субагент → `verify/_change-nodes.md`, считает каскад ЗАНОВО от change-якорей), затем субагент на каждый узел (`verify/<node>.md` нормированного формата: cascade-AC / contract-both-sides / scope-fence / silent-verdict / silent-raise / blockers). verify-оркестратор сводит частичные `verify/*.md` в `verify-report.md`, сам слой не читает; `.work/<run-id>/` чистится. Для ограниченного контекста.
- `guardrails=auto|off|<paths>` — внешние корпоративные правила (`patterns/guardrails.md`): `auto` (дефолт) берёт пакеты из `masterspec-config.yaml` фабрики; активный набор режется селекторами `applies_to`; применённые правила и конфликты фиксируются в route-run секцией «Guardrails applied».

## Метод

При вызове из другого workflow используй переданный `work_root` и его правила
сохранения доказательств вместо default `.work`/чистки. В OpenSpec import границы
заданы `masterspec-apply-from-openspec/references/workspace.md`.

1. preset=core (дефолт) — дешёвое ядро на каждом элементе: структполнота (+ раскладка: `python3 ../masterspec/scripts/check-layout.py <factory-root> --check` — каждый артефакт ↔ канонический подкаталог по `type:` из `artifact-routing.md`; вал в корень слоя = блокер структуры) → обязательный OE set-diff
   (`python3 <masterspec-kernel-skill-dir>/scripts/check-operational-envelope.py <factory-root> --layer req|spec`;
   путь резолвить относительно соседнего kernel-скилла; если Python недоступен — ручная сверка по
   `../masterspec/references/operational-envelope.md`) →
   глоссарий → матрица состояний → трасса
   событие→данные → оракул GWT с репрезентативностью. Для req сверить 8×external-I/O fn плюс
   однострочные internal-only, статусы и
   APPLICABLE→AC/tc-acc; для spec — APPLICABLE→scn, OE-LOAD→lp, внешний OE-DELIVERY→context/api.
   preset=full — все оси на слое + критичных элементах.
   В openspec-режиме при наличии CLI для `layer=change` проверь выбранный change:
   `openspec validate <name> --strict` из разрешённого planning-root (с выбранным store).
   Его ошибка — blocker. `validate --all` — дополнительный layout-health:
   ошибка чужого change не блокирует этот перенос и не маскируется как его дефект.
   Для импорта отдельно проверь native source из его проекта. Нет CLI — «не проверено»,
   не PASS. Неразрешимый planning-root/невалидный общий config блокирует выбранную проверку.
2. **Негатив-ось (O5) — отдельным антагонистом** (`Task`-субагент с единственной задачей «найди что сломается / чего не хватает»): состязательность ловит false-positive, недоступный кооперативному ревью. Не самопроверка автора.
3. **Эталон, не «похоже на правду».** Ревьюер прогоняет спеку через конкретные тесты (GWT-оракул, матрица состояний, трасса), а не оценивает «выглядит ли полным». Против ложной зелёной галочки.
4. Для layer=change — независимость: считать каскад ЗАНОВО, не доверяя зоне генератора.
   Сопоставь baseline и dry-run: старый неусиленный долг — отдельный остаток,
   новые/усиленные нарушения и непроверяемое обязательное изменение — блокеры change.
   Это не освобождает от полной сертификации слоя. Для OpenSpec подробное правило —
   `../masterspec-apply-from-openspec/references/review-policy.md`.
   Для change от evolve соблюдать spec-only границу из `layer-discipline.md`: обход только
   `01-`/`02-` и относящихся решений `04-`; нижние рёбра — `deferred-to-implementation`,
   без чтения кода/codemap. Они не входят в ожидаемое множество каскада.
   До LLM-осей запустить `python3 <kernel-skill-dir>/scripts/check-change-scope.py <change-dir> --factory <specs-root>`.
   Ошибка — blocker и `cascade_ready: no`. Нет Python — явная ручная сверка тех же множеств
   §2/§4/§5/new и путей; не записывать её как машинный PASS.
   Отдельно проверить смысл `change.md`, `new/`, route-run и итогового ответа: предложения
   редактировать исходники, классы, методы, миграции или исполняемые тесты запрещены даже
   без записи в кодовые файлы. Архитектура, API и схемы `02-` допустимы.
   Дословный legacy-текст в ДО/минимальном неизменяемом контексте не является новым
   предложением по коду: отметь baseline-debt, не расширяй его в ПОСЛЕ.
   Scope-fence из import-review/route-run учитывается без дублирования в change.md.
   Конфликт обоснуй несовместимыми исходами в общем случае; совпадение темы не доказательство.
5. **No manual counting (tool-grounding).** Вердикты о покрытии/полноте/счёте («все элементы покрыты», «N сущностей», «нет недостающих») опираются на СВЕРКУ МНОЖЕСТВ, а не на счёт по памяти/на глаз — LLM плохо считает. Сверка = инструмент (Grep/индекс/детерминированный pre-gate `verification-axes.md`) ИЛИ ручной структурный set-diff (выписать оба множества и сравнить — это допустимая деградация, в отличие от прикидки без сверки). При вердикте — указывать, чем сверено. Сначала дешёвый pre-gate покрытия, потом дорогие оси на остатке.
6. **Телеметрия обязательна.** В начале зафиксировать UTC start и ревизию, в конце UTC finish;
   собрать wall-time, число agent-вызовов, доступные token/cost counters и axis-run по judge.
   Сформировать `verify-report.md` строго по `../masterspec/templates/tpl-verify-report.md`, затем
   прогнать `python3 ../masterspec/scripts/check-verify-report.py <verify-report.md>`. Неизвестный
   счётчик = `N/A — причина`, а не пропуск. `last_verified` пишет только verify.
   `started_at`/`finished_at` содержат Z (новые отчёты) или явный UTC-offset.
   Date-only поля и age_days относятся к календарной дате `finished_at` в его зоне,
   а не к локальной дате машины, позже проверяющей сохранённый отчёт.

## Выход (отчуждаемо от содержания)
```
fabric · scope · preset
last_verified · verified_revision · verification_age_days · oldest_element_age_days
cost: {wall_time_seconds,agent_calls,input_tokens,output_tokens,cached_input_tokens,estimated_cost,cost_basis}
automation: {axis_runs_total,axis_runs_machine,machine_axes_percent}
holes: {O1,O2,O3,O4a,O4b,O5(,O0,O6,O7)}  total
by_severity: {blocker,major,minor}
spec_ready / codegen_ready: yes|no
oe: {expected, applicable, n_a_with_reason, open, uncovered_by_tc, unrealized_in_spec, uncovered_by_tc_int, fidelity_gaps}
остаток по типу: {вне-scope / противоречие / недоведённый-негатив}
top_holes: [{ось, элемент, что, severity}]
# для layer=change дополнительно (из node-partials):
cascade_ready: yes|no        # итог: четыре поля ниже пусты И нет contract-both-sides:missing И нет blockers по узлам
silent_verdicts: [узлы]      # узлы с silent-verdict: yes
silent_raises: [узлы]        # узлы с silent-raise: yes
cascade_AC_missing: [узлы]   # каскад-вниз-к-AC не доведён
scope_fence_uncovered: [соседи]  # соседи без вердикта
```
Полная форма отчёта — обязательный `../masterspec/templates/tpl-verify-report.md`; сокращённая
сводка выше не заменяет поля телеметрии. В lean этот же `verify-report.md` собирается агрегатором из частичных `verify/*.md` и хранится ВНЕ `.work/` — в корне фабрики (`layer=req|spec`) или в `<changes-root>/<name>/` (`layer=change`; например `masterspec/changes/<name>/` в classic-подпапке, `openspec/changes/<name>/` в openspec-режиме), как `route-run` (переживает чистку — это метрики, не содержание).
Блокеры → человеку на hard-gate. Метрики выносимы без содержания (приёмка, отчёт).

## Немое решение (проверка дисциплины записей)
Значимый выбор (был реальный выбор из ≥2 вариантов), не оставивший decision record (adr-/dr-), = НЕМОЕ РЕШЕНИЕ — флаг «недоведённое», как пустая ячейка состояний. verify помечает такие места: выбор сделан, обоснование не записано — его переоткроют. Тривиальные шаги (вариант один) записи не требуют.

## Без субагентов (`Task`)
Отдельный проверяющий с чистым контекстом может быть той же моделью; укажи оба факта.
Это изоляция контекста, не независимость ошибок моделей. Для малого каскада допустим
один проверяющий с единым отчётом и вердиктами по всем соседям, без фиктивных agent calls.
Негатив-ось (O5) и независимый контроль layer=change лучше гонять отдельным субагентом. Если механизма нет — прогоняй те же проверки последовательно сам, СМЕНИВ установку на состязательную («ищу, что сломается»); результат слабее изоляции, но контроль сохраняется.
