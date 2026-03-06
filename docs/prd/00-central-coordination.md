# Central PRD: Meetup Bot 2026 Update

## Overview

The Register 146 Meetup Bot needs a major update to support the 2026 season of alumni meetups. The current system has hardcoded event data (cities, dates, venues, pricing) scattered across multiple files (`app.py`, `router.py`, `payment.py`). All existing events are from 2025 and have passed. A stale registration from the old season is still visible to users.

This update introduces a proper **Event data model**, migrates all hardcoded event data into the database, seeds the DB with three new 2026 events, cleans up legacy data, and adds admin-only functionality to create/manage events directly through the bot.

## Goals

1. **Unblock users** - The bot currently shows "all events have passed" for everyone. New events need to be available immediately.
2. **Introduce Event model** - Replace scattered hardcoded dicts (`date_of_event`, `event_dates`, `time_of_event`, `venue_of_event`, `address_of_event`, `padezhi`, `ENABLED_CITIES`) with a single `Event` collection in MongoDB.
3. **Seed initial events** - On first startup with the new schema, create three events:
   - Moscow (March 21, 2026, Saturday)
   - Saint Petersburg (March 28, 2026, Saturday)
   - Perm (March 28, 2026, Saturday)
4. **Clean up old data** - Archive 2025 events and stale registrations so users start fresh.
5. **Admin event management** - Allow admins to create, edit, enable/disable, and archive events through the bot, eliminating code changes for future seasons.

## Component PRDs

| # | PRD | Scope | Depends On |
|---|-----|-------|------------|
| 1 | [01-event-data-model](./01-event-data-model.md) | New `Event` Pydantic model, MongoDB collection, migration of all hardcoded event data | - |
| 2 | [02-db-initialization](./02-db-initialization.md) | Startup seeding of 2026 events, schema migration logic | PRD 01 |
| 3 | [03-old-data-cleanup](./03-old-data-cleanup.md) | Archive 2025 events/registrations, clean stale user state | PRD 01 |
| 4 | [04-admin-event-management](./04-admin-event-management.md) | Admin bot commands to create/edit/manage events | PRD 01, 02 |

## Implementation Order

```
Phase 1: PRD 01 - Event data model
   └── Define Event model, create collection, refactor all code to read from DB
Phase 2: PRD 02 + 03 - DB init & cleanup (can be parallel)
   ├── Seed 2026 events on startup
   └── Archive old 2025 data
Phase 3: PRD 04 - Admin event management
   └── Bot commands for CRUD on events
```

## Key Design Decisions

### Event replaces TargetCity enum for runtime data
The `TargetCity` enum currently serves as both an identifier and a container for all event metadata (via parallel dicts). After migration:
- `TargetCity` enum can remain as a convenience for known cities, but the **source of truth** for active events is the `events` MongoDB collection.
- All dicts (`date_of_event`, `event_dates`, `time_of_event`, `venue_of_event`, `address_of_event`, `padezhi`, `ENABLED_CITIES`) are replaced by fields on the `Event` model.

### Registrations link to events by event_id
Currently registrations use `target_city` (a string) to link to events. After migration:
- New registrations will store an `event_id` field referencing the Event document.
- The `target_city` field is kept for display purposes and backward compatibility.

### Admin-only event creation via bot
New events are created through a guided bot conversation (admin-only), not by editing code. This supports the stated goal: "чтобы можно было новые встречи напрямую через бот делать."

## Affected Files

| File | Changes |
|------|---------|
| `app/app.py` | New `Event` model, new `events` collection, remove `ENABLED_CITIES`, new event CRUD methods |
| `app/router.py` | Replace all hardcoded dicts with DB queries, update `is_event_passed()`, update registration flow to reference events |
| `app/routers/payment.py` | Read pricing from Event model instead of hardcoded formulas |
| `app/routers/admin.py` | New admin commands for event management |
| `app/routers/crm.py` | Update template system to pull event data from DB |
| `app/routers/stats.py` | Update stats to work with dynamic events |
| `app/routers/feedback.py` | Update city references to use event data |

## Out of Scope (for now)

- Public event discovery/listing for non-registered users (beyond what `/info` already does)
- Recurring event templates
- Multi-language support
- Payment provider integration changes
- Automated event reminders/scheduling (the bot already has botspot scheduler, but automated reminders are not part of this PRD)

## Success Criteria

1. Users see three new 2026 events when they open the bot
2. Old 2025 registrations are archived and not shown to users
3. Admins can create a new event entirely through the bot without code changes
4. All existing functionality (registration, payment, export, stats, feedback) works with the new Event model
5. The `/status` command shows only current/future event registrations
