# PRD 04: Admin Event Management

## Summary

Add admin-only bot commands to create, edit, enable/disable, and archive events directly through Telegram. This eliminates the need to modify code for each new season of meetups.

## Problem

Currently, adding or modifying events requires:
1. Editing `TargetCity` enum in `app.py`
2. Adding entries to 6+ hardcoded dicts in `router.py`
3. Updating pricing logic in `payment.py`
4. Deploying new code

The user explicitly requested: "чтобы можно было новые встречи напрямую через бот делать" (to be able to create new meetups directly through the bot).

## Solution

### New Admin Commands

#### `/create_event` - Guided event creation flow

A multi-step conversational flow using FSM states:

```
Admin: /create_event

Bot: 🏙️ В каком городе будет встреча?
     Введите название города (например, "Москва"):

Admin: Казань

Bot: 📝 Как назвать встречу?
     Предлагаю: "Казань (Весенняя встреча 2026)"
     Или введите своё название:

Admin: [accepts suggestion or types custom name]

Bot: 🗓️ Укажите дату встречи (ДД.ММ.ГГГГ):

Admin: 15.05.2026

Bot: 🕐 Укажите время начала (например, "18:00"):

Admin: 18:00

Bot: 📍 Укажите место проведения (или "пропустить"):

Admin: пропустить

Bot: 📍 Укажите адрес (или "пропустить"):

Admin: пропустить

Bot: 💰 Выберите тип оплаты:
     [Формула] [Фиксированная по годам] [Бесплатно]

Admin: Формула

Bot: 💰 Укажите базовую стоимость (в рублях):

Admin: 500

Bot: 💰 Укажите надбавку за каждый год выпуска:

Admin: 100

Bot: 🎓 Для каких типов участников бесплатно?
     [Учителя] [Организаторы] [Никто] [Учителя + Организаторы]

Admin: Учителя + Организаторы

Bot: ✅ Новая встреча создана!

     📋 Казань (Весенняя встреча 2026)
     🏙️ Город: Казань
     📆 Дата: 15 Мая, Пт
     🕐 Время: 18:00
     📍 Место: Не указано
     💰 Оплата: 500 + 100 × (2026 − год выпуска)
     🎓 Бесплатно для: Учителя, Организаторы
     📊 Статус: Открыта для регистрации
```

#### `/manage_events` - Event management dashboard

```
Admin: /manage_events

Bot: 📋 Управление встречами:

     Активные:
     1. Москва (21 Марта, Сб) - 15 регистраций
     2. Санкт-Петербург (28 Марта, Сб) - 8 регистраций
     3. Пермь (28 Марта, Сб) - 12 регистраций

     [Создать новую] [Показать архив]

Admin: [selects event #1]

Bot: 📋 Москва (Весенняя встреча 2026)
     📆 21 Марта, Сб | 🕐 18:00
     📍 Не указано
     💰 Формула: 1000 + 200 × (2026 − год)
     📊 15 регистраций (5 оплачено)

     [Редактировать] [Закрыть регистрацию] [Архивировать]

Admin: Редактировать

Bot: Что изменить?
     [Название] [Дата] [Время] [Место] [Адрес] [Оплата] [Назад]
```

### FSM States

```python
class EventManagementStates(StatesGroup):
    # Create flow
    waiting_for_city = State()
    waiting_for_name = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_venue = State()
    waiting_for_address = State()
    waiting_for_pricing_type = State()
    waiting_for_price_base = State()
    waiting_for_price_rate = State()
    waiting_for_free_types = State()
    confirm_creation = State()

    # Edit flow
    selecting_event = State()
    selecting_field = State()
    waiting_for_new_value = State()
```

### New Router File

Create `app/routers/events.py`:

```python
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from botspot.utils import is_admin
from loguru import logger

from app.app import App, Event, EventStatus, PricingType

events_router = Router()


@events_router.message(Command("create_event"))
async def create_event_handler(message: Message, state: FSMContext, app: App):
    """Start the event creation flow (admin only)."""
    if not await is_admin(message.from_user.id):
        await message.reply("Эта команда доступна только администраторам.")
        return
    # Begin guided flow...


@events_router.message(Command("manage_events"))
async def manage_events_handler(message: Message, state: FSMContext, app: App):
    """Show event management dashboard (admin only)."""
    if not await is_admin(message.from_user.id):
        await message.reply("Эта команда доступна только администраторам.")
        return
    # Show active events with registration counts...
```

### Admin Actions on Events

| Action | Description | Confirmation Required |
|--------|-------------|----------------------|
| Create | Full guided flow as above | Yes, summary shown before save |
| Edit field | Change any single field | No (immediate save) |
| Close registration | Set `enabled=False`, keep `status=upcoming` | Yes |
| Reopen registration | Set `enabled=True` | No |
| Archive | Set `status=archived`, `enabled=False` | Yes, warns about hiding registrations |
| Delete | Permanently remove event (only if 0 registrations) | Yes, double confirmation |

### Input Validation

- **City name**: Non-empty string, auto-generates `city_prepositional` with common rules (Москва→Москве, Пермь→Перми, etc.). Admin can override.
- **Date**: Accepts `DD.MM.YYYY` format, must be in the future for new events
- **Time**: Accepts `HH:MM` or `HH:MM-HH:MM` format
- **Price base/rate**: Positive integers
- **Event name**: Auto-suggested as `"{city} ({season} встреча {year})"` based on date

### City Prepositional Case Helper

```python
PREPOSITIONAL_RULES = {
    "Москва": "Москве",
    "Пермь": "Перми",
    "Санкт-Петербург": "Санкт-Петербурге",
    "Белград": "Белграде",
    "Казань": "Казани",
    "Новосибирск": "Новосибирске",
    "Екатеринбург": "Екатеринбурге",
}

def get_city_prepositional(city: str) -> str:
    """Get prepositional case for a city name, with fallback."""
    if city in PREPOSITIONAL_RULES:
        return PREPOSITIONAL_RULES[city]
    # Fallback: ask admin to provide it
    return None
```

When the automatic lookup fails, the bot asks the admin:
```
Bot: Не могу автоматически просклонять "Тбилиси".
     Как сказать "в ___"? (например, для Москвы → "Москве")
```

### Event Logging

All admin event management actions are logged to `event_logs`:

```python
await app.save_event_log(
    event_type="admin_event_action",
    data={
        "action": "create_event",  # or edit_event, close_registration, archive_event
        "event_id": event_id,
        "event_name": event_name,
        "changes": {...},  # For edits: {field: {old: ..., new: ...}}
    },
    user_id=admin_id,
    username=admin_username,
)
```

### Bot Commands Menu Update

Update the commands menu to include new admin commands:

```python
# In bot.py, admin commands section
admin_commands = [
    ("create_event", "Создать новую встречу"),
    ("manage_events", "Управление встречами"),
    # existing...
    ("export", "Экспорт данных"),
]
```

These commands should only be visible to admins (using `BotCommandScopeChat` for admin user IDs).

## File Changes

| File | Changes |
|------|---------|
| `app/routers/events.py` | **NEW** - Event management router with create/edit/archive flows |
| `app/bot.py` | Register `events_router`, update commands menu |
| `app/app.py` | Add helper methods for event stats (registration count per event) |

## Testing

- Test full create flow: city → name → date → time → venue → pricing → confirmation
- Test create flow cancellation at each step
- Test edit flow for each editable field
- Test close/reopen registration toggle
- Test archive with confirmation
- Test delete prevention when registrations exist
- Test admin-only access (non-admin gets rejection)
- Test date validation (past dates rejected for new events)
- Test pricing type switching (formula ↔ fixed ↔ free)
- Test city prepositional auto-generation and manual override

## Future Enhancements (out of scope)

- Event templates (copy settings from a previous event)
- Bulk event creation (e.g., "create events for Moscow, SPb, Perm with same settings")
- Scheduled registration open/close
- Event co-admins (per-event admin permissions)
