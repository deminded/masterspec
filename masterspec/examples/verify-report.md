---
type: verify-report
factory: oe-example
scope: spec
preset: full
last_verified: 2026-07-13
verified_revision: N/A — example fixture
started_at: 2026-07-13T10:00:00Z
finished_at: 2026-07-13T10:00:02Z
---
# Verify-report: oe-example / spec

## Результат
- holes: O1=0; O2=0; O3=0; O4a=0; O4b=0; O5=0; O0=0; O6=0; O7=0; O_T=0
- by_severity: blocker=0; major=0; minor=0
- codegen_ready: yes
- OE: functions=2; applicable=7; weighted=21/21
- top_holes: N/A — holes отсутствуют

## Возраст сверки
- last_verified: 2026-07-13
- verification_age_days: 0
- oldest_element_last_verified: 2026-07-13
- oldest_element_age_days: 0
- stale_after_days: 14
- stale_elements: 0

| Элемент | Criticality | Last verified | Age days | Статус |
|---|---|---|---|---|
| fn-send-notification | medium | 2026-07-13 | 0 | fresh |

## Стоимость прогона
- wall_time_seconds: 2.0
- agent_calls: 0
- input_tokens: N/A — локальный валидатор не отдаёт счётчик
- output_tokens: N/A — локальный валидатор не отдаёт счётчик
- cached_input_tokens: N/A — локальный валидатор не отдаёт счётчик
- estimated_cost: N/A — модель не вызывалась
- cost_basis: N/A — модель не вызывалась

## Доля машинных осей
- axis_runs_total: 10
- axis_runs_machine: 4
- machine_axes_percent: 40.00

| Ось | Элемент/набор | Judge | Инструмент/основание | Verdict |
|---|---|---|---|---|
| OE/O_T | oe-example | machine | check-operational-envelope.py | pass |
| O1–O7 | oe-example | llm | пример отчёта | pass |

## Остаток и блокеры
- вне scope: N/A — отсутствует
- противоречия: N/A — отсутствуют
- недоведённый негатив: N/A — отсутствует
- blockers: N/A — отсутствуют
