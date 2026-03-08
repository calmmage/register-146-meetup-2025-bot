# Plus-One Support — Implementation Plan

## Summary

Allow registrants to bring additional guests (significant others, friends). Guests are stored as a nested list on the main registration document. Pricing supports two admin-configurable strategies. Max guests per event is configurable.

---

## Data Model Changes

### 1. New `GuestInfo` model (`app/app.py`)

```python
class GuestInfo(BaseModel):
    full_name: str                        # Required, same validation as main registrant
    relationship: str                     # e.g. "супруг(а)", "друг/подруга", "коллега", "другое"
    payment_amount: Optional[int] = None  # Calculated price for this guest
```

### 2. New `PlusOnePricingStrategy` enum (`app/app.py`)

```python
class PlusOnePricingStrategy(str, Enum):
    SAME_AS_REGISTRANT = "same_as_registrant"          # Guest pays same as registrant
    SAME_WITH_MINIMUM = "same_with_minimum"             # Same, but not less than min_guest_price
```

### 3. Extend `RegisteredUser` model

Add field:
```python
guests: List[GuestInfo] = []
```

### 4. Event-level configuration (new dict in `router.py` or `app.py`)

```python
plus_one_config = {
    TargetCity.PERM_SUMMER_2025: {
        "enabled": True,
        "max_guests": 2,
        "pricing_strategy": PlusOnePricingStrategy.SAME_WITH_MINIMUM,
        "min_guest_price": 1500,  # Only used when strategy is SAME_WITH_MINIMUM
    },
    # Other cities default to disabled
}
```

### 5. Data storage recommendation: **Nested list**

Guests stored as `guests: [GuestInfo, ...]` inside `RegisteredUser`. Reasons:
- Guests don't have independent Telegram accounts — no reason for separate docs
- Payment is handled together with the registrant
- Simpler queries, exports, and admin views
- No orphan records to worry about

---

## Registration Flow Changes (`app/router.py`)

### New FSM states

```python
class RegistrationStates(StatesGroup):
    # ... existing states ...
    ask_plus_one = State()              # "Want to bring someone?"
    guest_name = State()                # Collect guest name
    guest_relationship = State()        # Collect relationship
    ask_another_guest = State()         # "Add another guest?"
```

### Flow (inserted after graduation year / class letter, before payment)

1. **Ask plus-one** — "Хотите зарегистрировать кого-то с собой? (+1)"
   - Show only if `plus_one_config[city].enabled` and guest count < max
   - Buttons: "Да" / "Нет, продолжить"

2. **Guest name** — "Введите имя и фамилию гостя"
   - Same Russian-name validation as main registrant

3. **Guest relationship** — "Кем вам приходится гость?"
   - Inline buttons: "Супруг(а)", "Друг/Подруга", "Коллега", "Другое"
   - If "Другое" → free text input

4. **Calculate guest price** — Apply pricing strategy:
   - `SAME_AS_REGISTRANT`: guest_price = registrant_price
   - `SAME_WITH_MINIMUM`: guest_price = max(registrant_price, min_guest_price)

5. **Confirm guest** — "Гость: {name} ({relationship}). Стоимость: {price} руб."

6. **Ask another?** — If guest_count < max_guests:
   - "Хотите добавить ещё гостя?" → loop back to step 2
   - Otherwise proceed to payment

7. **Payment summary** — Show total: registrant_price + sum(guest_prices)

---

## Payment Changes (`app/routers/payment.py`)

### Modified payment message

- Show itemized breakdown:
  ```
  Ваш взнос: 1500 руб
  Гость (Анна Иванова): 1500 руб
  Итого: 3000 руб
  ```
- Total payment expected = registrant + all guests
- Admin sees guest details in the payment validation message

### Admin payment validation

- Show guest info alongside registrant in the events chat message
- Payment confirmation applies to the entire registration (registrant + guests)

---

## Export Changes (`app/export.py`)

- Add columns for guests (e.g. `guest_1_name`, `guest_1_relationship`, `guest_1_price`, `guest_2_name`, ...)
- Or add a single `guests` column with formatted text like "Анна Иванова (супруга, 1500₽)"

---

## Admin Visibility (`app/routers/admin.py`, `app/routers/stats.py`)

- Stats should include guest counts (total registrations vs total people including guests)
- Admin user info should show guest list

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/app.py` | Add `GuestInfo`, `PlusOnePricingStrategy`, extend `RegisteredUser` |
| `app/router.py` | Add FSM states, plus-one flow, pricing logic, event config |
| `app/routers/payment.py` | Itemized totals, guest info in admin messages |
| `app/routers/admin.py` | Show guests in user info |
| `app/routers/stats.py` | Include guest counts |
| `app/export.py` | Add guest columns to spreadsheet export |
| `tests/` | New tests for guest registration, pricing strategies |

---

## Edge Cases to Handle

1. **User cancels registration mid-guest-flow** — guests already entered should be discarded (only save when full registration completes)
2. **User re-registers** (edits existing registration) — should be able to modify guest list
3. **Free events** (SPb, Belgrade, teachers, organizers) — guests should also be free
4. **Deletion** — when registration is deleted, guests go with it (automatic with nested list)
5. **Max guests = 0 or config missing** — treat as plus-one disabled for that event
