---
name: masterspec-derive
description: >
  Породить слой фабрики по мета-модели masterspec. layer=req — из собранной информации в слой требований
  (бывший kernel-режим design «с нуля»); layer=spec — из требований в слой спецификаций.
  Оркестратор слоя: разворачивает слой на элементы, на каждый зовёт gen (узел-исполнение) или узел-решение,
  гонит verify, ведёт route-run, ставит human-gate. Поглощает прежний режим design.
when_to_use: >
  спроектировать слой требований или спецификаций, derive layer=req, derive layer=spec,
  сгенерировать as/fn/nfr/rules/cdm или cmp/scn/api/data, описать фабрику с нуля
argument-hint: "layer=req|spec [pass=linear|parallel] [verify=core|full]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
---

# masterspec-derive — породить слой

Route-скилл: информация/требования → слой артефактов. Читай kernel-справочник (`../masterspec/meta_model.md`, `../masterspec/references/layer-discipline.md`) и паттерны (`../masterspec/references/patterns/`).

## Параметры
- `layer=req` — Route A: вход = бизнес-запрос + агрегат `explore` → выход `01-requirements/` (as, fn, nfr, rules, cdm, dict, tc-acc).
- `layer=spec` — Route B: вход = согласованный слой требований → выход `02-specifications/` (cmp/cap, scn, alg, api, data, cd, lp, tc-int). Контракт и физмодель рождаются ЗДЕСЬ.
- `pass=linear` (дефолт) — по одному элементу, человек контролирует каждый шаг. `pass=parallel` — независимые элементы разом субагентами, человек на финальной вычитке. Дефолт linear; parallel — явный выбор аналитика.
- `verify=core` (дефолт) — дешёвое ядро осей на каждом элементе; `verify=full` — все 5 осей на слое + критичных элементах.

## Метод (оркестрация)
1. **Состав слоя.** Определи требуемые элементы. layer=req: as → cdm(сущности+состояния) → fn → rules → nfr → dict? → tc-acc. layer=spec: cmp(cap) → scn → alg → api/data → cd/lp → tc-int. cdm/cmp раньше зависимых.
2. **Маршрут внутри слоя** — порядок по зависимостям (выше). Это «route внутри слоя».
3. **На каждый элемент — узел.** Оцени decision-worthiness (`patterns/decision-node.md`): есть реальная развилка (модель данных, форма контракта, алгоритм) → **узел-РЕШЕНИЕ** (2-3 варианта → выбор → ADR в `04-decisions/`). Нет → **узел-ИСПОЛНЕНИЕ** (`patterns/element-workflow.md`): планировщик → `gen type=<элемент>` (субагент, изолир. фокус-набор) → приёмщик (single-source на месте).
4. **Параллельность.** pass=parallel: независимые элементы (несколько fn) — батч `gen`-субагентов; приёмщик сводит редакции (анти-расщепление). pass=linear: по одному.
5. **Дозапрос.** Если gen-субагенту не хватило фокус-набора — явный запрос «не хватает X» → обратно в `explore`, ≤2 раунда, потом эскалация человеку (Открытый вопрос). Не выдумывать.
6. **Вычитка.** `verify scope=<layer>` на собранном (preset по `verify=`). Негатив-ось (5) — отдельный антагонист-субагент.
7. **route-run.** Веди `changes/<name>/route-run-<ts>.md`: вход · pass · по элементам (дозапросы/оси/итерации) · отчуждаемые метрики · открытые вопросы · кто принял.
8. **Hard-gate** (`patterns/enforcement.md`). Выход = ЧЕРНОВИК (`status: draft`) в карантин. Применение в фабрику — только человек: ревью + merge PR → `apply`. Статус «Согласовано» ставит аналитик, не агент.

## Выход
- слой (`01-` или `02-`) в карантине, `status: draft`;
- `route-run-<ts>.md` с отчуждаемыми метриками;
- открытые вопросы человеку.

## Чек перед отдачей
Общий чек-лист артефакта — `../masterspec/SKILL.md §3`. Для layer=spec вычитка обязана пройти O0 single-source (две редакции контракта = hard-fail) и O6/O7 (`patterns/verification-axes.md`).

## Запись решений (дисциплина)
Каждый пройденный узел-решение оставляет ЗАПИСЬ: `adr-` в `04-decisions/` (развилка сквозная/архитектурная) или `dr-` рядом с артефактом на его слое (локальная, по одному артефакту). Выбор без записи = немое решение → блок перехода. Правила — `../masterspec/references/patterns/decision-node.md` (раздел «Дисциплина в скиллах»).
