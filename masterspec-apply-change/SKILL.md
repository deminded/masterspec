---
name: masterspec-apply-change
description: >
  Влить согласованный change.md (diff-блоки) и файлы из `new/` в артефакты фабрики —
  мультиартефактный мерж в masterspec/01-*/02-*/03-*/04-* с обновлением `00-masterspec-index.md`.
  Целевой артефакт — не одна спека, а дерево
  артефактов по slug'ам (fn-*, cmp-*, scn-*, adr-* и др.). Используй когда change-request
  согласован (статус `Согласовано` или `В реализации`), merge PR состоялся, реализация в
  коде (если нужна) завершена, и пользователь говорит "apply change", "влей change",
  "смержи в фабрику", "обнови артефакты".
when_to_use: >
  влить change в фабрику, apply change, обновить артефакты по change,
  merge change в spec, зафиксировать изменения в фабрике
argument-hint: "[имя change] [context=lean|full]"
license: MIT
compatibility: >
  Использует masterspec/ layout, bash/git, AskUserQuestion (при отсутствии — текстовый fallback, см. README).
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
---

# masterspec-apply-change — вливание change.md в артефакты фабрики

Мультиартефактный мерж: diff-блоки из `change.md §4` применяются к существующим файлам фабрики, файлы из `new/` копируются в целевые директории по `type:` фронтматтера, `00-masterspec-index.md` обновляется.

**Input**: Опционально — имя change. Если не указано — автовыбор/выбор через AskUserQuestion.

> **`context=full` / `context=lean` (дефолт)** — для крупного change в `lean` шаги §3, §5–§11 делегируются (файловый контракт — `../masterspec/references/patterns/context-isolation.md §Lean в других скиллах`): оркестратор читает только шапку `change.md` + §2-таблицы → dry-run-план `apply/_dryrun.md`; на каждую строку §2 — субагент применяет И верифицирует СВОЮ строку → `apply/<slug>.md` (`op`/`target`/`result`/`verification`; на конфликте оркестратор спрашивает человека, при пропуске — `skipped_by_user`); reindex субагентом (обновляет индекс); затем smoke-субагент (§9.1, по УЖЕ обновлённому индексу) → `apply/_smoke.md` как gate (провал → откат, к §9.3 не переходим); оркестратор собирает §9.3-вердикт из этих отчётов, целевые файлы сам НЕ читает; `apply-report.md` — вне `.work/`. В `context=full` шаги ниже выполняются самим скиллом (читает сам). Для ограниченного контекста.

## Bundle-пути

- Собственные `references/X` — относительно директории этого скилла.
- Внешние файлы kernel `masterspec` — сосед по директории, резолв через `<Skill dir>/../masterspec/<file>`.
- Если harness даёт `Skill directory: <abs>` — используй. Например:
  - `Read("<Skill dir>/references/merge-workflow.md")` — детальная механика мержа
  - `Read("<Skill dir>/../masterspec/references/artifact-routing.md")` — тип→целевая директория
  - `Read("<Skill dir>/../masterspec/references/layer-discipline.md")` — финальная проверка
- Fallback — `Glob("**/masterspec-apply-change/references/<file>")` и `Glob("**/masterspec/references/<file>")`. Пусто → спроси пользователя.

## Bundled materials

- `references/merge-workflow.md` — детальная механика мультиартефактного мержа: парсинг diff-блоков, обработка конфликтов, копирование `new/`, обновление index, откат через git.

## Внешние references (kernel `masterspec`)

- `masterspec/references/artifact-routing.md` — таблица `type:` → целевая директория (для копирования `new/`)
- `masterspec/references/change-conventions.md` — статусы, откат, архивация
- `masterspec/references/layer-discipline.md` — финальная проверка на обратные ссылки
- `masterspec/references/meta-model-version.md` — ось `meta_model_version`; версия = выход-сертификат (для §13 сертификации)
- `masterspec/references/migration.md` — контур миграции фабрики между версиями (детектор дельты → дозаполнение → сертификация)
- `masterspec/examples/00-masterspec-index.md` — формат строк индекса (`+` actual / `-` draft; `?` — только для планируемого, reindex его в §3–6 не ставит)

**AskUserQuestion fallback**: если инструмент недоступен — задай вопрос текстом, дождись ответа. Не угадывай.

---

## Шаги

### 1. Выбрать change

Если имя указано — использовать. Иначе:
```bash
ls masterspec/changes/ 2>/dev/null | grep -v "^archive$"
```

- Один активный → автовыбор.
- Несколько → AskUserQuestion.

Объяви: `Применяю change: <name>`.

### 2. Проверь наличие change.md и статус

Прочитай `masterspec/changes/<name>/change.md`.

Если файл отсутствует → предложи сначала создать change через `masterspec-evolve` (шаг 0).

Проверь поле `> **Статус**:` в шапке:

| Статус | Действие |
|--------|----------|
| `Согласовано` / `В реализации` | OK, можно мержить |
| `На согласовании` | **БЛОК**: change не согласован. Попроси дождаться merge PR и ручной установки статуса `Согласовано`. Выйди. |
| `Реализовано` | Поздравь, предложи запустить `masterspec-archive-change`. Выйди. |
| `Архивировано` | Сообщи, что change уже заархивирован. Выйди. |
| Другой / отсутствует | Предупреди, спроси подтверждение через AskUserQuestion. |

### 3. Прочитай контекст

> В `context=lean` этот шаг и применение (§5–§11) идут через субагентов: оркестратор читает только шапку change.md + §2-таблицы, целевые файлы и `new/*` не читает (см. врезку выше и `context-isolation.md`). Ниже — режим `full`.

- Полностью `masterspec/changes/<name>/change.md` (шапка + §1..§8).
- Все файлы `masterspec/changes/<name>/new/*.md` (если ADDED не пустой).
- Для каждой строки §2.1 MODIFIED — соответствующий файл фабрики (`masterspec/<путь>`).

Опционально (для ориентира): `masterspec/00-masterspec-index.md`.

### 4. Проверь git-состояние фабрики

Точка отката — через git, не через `.bak`. Запусти:

```bash
git status --porcelain masterspec/ | grep -v "^.. masterspec/changes/"
```

- Вывод не пустой → попроси пользователя сначала закоммитить или откатить незакоммиченные изменения в `masterspec/` вне `changes/`. Выйди.
- Пусто → продолжай. Точка отката — в `HEAD`.

Детали — `references/merge-workflow.md § 1`. `.bak`-файлы создавать запрещено.

### 5. Парсинг change.md

По `references/merge-workflow.md § 2` извлеки:
- Таблицы §2.1 MODIFIED, §2.2 ADDED, §2.3 REMOVED.
- Diff-блоки §4 — для `.md`-строк §2.1 (`**Файл**`, `**Раздел**`, `**Тип правки**`, `ДО:`, `ПОСЛЕ:`). Строки §2.1 с машинным сайдкаром (путь = объявленный `sidecar:`, любой формат) diff-блока НЕ имеют — у них файл-замена в `new/` (обработка §4.6), это норма.

Если парсинг провалился (нет обязательных полей) — сообщи пользователю, что change.md невалиден, не применяй.

### 6. Dry-run

Собери список операций (`merge-workflow.md § 3`) и покажи пользователю: что будет modify, что скопировано из new/, что удалено, как обновится index. Получи подтверждение через AskUserQuestion.

Только после явного «Да» — переходи к §7.

### 7. Применение diff-блоков (MODIFIED)

По `merge-workflow.md § 4`:
- Для каждого diff-блока: прочитай целевой файл, найди раздел **по заголовку**, применение по типу правки (`modify-bullet` / `replace-section` / `add-subsection`).
- Строка §2.1 с машинным сайдкаром (путь = объявленный `sidecar:`, любой формат) — НЕ diff-блок: полная замена файла из `new/` (`merge-workflow.md § 4.6`; целевой сайдкар должен существовать, новый — валидно парситься по своему `sidecar_format`).
- При конфликте (раздел не найден, `ДО:` не найден, файл отсутствует) → `merge-workflow.md § 6`: AskUserQuestion, отменить или пропустить блок.
- Обнови `updated:` в YAML-фронтматтере целевого файла на сегодня.
- Запиши файл.

### 8. Копирование new/ (ADDED)

По `merge-workflow.md § 5`:
- Для каждого файла `new/<slug>.md`: прочитай YAML-фронтматтер → определи целевую директорию по `type:` через `masterspec/references/artifact-routing.md`.
- Проверь отсутствие коллизии ОБОИХ целевых путей: `<target-dir>/<slug>.md` И объявленный `<target-dir>/<sidecar>` не существуют. Любой занят → `merge-workflow.md § 6.4` (не перезаписывать чужой файл; `sidecar:` — только локальный basename).
- Скопируй файл, `updated:` = сегодня. Статус: артефакты слоёв → `status: actual` (change согласован мержем PR); `adr-`/`dr-` сохраняют свой решенческий статус (`proposed`/`accepted`) — НЕ перезаписывать в actual. **Исключение — migration-класс** (шапка change.md `> **Класс**: migration`): сохрани объявленный `status:` из `new/` (не форси `actual`) — миграция меняет форму под новую версию мета-модели, не зрелость (`merge-workflow.md §5.5`).
- **Машинная пара api/data/scn/alg** (компаньон, `change-format.md §3.1`): копируй ПАРУ — компаньон `<slug>.md` и объявленный `sidecar:` (любой формат) рядом. Метаданные и статус — из компаньона; сайдкар копируется as-is (`merge-workflow.md §5.4`).

### 9. Удаление REMOVED

По `merge-workflow.md § 7`:
- Для каждой строки §2.3: `rm masterspec/<путь>`. Если REMOVED-компаньон объявляет `sidecar:` — удали ПАРУ (компаньон + сайдкар) атомарно; сайдкар — только локальный basename рядом (без traversal). Висячий сайдкар индекс и smoke-check не видят (ходят по `.md`) — его ловит form-detector (F2 orphan).
- Grep по `masterspec/` на ссылки на удалённый slug. Если ссылки остались — предупреди пользователя (рассинхрон change.md).

### 10. Обновление `00-masterspec-index.md`

Один алгоритм — **полная перегенерация** по `merge-workflow.md § 8` и `../masterspec/references/index-canonical.md`: §3–§6 индекса перестраиваются по реально существующим файлам фабрики (маркеры `+`/`-` по `status`), §1 «Паспорт» и §7 «Белые пятна» сохраняются дословно. Точечных правок строк индекса (ручное добавление `?`/удаление) НЕ делается — это и исключает рассинхрон.

### 11. Финальная валидация

По `merge-workflow.md § 9` — двухэтапная:

**§9.1 Smoke-check** (структурные инварианты):
- Подсчёт файлов совпадает с ожидаемым.
- Каждый ADDED присутствует в `00-masterspec-index.md`.
- Каждый REMOVED отсутствует и в `00-masterspec-index.md`, и в дереве.
- Grep на обратные ссылки (`masterspec/references/layer-discipline.md § 4`) — нет ссылок сверху вниз.

Провал smoke-check → `git checkout HEAD -- masterspec/ ':(exclude)masterspec/changes/'`, расследуй причину. В verification не переходим.

**§9.2 Verification** (применённость по каждой строке §2.1/§2.2/§2.3):
- Для каждого `modify-bullet` / `replace-section` / `add-subsection` — проверь, что `ПОСЛЕ:` реально в файле (первая + последняя непустая строка для `modify-bullet`; первая строка в границах раздела для `replace-section` / `add-subsection`). Детальный алгоритм — `merge-workflow.md § 9.2`.
- Для ADDED — файл на месте, YAML-фронтматтер валиден (`slug`/`type`/`status`/`updated`), нет HTML-комментариев шаблона.
- Для REMOVED — файла нет.
- Строки, пропущенные пользователем в §6 (skipped_by_user), хранятся в памяти сессии и из verification исключаются.

**§9.3 Вердикт**:
- `unconfirmed == 0` → переходи в §12.
- `unconfirmed > 0` → AskUserQuestion с тремя опциями: **rollback** (`git checkout HEAD -- masterspec/ ':(exclude)masterspec/changes/'`), **override** (пользователь подтверждает применение глазами), **leave** (статус `В реализации`, без архивации). См. `merge-workflow.md § 9.3`.

### 12. Обновление статуса change.md

По `merge-workflow.md § 10`:
- Вердикт §11 = `confirmed` ИЛИ `override` → `> **Статус**: Реализовано` в шапке change.md (+ синхронизируй `status:` в YAML-фронтматтере, если он есть).
- Вердикт §11 = `leave` → `> **Статус**: В реализации`.
- Вердикт §11 = `rollback` → статус change.md не трогаем, выйди.

### 13. Сертификация версии мета-модели

По `merge-workflow.md § 11`. Единственный шаг, ставящий штамп `meta_model_version` фабрики; версия = выход-сертификат (`../masterspec/references/meta-model-version.md`).

- Прогони детекторы инвариантов текущей версии на применимых scope: `check-operational-envelope.py masterspec --layer req` (+ `spec`, если есть `02-specifications/`; + `code`, если есть `03-codemap/`) и `check-verify-report.py <report>`, если verify-report есть. Собери все BLOCKER-строки = остаточная дельта.
- **Все применимые scope зелёные** → впиши/обнови `meta_model_version: <текущая версия ядра>` (сейчас `3.0`, без квалификатора) и `updated:` во фронтматтере Паспорта `01-requirements/01-system/as-*.md`. Идемпотентно (уже равно → no-op).
- **Часть scope зелёная** → scope-квалифицированный штамп `<версия>-<scope>` (напр. `3.0-req`); честно фиксирует, докуда дотянута версия.
- **Все применимые scope красные** → штамп не ставь и не понижай; в отчёте «до-<версия>, дельта: N BLOCKER». Не откат — правки change применены.
- **Режим сертификации без change** (миграция draft-фабрики, дозаполнение уже в дереве — `../masterspec/references/migration.md` шаг 5): §§3–12 пропускаются, выполняется только этот шаг.

### 14. Вывод

```
## Apply Complete (Multi-artefact Merge)

**Change:** <change-name>
**Factory:** <factory-slug>

### Применено

#### MODIFIED (N diff-блоков)
- ✓ fn-send-notification.md : AC-03 (modify-bullet)
- ✓ cmp-delivery-router.md : Возможности / cap-retry (add-subsection)

#### ADDED (M файлов из new/)
- ✓ scn-retry-flow.md → 02-specifications/02-scenarios/
- ✓ adr-backoff-policy.md → 04-decisions/

#### REMOVED
(нет)

#### Index
- перегенерирован полностью по `index-canonical.md` (маркеры `+`/`-` по `status`), обновлено `updated`

### Verification (применённость)
confirmed: K · skipped_by_user: S · unconfirmed: U
(если U > 0 — указать, какую опцию выбрал пользователь: rollback / override / leave)

### Сертификация версии
meta_model_version: 3.0 (проставлен) | до-3.0 (дельта: N BLOCKER — <первые строки>)
детекторы: check-oe req=OK[ spec=OK][ code=OK][ ; check-verify-report=OK]

### Конфликты (пропущенные блоки)
(если были — список с причиной из §6 merge-workflow.md)

### Откат
`git checkout HEAD -- masterspec/ ':(exclude)masterspec/changes/'`

### Next step
- Вердикт = `confirmed` / `override` → Готово к архивации: запусти скилл `masterspec-archive-change`.
- Вердикт = `leave` → разберись с unconfirmed-строками, потом перезапусти `apply-change` или переведи статус в `Реализовано` вручную.
- Вердикт = `rollback` → правки отменены; расследуй, почему verification не прошёл, и перезапусти `apply-change`.
```

---

## Guardrails

- ВСЕГДА читай change.md, все `new/*.md`, целевые MODIFIED-файлы ПЕРЕД началом.
- ВСЕГДА проверяй чистоту git-состояния `masterspec/` (исключая `changes/`) перед мержем — точка отката в `HEAD`.
- ВСЕГДА dry-run + подтверждение через AskUserQuestion перед применением.
- **НЕ угадывай раздел, если заголовок не найден** — конфликт, вопрос пользователю.
- **НЕ пытайся создать раздел самостоятельно** — сигнал о рассинхроне change.md с состоянием файла.
- НИКОГДА не удаляй контент, не упомянутый в change (кроме REMOVED из §2.3).
- НИКОГДА не создавай `.bak`-файлы.
- НЕ трогай файлы в `masterspec/changes/<name>/` (кроме строки статуса в change.md).
- НЕ коммитай автоматически — коммит пользователь делает отдельно, видя diff.
- Если smoke-check (§11 / `merge-workflow.md §9.1`) провалился — `git checkout HEAD -- masterspec/ ':(exclude)masterspec/changes/'`, сообщи, в verification не переходи.
- Если verification (§11 / `merge-workflow.md §9.2`) нашёл `unconfirmed`-строки — **НЕ переводи статус change.md в `Реализовано` автоматически**. Только через явный `override`, `leave` или `rollback` пользователя в §9.3. Тихий переход в `Реализовано` при unconfirmed — баг.
