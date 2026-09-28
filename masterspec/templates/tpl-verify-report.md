---
type: verify-report
factory: <factory-slug>
scope: <req | spec | change>
preset: <core | full>
last_verified: YYYY-MM-DD
verified_revision: <git-sha | N/A — вне git>
started_at: YYYY-MM-DDThh:mm:ssZ
finished_at: YYYY-MM-DDThh:mm:ssZ
---
# Verify-report: <factory> / <scope>

<!-- Штатный отчёт verify. Все поля обязательны; неизвестное значение записывается как
     `N/A — причина`, не пустой строкой. last_verified меняет только verify, не derive/evolve. -->

## Результат
- holes: {O1,O2,O3,O4a,O4b,O5[,O0,O6,O7,O_T1..O_T6]} = <total>
- by_severity: blocker=<N>; major=<N>; minor=<N>
- spec_ready / codegen_ready / cascade_ready: <yes | no | N/A — не этот scope>
- OE: <дословная строка `OE metrics:` валидатора | N/A — метрики не выданы, см. exit code и диагностику>
- top_holes: <ось; элемент; дефект; severity>

## Возраст сверки
- last_verified: YYYY-MM-DD
- verification_age_days: <целое число на календарную дату finished_at в его зоне>
- oldest_element_last_verified: YYYY-MM-DD
- oldest_element_age_days: <целое число на ту же дату>

<!-- Новые отчёты используют UTC (Z). У started_at/finished_at обязательна зона:
     Z или явный UTC-offset. last_verified и oldest_element_last_verified —
     календарные даты в зоне finished_at. Возраст фиксируется на finished_at,
     не пересчитывается на дату машины при повторном чтении отчёта. -->
<!-- Порог берётся из явной политики фабрики или входа задачи, не назначается ради
     прохождения проверки. Если порог не задан, оба stale-поля — `N/A — причина`;
     ноль допустим только как явно заданный порог или измеренное число элементов.
     При известном пороге, но недоступном измерении stale_elements тоже N/A с причиной.
     Без порога не присваивай элементам fresh/stale. -->
- stale_after_days: <целое >= 0 | N/A — политика не задаёт порог>
- stale_elements: <N | N/A — причина отсутствия оценки>

| Элемент | Criticality | Last verified | Age days | Статус |
|---|---|---|---|---|
| <slug> | high / medium / low | YYYY-MM-DD | <N> | fresh / stale / not-verified / N/A — порог не задан |

## Стоимость прогона
<!-- Стоимостные счётчики (input_tokens/output_tokens/estimated_cost) НЕ могут быть нулём:
     реальный вызов модели тратит токены и деньги. Ноль здесь — неизмеренное под видом
     «бесплатно» (дыра телеметрии). Нет измерения → `N/A — причина`, а не 0.
     cached_input_tokens=0 и agent_calls=0 законны (холодный кеш / чисто машинный прогон). -->
- wall_time_seconds: <N>
- agent_calls: <N>
- input_tokens: <положит. целое | N/A — среда не отдаёт счётчик>
- output_tokens: <положит. целое | N/A — среда не отдаёт счётчик>
- cached_input_tokens: <N | N/A — среда не отдаёт счётчик>
- estimated_cost: <положит. decimal currency | N/A — нет тарифных данных>
- cost_basis: <тариф/модель/дата или причина N/A>

## Доля машинных осей
<!-- Единица счёта axis-run = один запуск оси над одним элементом. Mixed считается machine
     только когда машинный результат достаточен для финального verdict; иначе judge=llm/manual. -->
- axis_runs_total: <N>
- axis_runs_machine: <N>
- machine_axes_percent: <0..100, две цифры; axis_runs_machine / axis_runs_total × 100>

| Ось | Элемент/набор | Judge (machine/llm/manual) | Инструмент/основание | Verdict |
|---|---|---|---|---|
| <O_*> | <slug/set> | machine / llm / manual | <команда/проверяющий> | pass/fail/unconfirmed |

## Остаток и блокеры
- вне scope:
- противоречия:
- недоведённый негатив:
- blockers:
