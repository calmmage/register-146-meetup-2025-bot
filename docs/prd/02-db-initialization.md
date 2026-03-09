# PRD 02: Database Initialization & Event Seeding

## Summary

On first startup with the new Event model, seed the MongoDB `events` collection with three 2026 meetup events. Implement an idempotent migration mechanism so seeding runs exactly once and doesn't duplicate events on subsequent restarts.

## Problem

The bot currently has no events collection. When PRD 01's code lands, the bot will have no events to show. We need a reliable way to populate initial event data and support future migrations.

## Solution

### Initial Events to Seed

#### 1. Moscow - Spring 2026
```python
Event(
    name="Москва (Весенняя встреча 2026)",
    city="Москва",
    city_prepositional="Москве",
    date=datetime(2026, 3, 21, 18, 0),
    date_display="21 Марта, Сб",
    time_display="18:00",
    venue=None,          # TBD - admin can update later
    address=None,        # TBD
    status=EventStatus.UPCOMING,
    enabled=True,
    pricing_type=PricingType.FORMULA,
    price_formula_base=1000,
    price_formula_rate=200,
    price_formula_reference_year=2026,
    free_for_types=["TEACHER", "ORGANIZER"],
)
```

#### 2. Saint Petersburg - Spring 2026
```python
Event(
    name="Санкт-Петербург (Весенняя встреча 2026)",
    city="Санкт-Петербург",
    city_prepositional="Санкт-Петербурге",
    date=datetime(2026, 3, 28, 17, 0),
    date_display="28 Марта, Сб",
    time_display="17:00",
    venue=None,          # TBD
    address=None,        # TBD
    status=EventStatus.UPCOMING,
    enabled=True,
    pricing_type=PricingType.FREE,
    free_for_types=[],   # Free for everyone
)
```

#### 3. Perm - Spring 2026
```python
Event(
    name="Пермь (Весенняя встреча 2026)",
    city="Пермь",
    city_prepositional="Перми",
    date=datetime(2026, 3, 28, 17, 0),
    date_display="28 Марта, Сб",
    time_display="17:00",
    venue=None,          # TBD
    address=None,        # TBD
    status=EventStatus.UPCOMING,
    enabled=True,
    pricing_type=PricingType.FORMULA,
    price_formula_base=500,
    price_formula_rate=100,
    price_formula_reference_year=2026,
    free_for_types=["TEACHER", "ORGANIZER"],
)
```

**Note on pricing**: The 2025 pricing formulas were `1000 + 200*(2025-year)` for Moscow and `500 + 100*(2025-year)` for Perm. We carry the same structure forward with `reference_year=2026`. SPb was free in 2025 and remains free. Admins can adjust pricing via the admin event management flow (PRD 04).

### Migration Mechanism

Use a `migrations` collection to track which migrations have run:

```python
MIGRATIONS_COLLECTION = "migrations"

class Migration:
    """Tracks applied database migrations."""
    name: str           # Unique migration identifier
    applied_at: datetime

async def run_migrations(app: App):
    """Run all pending migrations in order."""
    migrations_col = get_database().get_collection(MIGRATIONS_COLLECTION)

    for migration in MIGRATION_REGISTRY:
        existing = await migrations_col.find_one({"name": migration.name})
        if existing:
            logger.debug(f"Migration '{migration.name}' already applied, skipping.")
            continue

        logger.info(f"Applying migration: {migration.name}")
        await migration.apply(app)
        await migrations_col.insert_one({
            "name": migration.name,
            "applied_at": datetime.now(),
        })
        logger.info(f"Migration '{migration.name}' applied successfully.")
```

### Migration: `seed_2026_spring_events`

```python
async def seed_2026_spring_events(app: App):
    """Seed the three 2026 spring events."""
    events = [
        # Moscow, SPb, Perm event dicts as defined above
    ]
    for event_data in events:
        # Double-check no duplicate (belt + suspenders)
        existing = await app.events_col.find_one({
            "city": event_data["city"],
            "date": event_data["date"],
        })
        if not existing:
            await app.events_col.insert_one(event_data)
            logger.info(f"Seeded event: {event_data['name']}")
        else:
            logger.info(f"Event already exists: {event_data['name']}, skipping.")
```

### Integration with App Startup

Update `app.startup()`:

```python
async def startup(self):
    """Run startup tasks."""
    logger.info("Running app startup tasks...")

    # Initialize collections
    _ = self.collection
    _ = self.event_logs
    _ = self.deleted_users
    _ = self.events_col

    # Run database migrations (includes seeding)
    await run_migrations(self)

    # Existing database fixes
    fix_results = await self._fix_database()
    ...

    # Auto-update event statuses (mark passed events)
    await self._update_event_statuses()
```

### Auto-Update Event Statuses

On every startup, automatically mark events whose date has passed:

```python
async def _update_event_statuses(self):
    """Mark events as 'passed' if their date is in the past."""
    now = datetime.now()
    result = await self.events_col.update_many(
        {
            "date": {"$lt": now},
            "status": {"$in": ["upcoming", "registration_closed"]},
        },
        {"$set": {"status": "passed", "updated_at": now}}
    )
    if result.modified_count > 0:
        logger.info(f"Marked {result.modified_count} events as passed.")
```

## File Changes

| File | Changes |
|------|---------|
| `app/app.py` | Add `_events_col`, `events_col` property, `_update_event_statuses()`, update `startup()` |
| `app/migrations.py` | **NEW** - Migration framework + `seed_2026_spring_events` migration |

## Testing

- Test that `seed_2026_spring_events` creates exactly 3 events
- Test that running it twice doesn't create duplicates (idempotency)
- Test that `_update_event_statuses` correctly marks past events
- Test that `run_migrations` skips already-applied migrations
- Test startup flow end-to-end with empty database

## Rollback

If needed, simply drop the `events` collection and the migration record:
```js
db.events.drop()
db.migrations.deleteOne({name: "seed_2026_spring_events"})
```
The next startup will re-seed.
