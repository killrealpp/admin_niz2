# Broad Regression Scenarios

Назначение: чеклист широких регрессий из полного `scripts/local_regression_suite.py`. Авто-проверка последнего прогона: `OK`, 2026-06-01.

## Как Проверять Руками

- Это не один диалог, а зоны поведения, которые покрыты пачкой автотестов.
- Для ручной проверки лучше выбирать по 1-3 живых диалога из каждой зоны и переносить найденные сбои в отдельные сценарии.

## Список Зон

| ID | Зона | Авто-статус | Ручная проверка |
|---|---|---:|---|
| REG-001 | Fresh/new booking и сброс старых slot-полей | OK | TODO |
| REG-002 | Payments/holds: retry payment link, expired hold, existing payment link, paid question, payment-delay wording, resume same expired hold, concurrent hold conflict, payment intent retry | OK | TODO |
| REG-003 | Services/date/gazebo/time parsing | OK | TODO |
| REG-004 | Live capacity/date scenarios | OK | TODO |
| REG-005 | Mixed selection + info | OK | TODO |
| REG-006 | Upsell and addon persistence | OK | TODO |
| REG-007 | Post-booking summary and active bookings | OK | TODO |
| REG-008 | Cancel/reschedule/reminder flows | OK | TODO |
| REG-009 | Media/photo routing | OK | TODO |
| REG-010 | Waitlist/handoff safeguards | OK | TODO |
| REG-011 | Same-date/same-time second-service references | OK | TODO |
| REG-012 | Price/info replies from `best2info` | OK | TODO |
| REG-013 | Live-1953 form corrections: uppercase name, on-site no-extras, phone-confirmation yes, paid notification date | OK | TODO |
| REG-014 | Live-1953 post-booking bath boundary: bathhouse info, generic new booking, clean service correction | OK | TODO |
| REG-015 | Live-19:09 post-booking service context, current-booking DB summary, general gazebo photo request, confirmation abort | OK | TODO |
