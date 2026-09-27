---
type: route-run
factory: <factory-slug>
flow: generation | change        # генерация (derive) | изменение (evolve)
layer_or_entry: <layer=req|spec ИЛИ entry=req|rule|ext>
pass: linear | parallel
ts: YYYY-MM-DDThh:mm
---
# Route-run: <factory> / <layer|entry>

Отчуждаемый аудит-след прогона derive/evolve. Метрики выносимы без содержания фабрики — для приёмки и сравнения прогонов.

> **Расположение** (зависит от потока): генерация (`derive`) — `<specs-root>/route-run-<ts>.md` (в корне фабрики, change'а нет); изменение (`evolve`) — `<changes-root>/<name>/route-run-<ts>.md`.

## Вход
<!-- бизнес-запрос / зона изменения / якоря скоупа -->

## По элементам
<!-- На каждый порождённый/правленый элемент: -->
| Элемент (slug) | Узел | Дозапросы | Оси с дефектами | Итераций |
|---|---|---|---|---|
| <slug> | решение / исполнение | 0 | — | 1 |

## Для потока изменения (evolve)
<!-- Опустить для генерации. -->
- **scope-fence:** <сосед → вердикт «не затронут, потому что…»>
- **граница evolve:** spec-only; нижние зависимости — `deferred-to-implementation`
- **подъёмы вверх:** <узел → материализован каскад? да/нет>
- **открытые развилки (узлы-решения):** <slug → adr-/dr->

## Метрики (отчуждаемо)
- точность: тронуто / в каскаде = N / M
- полнота: забытых узлов = 0
- немые вердикты: 0 · немые подъёмы: 0 · немые решения: 0
- OE: <дословная строка `OE metrics:` из check-operational-envelope.py; не вести второй реестр>
- OE-покрытие: <scope → exit code только реально выполненных проверок>; fidelity gaps = N
<!-- evolve не запускает scope=code; N/A не означает PASS. -->
- критерий: spec_ready | codegen_ready | cascade_ready = yes/no
- scope gate (evolve): <check-change-scope.py exit code или ручная сверка с основанием>
- verify-report: <путь>; telemetry gate (`check-verify-report.py`) = <exit code>

## Открытые вопросы человеку
- <вопрос>

## Кто принял
<!-- заполняется человеком на гейте: merge PR, кем, когда -->
