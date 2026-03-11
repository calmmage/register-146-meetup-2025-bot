Replace city-name-based routing with event_id-based routing across the codebase.

TargetCity enum was removed but city name strings still serve as routing keys — DB compound filters use {"user_id": X, "target_city": Y}, payment callbacks encode city names via CITY_CODES dict, stats aggregate by "$target_city". All 2026 events are database-driven, every registration already has event_id. City strings should only remain as denormalized display data.

---

## Context

- TargetCity enum removed in previous commit (32e8e36)
- All 2026 events live in `events` collection with full config (pricing, formula, early bird, prepositional name)
- New registrations already save `event_id`
- Existing migration in `app/migrations.py` backfills `event_id` for legacy records
- `target_city` stays in documents as denormalized display data (exports, templates, human readability)

## Approach

### Step 1: Verify migration
Confirm all DB records have `event_id` set. Existing migration handles `{"target_city": X, "event_id": {"$exists": False}}`.

### Step 2: `app/app.py` — core DB methods
- All 15+ `{"user_id": X, "target_city": Y}` filters → `{"user_id": X, "event_id": Y}`
- `save_registration_guests(city)` → `save_registration_guests(event_id)`
- `save_payment_info(city)` → `save_payment_info(event_id)`
- `update_payment_status(city)` → `update_payment_status(event_id)`
- `move_user_to_deleted(city)` → `move_user_to_deleted(event_id)`
- `delete_user_registration(city)` → `delete_user_registration(event_id)`
- `_get_users_base` — drop `city` param and `city_mapping`, keep only `event_id`
- `get_unpaid_users`, `get_paid_users`, `get_all_users`, `get_users_without_feedback` — remove `city` param
- `_fix_database` — query by event with `pricing_type: "free"` instead of hardcoded "Белград"
- `RegisteredUser.event_id` → required `str` (keep `target_city` as `Optional[str]` for display)
- `get_event_for_registration` — keep legacy fallback with deprecation log

### Step 3: `app/router.py` — registration flow
- Replace `city_for_db` with `event_id` everywhere
- Duplicate-check by `event_id` instead of city name
- `existing_cities` → `existing_event_ids`
- All downstream calls passing `city_for_db` → pass `event_id`

### Step 4: `app/routers/payment.py` — payment routing (heaviest change)
- Delete `CITY_CODES` / `CITY_CODES_REVERSE` dicts
- Callback data format: `confirm_payment_{user_id}_{event_id}_{amount}` (ObjectId is 24-char hex, no underscores)
- Simplify `parse_payment_callback_data`
- `process_payment(city)` → `process_payment(event_id)`
- `confirm_payment_callback` — parse event_id from callback, load city display name from event doc
- `decline_payment_callback` — same
- `payment_decline_reason_handler` — `decline_city` → `decline_event_id` in state
- `pay_handler` — select by event_id, display city from reg/event
- Add brief fallback for old-format callbacks (~1 week lifespan)

### Step 5: `app/routers/stats.py` — aggregation pipelines
- 10+ `$group: {"_id": "$target_city"}` → `$group: {"_id": "$event_id"}`
- Resolve display names from events collection after aggregation
- Replace `$match: {"target_city": {"$ne": "Белград"}}` with event_id-based exclusion
- Replace hardcoded city list with dynamic event loading
- `simplify_city` function → event-based grouping

### Step 6: `app/routers/crm.py` — notifications
- Keep `target_city` reads for `{city}` template variable
- Remove fallback city parameter from `get_unpaid_users` calls

### Step 7: `app/routers/events.py`
- `CITY_PREPOSITIONAL_MAP` usage during event creation — keep as convenience, no longer routing

### Step 8: `app/export.py`
- Keep `user["target_city"]` reads for export columns (display data)

### Step 9: Tests
- Update all mock DB queries to use event_id filters
- `RegisteredUser` construction — event_id becomes required
- Update callback data format in test fixtures

### Step 10: Cleanup
- Remove `CITY_PREPOSITIONAL_MAP` from app.py (lives in event docs now)
- Remove `city` param from `_get_users_base`
- Remove legacy fallback in `get_event_for_registration`

## Files to modify

Core (must ship together):
- `app/app.py`
- `app/router.py`
- `app/routers/payment.py`

Incremental:
- `app/routers/stats.py`
- `app/routers/crm.py`
- `app/routers/events.py`
- `app/export.py`
- `app/migrations.py`
- `tests/test_*.py`

## Backward compatibility
- `target_city` stays in documents as display data
- Old Telegram callback buttons get temporary fallback (check if parsed "event_id" matches old CITY_CODES format)
- Run migration before deploying to ensure all records have event_id

---

## Progress

### Done
- Step 1: Migration verified (32e8e36)
- Step 2: `app/app.py` — all DB filters, method signatures, `RegisteredUser.event_id` required (c1d93ca)
- Step 3: `app/router.py` — `event_id` routing, duplicate check, NoneType guard (c1d93ca)
- Step 4: `app/routers/payment.py` — CITY_CODES deleted, callback format, legacy fallback (c1d93ca)
- Step 5: `app/routers/stats.py` — all pipelines group by `$event_id`, dynamic event loading, `simplify_city` removed (a0b555b)
- Step 9 (partial): tests updated for steps 2-4 (c1d93ca)

### Production bugs fixed
- `existing_cities` NameError in `register_user` log — missed rename (8f96e7d)
- Moscow event not showing: city-name duplicate check collided 2025/2026 events → now uses event_id (c1d93ca)
- `calculate_event_payment` NoneType crash: added guard when `selected_event` is None (c1d93ca)

### Remaining

**Step 6: `app/routers/crm.py`** ✅ verified clean
- Already uses `event_id` params from step 2
- `target_city` reads are display-only (templates, user lists) — no changes needed

**Step 7: `app/routers/events.py`** ✅ verified clean
- `CITY_PREPOSITIONAL_MAP` used only for event creation convenience (not routing)
- No routing logic depends on city name

**Step 8: `app/export.py`** ✅ verified clean
- `target_city` reads are display data for export columns — no changes needed

**Step 9: Tests (remaining)**
- Any test files touching stats need event_id in fixtures
- crm/events/export tests already clean

**Step 10: Cleanup** (deferred, post-production stabilization)
- Remove `CITY_PREPOSITIONAL_MAP` from `app/app.py` (now in event docs)
- Remove `_LEGACY_CITY_CODES_REVERSE` from `payment.py` (after ~1 week in production)
- Remove legacy fallback in `get_event_for_registration` (app.py lines 274-278)
- Final grep: `target_city` should only appear in display/export contexts

## New features (separate from refactor)
- Admin `/wipe_registrations` command: select event → double confirm → export JSON dump → delete registrations
