# Review переноса quote-breakdown

Статус: подготовлено для согласования; self-review автора дополнен независимым
семантическим review mapping и проверкой воспроизведения другим агентом.
Учебное применение в одноразовой копии разрешено задачей на воспроизведение примера.
Это не согласование production change и не свидетельство merge PR.

| Операция / scenario | Цель | Проверка смысла |
|---|---|---|
| MODIFIED Taxed quote / Fractional subtotal | fn-calculate-quote: основной поток, AC-01; tc-acc-taxed-quote: шаг 1 | 10.03 → 12.04; 20%, half-up и неотрицательный вход сохранены |
| MODIFIED Taxed quote / Zero subtotal | fn-calculate-quote: AC-02; tc-acc-taxed-quote: шаг 2 | Нулевой результат сохранён дословно |
| ADDED Tax breakdown / Breakdown reconciles | fn-calculate-quote: результат, AC-03; tc-acc-quote-breakdown: шаг 1 | Все три значения 10.03 / 2.01 / 12.04 и правило разности перенесены |

Каскад: cmp-quote-policy/cap-calculate теперь ссылается на состав результата функции.
Числа не продублированы в компоненте. Дополнительных обязанностей у компонента нет;
порядок кооперации, внешние каналы и persistence этим изменением не вводятся.
В фабрике нет иных зависимых требований или спецификаций; индекс включён в snapshot.
Стабильные slug и AC-01/AC-02 сохранены, AC-03 добавлен.

Границы: прочитаны native delta, соответствующий native main spec, индекс и три
артефакта MasterSpec. Native design/tasks не являются источником переноса.
Во всём destination нет предложений по коду; нижнее влияние —
`deferred-to-implementation`. Импорт не подтверждает выполнение coding tasks.

Проверки на финальной базе: OpenSpec 1.13.2 `validate quote-breakdown --strict` PASS;
`check_import.py` — 2 операции, ready-for-review; `check-change-scope.py` PASS.
Покрыты 3 из 3 native scenarios; добавленных из предположений норм нет.
Readiness относится к переносу этого фрагмента, не к полноте фабрики.
После применения `check-layout.py`: проверено 4 артефакта, неверных путей 0.

Воспроизведение применяет 6 diff-блоков и 1 новый артефакт, сравнивает полный результат
с `after/masterspec`, затем повторяет импорт как no-op. Изменение source, target или
неверный ДО блокирует запись целиком. Итоговая дрейфующая база не скрывается прошлым
inventory_id. Для реальной базы после такого блокера нужны remap и повторное review,
а не пересчёт хешей для обхода проверки.
