## In Progress

- [ ] Replace city-name routing with event_id routing [[actions/03-10-event-id-routing-refactor]]
  - [x] Step 1: Verify migration — all DB records have `event_id`
  - [x] Step 2: `app/app.py` — change DB filters from `target_city` to `event_id`, update method signatures
  - [x] Step 3: `app/router.py` — replace `city_for_db` with `event_id`, update duplicate checking
  - [x] Step 4: `app/routers/payment.py` — delete CITY_CODES, rewrite callback format, add old-format fallback
  - [ ] Step 5: `app/routers/stats.py` — switch aggregation pipelines to group by `event_id`
  - [ ] Step 6: `app/routers/crm.py` — remove city param from query calls
  - [ ] Step 7: `app/routers/events.py` — decouple from CITY_PREPOSITIONAL_MAP
  - [ ] Step 8: `app/export.py` — keep target_city as display, no routing changes
  - [ ] Step 9: Tests — update mock queries, make event_id required in test data
  - [ ] Step 10: Cleanup — remove CITY_PREPOSITIONAL_MAP, legacy fallbacks

## Done

- [x] Remove TargetCity enum — all cities are now plain strings (32e8e36)
