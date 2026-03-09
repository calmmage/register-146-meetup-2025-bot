# PRD 01: Event Data Model

## Summary

Introduce an `Event` Pydantic model and a corresponding MongoDB `events` collection to replace all hardcoded event metadata currently scattered across `app.py` and `router.py`. This is the foundational change that all other PRDs depend on.

## Problem

Event data is currently hardcoded in multiple parallel dictionaries and an enum:

```python
# app.py
class TargetCity(Enum):           # City identifiers
    PERM = "Пермь"
    ...
ENABLED_CITIES = { ... }          # Which cities accept registrations

# router.py
date_of_event = { ... }           # Display dates ("29 Марта, Сб")
event_dates = { ... }             # datetime objects for comparison
time_of_event = { ... }           # Event times
venue_of_event = { ... }          # Venue names
address_of_event = { ... }        # Venue addresses
padezhi = { ... }                 # City names in prepositional case

# payment.py
payment_formula = "..."           # Hardcoded per-city pricing formulas
year_price_map = { ... }          # Hardcoded per-year pricing
```

Adding a new event requires modifying code in 3+ files. Old events accumulate in the codebase. There is no way to manage events at runtime.

## Solution

### Event Model

```python
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict
from bson import ObjectId


class EventStatus(str, Enum):
    UPCOMING = "upcoming"       # Registration open, event in the future
    REGISTRATION_CLOSED = "registration_closed"  # Event upcoming but reg closed
    PASSED = "passed"           # Event has occurred
    ARCHIVED = "archived"       # Old event, hidden from users


class PricingType(str, Enum):
    FIXED_BY_YEAR = "fixed_by_year"   # Price map by graduation year
    FORMULA = "formula"                # Formula-based (e.g. base + rate * delta)
    FREE = "free"                      # No payment required


class Event(BaseModel):
    """Represents a single meetup event."""

    # Identity
    name: str                                    # e.g. "Москва (Весенняя встреча 2026)"
    city: str                                    # City name, e.g. "Москва"
    city_prepositional: str                      # e.g. "Москве" (for "в Москве")

    # Schedule
    date: datetime                               # Event date+time for comparison
    date_display: str                            # Human-readable, e.g. "21 Марта, Сб"
    time_display: str                            # e.g. "18:00"

    # Venue
    venue: Optional[str] = None                  # e.g. "People Loft"
    address: Optional[str] = None                # Full address string

    # Status & visibility
    status: EventStatus = EventStatus.UPCOMING
    enabled: bool = True                         # Can users register?

    # Pricing
    pricing_type: PricingType = PricingType.FIXED_BY_YEAR
    year_price_map: Optional[Dict[int, int]] = None      # {2025: 1300, 2024: 1300, ...}
    price_formula_base: Optional[int] = None              # For formula pricing
    price_formula_rate: Optional[int] = None              # Per-year increment
    price_formula_reference_year: Optional[int] = None    # e.g. 2026
    free_for_types: list[str] = []                        # GraduateTypes that are free

    # Payment details
    payment_phone: Optional[str] = None          # Override global payment phone
    payment_name: Optional[str] = None           # Override global payment name

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        extra = "ignore"
```

### MongoDB Collection

- **Collection name**: `events`
- **Indexes**:
  - `status` (for filtering active events)
  - `date` (for sorting by date)
  - `city` (for lookups)

### App Class Changes

Add to `App`:

```python
class App:
    events_collection_name = "events"

    @property
    def events_col(self):
        if self._events_col is None:
            self._events_col = get_database().get_collection(self.events_collection_name)
        return self._events_col

    async def get_active_events(self) -> list[dict]:
        """Get all events that are upcoming or have open registration."""
        cursor = self.events_col.find({
            "status": {"$in": ["upcoming", "registration_closed"]},
            "enabled": True,
        }).sort("date", 1)
        return await cursor.to_list(length=None)

    async def get_event_by_id(self, event_id: str) -> Optional[dict]:
        """Get a single event by its MongoDB _id."""
        from bson import ObjectId
        return await self.events_col.find_one({"_id": ObjectId(event_id)})

    async def get_event_by_city_and_date(self, city: str, date: datetime) -> Optional[dict]:
        """Find an event matching city and date."""
        return await self.events_col.find_one({"city": city, "date": date})

    async def get_all_events(self) -> list[dict]:
        """Get all events (for admin)."""
        cursor = self.events_col.find().sort("date", -1)
        return await cursor.to_list(length=None)

    async def create_event(self, event: Event) -> str:
        """Create a new event. Returns the inserted _id as string."""
        data = event.model_dump()
        result = await self.events_col.insert_one(data)
        return str(result.inserted_id)

    async def update_event(self, event_id: str, updates: dict) -> bool:
        """Update event fields. Returns True if modified."""
        from bson import ObjectId
        updates["updated_at"] = datetime.now()
        result = await self.events_col.update_one(
            {"_id": ObjectId(event_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    def is_event_passed(self, event: dict) -> bool:
        """Check if an event's date has passed."""
        return datetime.now() > event["date"]

    def calculate_event_payment(self, event: dict, graduation_year: int, graduate_type: str) -> tuple:
        """Calculate payment for an event based on its pricing config."""
        # Free for specified types
        if graduate_type in event.get("free_for_types", []):
            return 0, 0, 0, 0

        pricing_type = event.get("pricing_type", "fixed_by_year")

        if pricing_type == "free":
            return 0, 0, 0, 0
        elif pricing_type == "fixed_by_year":
            year_map = event.get("year_price_map", {})
            # Convert string keys to int if needed
            amount = year_map.get(graduation_year, year_map.get(str(graduation_year), 0))
            return amount, 0, amount, amount
        elif pricing_type == "formula":
            base = event.get("price_formula_base", 0)
            rate = event.get("price_formula_rate", 0)
            ref_year = event.get("price_formula_reference_year", 2026)
            amount = base + rate * (ref_year - graduation_year)
            return amount, 0, amount, amount

        return 0, 0, 0, 0
```

### Registration Model Changes

Update `RegisteredUser` to include an event reference:

```python
class RegisteredUser(BaseModel):
    full_name: str
    graduation_year: int
    class_letter: str
    target_city: TargetCity              # Kept for backward compat
    event_id: Optional[str] = None       # NEW: reference to Event document
    user_id: Optional[int] = None
    username: Optional[str] = None
    graduate_type: GraduateType = GraduateType.GRADUATE
```

### Router Refactoring

Replace all hardcoded dicts in `router.py`:

**Before:**
```python
date_of_event = {
    TargetCity.PERM: "29 Марта, Сб",
    ...
}

def is_event_passed(city: TargetCity) -> bool:
    today = datetime.now()
    return today > event_dates[city]
```

**After:**
```python
# All event data loaded from DB at handler level

async def get_available_events(app: App) -> list[dict]:
    """Get events available for registration."""
    events = await app.get_active_events()
    return [e for e in events if not app.is_event_passed(e)]
```

Key changes in router:
1. `start_handler` - Load events from DB, show available ones
2. `register_user` - City selection from active events, store `event_id` on registration
3. `info_handler` - Build info text from Event documents
4. `status_handler` - Look up event details by `event_id` on each registration
5. `cancel_registration_handler` - No change needed (works by user_id + city)

### Payment Router Refactoring

Replace hardcoded pricing in `payment.py`:
- Load the `Event` document for the user's registration
- Use `app.calculate_event_payment()` with the event's pricing config
- Display payment formula from event data

## Migration Strategy

1. Create `events` collection with 2026 events (PRD 02)
2. Update all router/handler code to read from events collection
3. Keep `TargetCity` enum for backward compat with existing registrations
4. New registrations get both `target_city` and `event_id`
5. Old registrations without `event_id` are handled gracefully (lookup by `target_city`)

## Files Changed

| File | Changes |
|------|---------|
| `app/app.py` | Add `Event`, `EventStatus`, `PricingType` models; add `events_col` property; add event CRUD methods; add `calculate_event_payment()`; remove `ENABLED_CITIES` dict |
| `app/router.py` | Remove all hardcoded dicts (`date_of_event`, `event_dates`, etc.); refactor all handlers to load event data from DB; make `is_event_passed` work with event dicts |
| `app/routers/payment.py` | Replace hardcoded pricing with `calculate_event_payment()` |
| `app/routers/crm.py` | Update `apply_message_templates()` to pull from event data |
| `app/routers/stats.py` | Update grouping/labeling to use event names from DB |
| `app/routers/feedback.py` | Update city selection to use active events |

## Testing

- Unit tests for `Event` model validation
- Unit tests for `calculate_event_payment()` with each pricing type
- Unit tests for `is_event_passed()` with various dates
- Integration test: create event, register user, verify event_id stored
- Regression: existing registrations without event_id still display correctly
