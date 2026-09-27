# Пример: OpenSpec change → MasterSpec change → обновлённые спецификации

В кодовой фабрике pricing внутренний расчёт возвращает сумму с 20% налога,
округлённую до целой единицы. OpenSpec change меняет точность до двух знаков и
добавляет разбивку налога. Импорт обновляет функцию, приёмочные проверки и контракт
компонента; код остаётся в исходном состоянии, его реализация — отдельная работа.

| Каталог | Содержимое |
|---|---|
| `before/` | Код, исходный MasterSpec, native OpenSpec main spec и сгенерированный OpenSpec change |
| `prepared/from-openspec-quote-breakdown/` | Канонический MasterSpec change, новый тест, inventory, mapping и review |
| `after/masterspec/` | Ожидаемая фабрика после применения; без копирования source и кода |
| `after/apply-report.md` | Фактический результат учебного применения и его ограничения |

Это небольшой фрагмент фабрики, а не сертифицированный образец полной системы.
Nested capability `pricing/quotes` сохраняет свой путь. Две операции относятся к
одной существующей функции; правило «один requirement = один новый файл» не используется.
Все три native scenario отображены в стабильные AC и приёмочные тесты.

## 1. Успешный перенос и повторный запуск

Из корня репозитория, Python 3.10+; дополнительные пакеты не нужны:

```text
python masterspec-apply-from-openspec/examples/code-factory/replay.py
python -m unittest discover -s masterspec/scripts/tests -p test_openspec_bridge_example.py -v
```

Ожидаемый вывод replay: `applied-in-disposable-example`, затем `no-op`, затем PASS.
Скрипт создаёт собственную временную копию и не принимает путь назначения.
Проверяет настоящие import/scope gates, точное совпадение ДО в нужном разделе,
полный результат и сохранность native OpenSpec и кода. Индекс строится заново по
файлам, с сохранением §1/§7 и прежних комментариев. Поддерживается только подмножество
формата данного fixture: 6 modify-bullet и 1 ADDED. Это регрессионный harness,
а не второй production-механизм применения.

Семантическое mapping выполнил агент по новому скиллу; Python не переводит произвольный
английский текст в MasterSpec. Для своей фабрики вызовите скилл с `source=`, `factory=`,
`specs=` и `mode=prepare`; после согласования — `mode=apply` через apply-change.
В production подготовленный change со статусом «На согласовании» не применяется.
Тестовая копия здесь применяется по разрешению на воспроизведение примеров, без
вымышленного согласования или merged PR.

## 2. Источник или фабрика изменились после подготовки

Тест `test_stale_source_blocks_before_any_factory_write` меняет ставку native delta
с 20% на 21%. Gate возвращает `inventory is stale` до первой записи в MasterSpec.
`test_stale_target_blocks_before_any_factory_write` добавляет другую норму в целевую
функцию; результат — `stale target`, без частичного применения. Оба сценария выполняются
в отдельной временной копии. Пример специально не обновляет snapshot для обхода gate.

Ещё две регрессии проверяют неверный ДО и изменение результата после успешного apply.
Прошлый inventory_id не превращает такой повторный запуск в ложный no-op.

## Как был получен native OpenSpec change

2026-09-27 использован официальный `openspec-propose` и CLI `@fission-ai/openspec`
**1.13.2**, Node **22.23.3**. Проект примера явно инициализирован через
`openspec init <example-project> --tools none --no-animation`.
В этом проекте выполнены `list --json`, `context --json`, `list --specs`, чтение
полного `pricing/quotes`, `new change quote-breakdown`, `status --json` и
`instructions ... --json` по порядку proposal → specs/design → tasks.
Каждый planning-артефакт создан по возвращённым CLI инструкциям. Код на этой стадии
прочитан для planning-контекста и не менялся; импорт далее использует только specs.

Проверка уже сохранённого native source, при установленном OpenSpec 1.13.2:

```text
cd masterspec-apply-from-openspec/examples/code-factory/before
openspec status --change quote-breakdown --json
openspec validate quote-breakdown --strict
```

Фактический результат: все четыре planning-артефакта `done`,
`Change 'quote-breakdown' is valid`. Статус planning `isComplete` не означает,
что выполнены два checkbox в tasks.md: оба оставлены незавершёнными.
OpenSpec sync/archive/apply не запускались.

Для генерации заново используйте свежий disposable-проект: перенесите исходный код,
MasterSpec и native main spec из `before/`, инициализируйте OpenSpec и вызовите
`openspec-propose` с описанием изменения выше. Имя уже существующего source
`quote-breakdown` в сохранённом примере повторно создавать не нужно.

Нормативные файлы и snapshots фиксированы с LF через `.gitattributes`, чтобы SHA256
не зависел от `core.autocrlf`. Точный текст source важен: изменение даже комментария
требует новой подготовки и проверки mapping.
