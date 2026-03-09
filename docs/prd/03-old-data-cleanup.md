# PRD 03: Old Data Cleanup

## Summary

Archive 2025 events and their associated registrations so that users see a clean slate for the 2026 season. The old Perm Summer 2025 registration visible in the screenshot should no longer appear in `/status`.

## Problem

1. A user has a stale registration for "Пермь (Летняя встреча 2025)" with payment status "declined". This shows up in `/status` even though the event was in August 2025.
2. All 2025 events (Moscow, Perm, SPb, Belgrade, Perm Summer 2025) are hardcoded and passed. They clutter the user experience.
3. The `TargetCity` enum contains 5 entries from 2025 that are no longer relevant.

## Solution

### Migration: `archive_2025_events`

Create a migration (using the framework from PRD 02) that:

1. **Creates Event documents for all 2025 events** with `status=EventStatus.ARCHIVED`
   - This preserves the historical record in the new schema
   - Events: Moscow (Apr 5), Perm (Mar 29), SPb (Apr 5), Belgrade (Apr 5), Perm Summer (Aug 2)

2. **Links existing registrations to their archived events**
   - For each registration with a `target_city` matching a 2025 event, set `event_id` to the corresponding archived Event document

3. **Does NOT delete registrations**
   - Registrations are preserved in the `registered_users` collection
   - They simply won't appear in active views because their events are archived

```python
async def archive_2025_events(app: App):
    """Create archived Event documents for 2025 events and link registrations."""

    old_events = [
        {
            "name": "Пермь (Весенняя встреча 2025)",
            "city": "Пермь",
            "city_prepositional": "Перми",
            "date": datetime(2025, 3, 29),
            "date_display": "29 Марта, Сб",
            "time_display": "17:00",
            "venue": "Пермское бистро",
            "address": "ул. Сибирская, 8",
            "status": "archived",
            "enabled": False,
            "target_city_value": "Пермь",  # For matching registrations
        },
        {
            "name": "Москва (Весенняя встреча 2025)",
            "city": "Москва",
            "city_prepositional": "Москве",
            "date": datetime(2025, 4, 5),
            "date_display": "5 Апреля, Сб",
            "time_display": "18:00",
            "venue": "People Loft",
            "address": "1-я ул. Энтузиастов, 12, метро Авиамоторная",
            "status": "archived",
            "enabled": False,
            "target_city_value": "Москва",
        },
        {
            "name": "Санкт-Петербург (Весенняя встреча 2025)",
            "city": "Санкт-Петербург",
            "city_prepositional": "Санкт-Петербурге",
            "date": datetime(2025, 4, 5),
            "date_display": "5 Апреля, Сб",
            "time_display": "17:00",
            "venue": "Family Loft",
            "address": "Кожевенная линия, 34, Метро горный институт",
            "status": "archived",
            "enabled": False,
            "target_city_value": "Санкт-Петербург",
        },
        {
            "name": "Белград (Весенняя встреча 2025)",
            "city": "Белград",
            "city_prepositional": "Белграде",
            "date": datetime(2025, 4, 5),
            "date_display": "5 Апреля, Сб",
            "time_display": "Уточняется",
            "venue": "Уточняется",
            "address": "Уточняется",
            "status": "archived",
            "enabled": False,
            "target_city_value": "Белград",
        },
        {
            "name": "Пермь (Летняя встреча 2025)",
            "city": "Пермь",
            "city_prepositional": "Перми",
            "date": datetime(2025, 8, 2),
            "date_display": "2 Августа, Сб",
            "time_display": "18:00-24:00",
            "venue": 'База "Чайка", Беседка 11',
            "address": "г. Пермь, ул. Встречная 33",
            "status": "archived",
            "enabled": False,
            "target_city_value": "Пермь (Летняя встреча 2025)",
        },
    ]

    for event_data in old_events:
        target_city_value = event_data.pop("target_city_value")

        # Insert the archived event
        existing = await app.events_col.find_one({
            "name": event_data["name"],
            "status": "archived",
        })
        if existing:
            event_id = str(existing["_id"])
        else:
            result = await app.events_col.insert_one(event_data)
            event_id = str(result.inserted_id)

        # Link existing registrations to this archived event
        await app.collection.update_many(
            {"target_city": target_city_value, "event_id": {"$exists": False}},
            {"$set": {"event_id": event_id}}
        )
```

### Router Changes: Filter by Active Events Only

Update `/status` handler to only show registrations linked to non-archived events:

```python
async def status_handler(message: Message, app: App):
    # Get user registrations
    registrations = await app.get_user_registrations(user_id)

    # Filter to only show registrations for active (non-archived) events
    active_registrations = []
    archived_registrations = []
    for reg in registrations:
        if reg.get("event_id"):
            event = await app.get_event_by_id(reg["event_id"])
            if event and event.get("status") != "archived":
                active_registrations.append(reg)
            else:
                archived_registrations.append(reg)
        else:
            # Legacy registration without event_id - treat as archived
            archived_registrations.append(reg)

    # Show only active registrations
    # Optionally mention archived ones with a brief note
    if archived_registrations and not active_registrations:
        # User only has old registrations
        # Show new events instead
        ...
```

### TargetCity Enum Cleanup

The `TargetCity` enum is kept but simplified. Old city values remain for DB compatibility but are not used in new flows:

```python
class TargetCity(Enum):
    """Legacy city enum. New events use the Event model directly."""
    PERM = "Пермь"
    MOSCOW = "Москва"
    SAINT_PETERSBURG = "Санкт-Петербург"
    BELGRADE = "Белград"
    PERM_SUMMER_2025 = "Пермь (Летняя встреча 2025)"
```

The enum remains so that existing code referencing `TargetCity.MOSCOW.value` for database queries doesn't break. New code should reference events by `event_id` rather than city enum values.

## User Experience After Cleanup

### /status (user with old registration only)
**Before:**
```
📋 Ваши регистрации:
🏙️ Город: Пермь (Летняя встреча 2025) (2 Августа, Сб - встреча уже прошла)
👤 ФИО: П п
🎓 Выпуск: 1996 В
💰 Статус оплаты: ❌ declined

Все встречи уже прошли. Спасибо, что были с нами! 🎓
```

**After:**
```
У вас нет активных регистраций.

📅 Ближайшие встречи:
- Москва (21 Марта, Сб)
- Санкт-Петербург (28 Марта, Сб)
- Пермь (28 Марта, Сб)

Используйте /start для регистрации на встречу.
```

### /start (user with old registration)
User is treated as a new user for the 2026 events. Their old registration data (name, year, class) can be pre-filled for convenience.

## File Changes

| File | Changes |
|------|---------|
| `app/migrations.py` | Add `archive_2025_events` migration |
| `app/router.py` | Update `status_handler` to filter archived registrations; update `start_handler` to pre-fill from old data |
| `app/routers/stats.py` | Add ability to filter stats by event/season |

## Testing

- Test migration creates 5 archived events
- Test migration links existing registrations to archived events
- Test `/status` hides archived registrations
- Test `/start` shows new events for users with only old registrations
- Test pre-fill of user data from old registrations
- Test that old registration data is still accessible for admin export

## Data Preservation

No data is deleted. The migration only:
1. Creates new `Event` documents with `status=archived`
2. Adds `event_id` field to existing registration documents

Original registration data, payment records, and event logs are all preserved for historical reference and admin export.
