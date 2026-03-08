"""Admin event management router: /create_event and /manage_events commands."""

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.app import (
    App,
    CITY_PREPOSITIONAL_MAP,
    EventStatus,
    PricingType,
)
from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from app.user_interactions import ask_user_choice, ask_user_confirmation, ask_user_raw
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter

events_router = Router()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEASON_NAMES = {
    (3, 5): "Весенняя встреча",
    (6, 8): "Летняя встреча",
    (9, 11): "Осенняя встреча",
    (12, 2): "Зимняя встреча",
}


def _suggest_event_name(city: str, date: datetime) -> str:
    month = date.month
    for (start, end), name in SEASON_NAMES.items():
        if start <= end:
            if start <= month <= end:
                return f"{city} ({name} {date.year})"
        else:
            if month >= start or month <= end:
                return f"{city} ({name} {date.year})"
    return f"{city} (Встреча {date.year})"


def _format_pricing(event: dict) -> str:
    pricing_type = event.get("pricing_type", "free")
    if pricing_type == PricingType.FREE:
        return "Бесплатно"
    elif pricing_type == PricingType.FORMULA:
        base = event.get("price_formula_base", 0)
        rate = event.get("price_formula_rate", 0)
        ref = event.get("price_formula_reference_year", datetime.now().year)
        return f"{base} + {rate} x ({ref} - год выпуска)"
    elif pricing_type == PricingType.FIXED_BY_YEAR:
        return "Фиксированная по годам"
    return "Неизвестно"


def _format_event_summary(event: dict, reg_count: int = 0) -> str:
    lines = []
    lines.append(f"📋 <b>{event.get('name', 'Без названия')}</b>")
    lines.append(f"🏙️ Город: {event.get('city', '?')}")
    lines.append(f"📆 Дата: {event.get('date_display', '?')}")
    lines.append(f"🕐 Время: {event.get('time_display', '?')}")
    venue = event.get("venue") or "Не указано"
    address = event.get("address") or "Не указано"
    lines.append(f"📍 Место: {venue}")
    lines.append(f"📍 Адрес: {address}")
    lines.append(f"💰 Оплата: {_format_pricing(event)}")

    free_for = event.get("free_for_types", [])
    if free_for:
        type_names = {"TEACHER": "Учителя", "ORGANIZER": "Организаторы"}
        names = [type_names.get(t, t) for t in free_for]
        lines.append(f"🎓 Бесплатно для: {', '.join(names)}")

    # Guest settings
    if event.get("guests_enabled"):
        max_g = event.get("max_guests_per_person", 3)
        min_p = event.get("guest_price_minimum", 0)
        guest_info = f"до {max_g} чел."
        if min_p > 0:
            guest_info += f", мин. {min_p}₽"
        else:
            guest_info += ", цена = как у регистранта"
        lines.append(f"👥 Гости: {guest_info}")
    else:
        lines.append("👥 Гости: Нет")

    status_map = {
        "upcoming": "Открыта для регистрации",
        "registration_closed": "Регистрация закрыта",
        "passed": "Прошла",
        "archived": "В архиве",
    }
    status = event.get("status", "upcoming")
    enabled = event.get("enabled", False)
    status_text = status_map.get(status, status)
    if status == "upcoming" and not enabled:
        status_text = "Регистрация приостановлена"
    lines.append(f"📊 Статус: {status_text}")

    if reg_count > 0:
        lines.append(f"👥 Регистраций: {reg_count}")

    return "\n".join(lines)


MONTH_NAMES_RU = {
    1: "Января",
    2: "Февраля",
    3: "Марта",
    4: "Апреля",
    5: "Мая",
    6: "Июня",
    7: "Июля",
    8: "Августа",
    9: "Сентября",
    10: "Октября",
    11: "Ноября",
    12: "Декабря",
}

DAY_OF_WEEK_RU = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Вс",
}


def _make_date_display(dt: datetime) -> str:
    day_name = DAY_OF_WEEK_RU.get(dt.weekday(), "")
    month_name = MONTH_NAMES_RU.get(dt.month, "")
    return f"{dt.day} {month_name}, {day_name}"


# ---------------------------------------------------------------------------
# /create_event
# ---------------------------------------------------------------------------

@commands_menu.add_command(
    "create_event", "Создать новую встречу", visibility=Visibility.ADMIN_ONLY
)
@events_router.message(Command("create_event"), AdminFilter())
async def create_event_handler(message: Message, state: FSMContext, app: App):
    """Guided event creation flow (admin only)."""
    if not message.from_user:
        return

    # Step 1: City
    city_resp = await ask_user_raw(
        message.chat.id,
        '🏙️ В каком городе будет встреча?\nВведите название города (например, "Москва"):',
        state=state,
        timeout=None,
    )
    if not city_resp or not city_resp.text:
        await send_safe(message.chat.id, "Операция отменена.")
        return
    city = city_resp.text.strip()

    # Step 2: City prepositional
    city_prep = CITY_PREPOSITIONAL_MAP.get(city)
    if not city_prep:
        prep_resp = await ask_user_raw(
            message.chat.id,
            f'Не могу автоматически просклонять "{city}".\n'
            f'Как сказать "в ___"? (например, для Москвы → "Москве")',
            state=state,
            timeout=None,
        )
        if not prep_resp or not prep_resp.text:
            await send_safe(message.chat.id, "Операция отменена.")
            return
        city_prep = prep_resp.text.strip()

    # Step 3: Date
    date_resp = await ask_user_raw(
        message.chat.id,
        "🗓️ Укажите дату встречи (ДД.ММ.ГГГГ):",
        state=state,
        timeout=None,
    )
    if not date_resp or not date_resp.text:
        await send_safe(message.chat.id, "Операция отменена.")
        return

    try:
        event_date = datetime.strptime(date_resp.text.strip(), "%d.%m.%Y")
    except ValueError:
        await send_safe(message.chat.id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
        return

    # Step 4: Name suggestion
    suggested_name = _suggest_event_name(city, event_date)
    name_resp = await ask_user_raw(
        message.chat.id,
        f'📝 Как назвать встречу?\nПредлагаю: "{suggested_name}"\n'
        f'Нажмите Enter или введите своё название (или отправьте "ок" чтобы принять):',
        state=state,
        timeout=None,
    )
    if not name_resp or not name_resp.text:
        event_name = suggested_name
    else:
        text = name_resp.text.strip()
        if text.lower() in ("ок", "ok", "да", ""):
            event_name = suggested_name
        else:
            event_name = text

    # Step 5: Time
    time_resp = await ask_user_raw(
        message.chat.id,
        '🕐 Укажите время начала (например, "18:00" или "18:00-24:00"):',
        state=state,
        timeout=None,
    )
    if not time_resp or not time_resp.text:
        await send_safe(message.chat.id, "Операция отменена.")
        return
    time_display = time_resp.text.strip()

    # Parse hour for the event datetime
    try:
        hour = int(time_display.split(":")[0])
        minute = int(time_display.split(":")[1].split("-")[0]) if ":" in time_display else 0
        event_date = event_date.replace(hour=hour, minute=minute)
    except (ValueError, IndexError):
        pass  # Keep date without time if parsing fails

    # Step 6: Venue (optional)
    venue_resp = await ask_user_raw(
        message.chat.id,
        '📍 Укажите место проведения (или "пропустить"):',
        state=state,
        timeout=None,
    )
    venue = None
    if venue_resp and venue_resp.text:
        text = venue_resp.text.strip()
        if text.lower() not in ("пропустить", "skip", "-"):
            venue = text

    # Step 7: Address (optional)
    address_resp = await ask_user_raw(
        message.chat.id,
        '📍 Укажите адрес (или "пропустить"):',
        state=state,
        timeout=None,
    )
    address = None
    if address_resp and address_resp.text:
        text = address_resp.text.strip()
        if text.lower() not in ("пропустить", "skip", "-"):
            address = text

    # Step 8: Pricing type
    pricing_choice = await ask_user_choice(
        message.chat.id,
        "💰 Выберите тип оплаты:",
        choices={
            "formula": "Формула",
            "free": "Бесплатно",
        },
        state=state,
        timeout=None,
    )

    event_data = {
        "name": event_name,
        "city": city,
        "city_prepositional": city_prep,
        "date": event_date,
        "date_display": _make_date_display(event_date),
        "time_display": time_display,
        "venue": venue,
        "address": address,
        "status": EventStatus.UPCOMING,
        "enabled": True,
        "free_for_types": [],
    }

    if pricing_choice == "formula":
        base_resp = await ask_user_raw(
            message.chat.id,
            "💰 Укажите базовую стоимость (в рублях):",
            state=state,
            timeout=None,
        )
        if not base_resp or not base_resp.text:
            await send_safe(message.chat.id, "Операция отменена.")
            return
        try:
            price_base = int(base_resp.text.strip())
        except ValueError:
            await send_safe(message.chat.id, "❌ Введите число.")
            return

        rate_resp = await ask_user_raw(
            message.chat.id,
            "💰 Укажите надбавку за каждый год выпуска:",
            state=state,
            timeout=None,
        )
        if not rate_resp or not rate_resp.text:
            await send_safe(message.chat.id, "Операция отменена.")
            return
        try:
            price_rate = int(rate_resp.text.strip())
        except ValueError:
            await send_safe(message.chat.id, "❌ Введите число.")
            return

        event_data["pricing_type"] = PricingType.FORMULA
        event_data["price_formula_base"] = price_base
        event_data["price_formula_rate"] = price_rate
        event_data["price_formula_reference_year"] = event_date.year
    else:
        event_data["pricing_type"] = PricingType.FREE

    # Step 9: Free for types
    free_choice = await ask_user_choice(
        message.chat.id,
        "🎓 Для каких типов участников бесплатно?",
        choices={
            "teachers_organizers": "Учителя + Организаторы",
            "teachers": "Только учителя",
            "nobody": "Никто (все платят)",
        },
        state=state,
        timeout=None,
    )

    if free_choice == "teachers_organizers":
        event_data["free_for_types"] = ["TEACHER", "ORGANIZER"]
    elif free_choice == "teachers":
        event_data["free_for_types"] = ["TEACHER"]
    # else: empty list

    # Step 10: Guest settings
    guests_choice = await ask_user_choice(
        message.chat.id,
        "👥 Разрешить участникам приводить гостей (+1)?",
        choices={
            "yes": "Да",
            "no": "Нет",
        },
        state=state,
        timeout=None,
    )

    if guests_choice == "yes":
        event_data["guests_enabled"] = True

        max_guests_resp = await ask_user_raw(
            message.chat.id,
            "Максимальное количество гостей на человека (по умолчанию 3):",
            state=state,
            timeout=None,
        )
        if max_guests_resp and max_guests_resp.text:
            text = max_guests_resp.text.strip()
            try:
                event_data["max_guests_per_person"] = max(1, int(text))
            except ValueError:
                event_data["max_guests_per_person"] = 3
        else:
            event_data["max_guests_per_person"] = 3

        min_price_resp = await ask_user_raw(
            message.chat.id,
            "Минимальная цена за гостя в рублях (0 = такая же, как у регистранта):",
            state=state,
            timeout=None,
        )
        if min_price_resp and min_price_resp.text:
            text = min_price_resp.text.strip()
            try:
                event_data["guest_price_minimum"] = max(0, int(text))
            except ValueError:
                event_data["guest_price_minimum"] = 0
        else:
            event_data["guest_price_minimum"] = 0
    else:
        event_data["guests_enabled"] = False
        event_data["max_guests_per_person"] = 3
        event_data["guest_price_minimum"] = 0

    # Step 11: Confirmation
    summary = _format_event_summary(event_data)
    confirm = await ask_user_confirmation(
        message.chat.id,
        f"Создать встречу?\n\n{summary}",
        state=state,
    )

    if not confirm:
        await send_safe(message.chat.id, "Операция отменена.")
        return

    event_id = await app.create_event(event_data)
    logger.info(f"Admin {message.from_user.id} created event: {event_name} (id={event_id})")

    await app.save_event_log(
        event_type="admin_event_action",
        data={
            "action": "create_event",
            "event_id": event_id,
            "event_name": event_name,
        },
        user_id=message.from_user.id,
        username=message.from_user.username,
    )

    await send_safe(message.chat.id, f"✅ Встреча создана!\n\n{summary}")


# ---------------------------------------------------------------------------
# /manage_events
# ---------------------------------------------------------------------------

@commands_menu.add_command(
    "manage_events", "Управление встречами", visibility=Visibility.ADMIN_ONLY
)
@events_router.message(Command("manage_events"), AdminFilter())
async def manage_events_handler(message: Message, state: FSMContext, app: App):
    """Event management dashboard (admin only)."""
    if not message.from_user:
        return

    while True:
        # Build event list
        all_events = await app.get_all_events()

        active_events = [
            e for e in all_events if e.get("status") in ("upcoming", "registration_closed")
        ]
        archived_events = [
            e for e in all_events if e.get("status") in ("archived", "passed")
        ]

        # Build choices
        choices = {}
        if active_events:
            for ev in active_events:
                eid = str(ev["_id"])
                reg_count = await app.get_registration_count_for_event(eid)
                enabled_mark = "✅" if ev.get("enabled") else "⏸️"
                choices[eid] = (
                    f"{enabled_mark} {ev.get('city', '?')} "
                    f"({ev.get('date_display', '?')}) - {reg_count} рег."
                )

        choices["show_archive"] = f"📦 Архив ({len(archived_events)} встреч)"
        choices["done"] = "Готово"

        selection = await ask_user_choice(
            message.chat.id,
            "📋 Управление встречами:",
            choices=choices,
            state=state,
            timeout=None,
        )

        if selection == "done":
            await send_safe(message.chat.id, "Готово.")
            return

        if selection == "show_archive":
            if not archived_events:
                await send_safe(message.chat.id, "Архив пуст.")
                continue

            archive_text = "📦 <b>Архив встреч:</b>\n\n"
            for ev in archived_events[:20]:
                archive_text += f"• {ev.get('name', '?')} ({ev.get('date_display', '?')})\n"
            await send_safe(message.chat.id, archive_text)
            continue

        # User selected a specific event
        event = await app.get_event_by_id(selection)
        if not event:
            await send_safe(message.chat.id, "❌ Встреча не найдена.")
            continue

        reg_count = await app.get_registration_count_for_event(selection)
        summary = _format_event_summary(event, reg_count)

        action = await ask_user_choice(
            message.chat.id,
            f"{summary}\n\nЧто сделать?",
            choices={
                "edit": "Редактировать",
                "toggle": "Вкл/Выкл регистрацию",
                "archive": "Архивировать",
                "back": "Назад",
            },
            state=state,
            timeout=None,
        )

        if action == "back":
            continue

        if action == "toggle":
            new_enabled = not event.get("enabled", False)
            await app.update_event(selection, {"enabled": new_enabled})
            status_text = "включена" if new_enabled else "выключена"
            await send_safe(message.chat.id, f"Регистрация {status_text}.")
            await app.save_event_log(
                event_type="admin_event_action",
                data={
                    "action": "toggle_registration",
                    "event_id": selection,
                    "event_name": event.get("name"),
                    "new_enabled": new_enabled,
                },
                user_id=message.from_user.id,
                username=message.from_user.username,
            )
            continue

        if action == "archive":
            if reg_count > 0:
                confirm = await ask_user_confirmation(
                    message.chat.id,
                    f"⚠️ У этой встречи {reg_count} регистраций. "
                    f"После архивации они не будут видны пользователям. Продолжить?",
                    state=state,
                )
                if not confirm:
                    continue

            await app.update_event(
                selection,
                {"status": EventStatus.ARCHIVED, "enabled": False},
            )
            await send_safe(message.chat.id, "Встреча архивирована.")
            await app.save_event_log(
                event_type="admin_event_action",
                data={
                    "action": "archive_event",
                    "event_id": selection,
                    "event_name": event.get("name"),
                },
                user_id=message.from_user.id,
                username=message.from_user.username,
            )
            continue

        if action == "edit":
            field = await ask_user_choice(
                message.chat.id,
                "Что изменить?",
                choices={
                    "name": "Название",
                    "date": "Дата",
                    "time": "Время",
                    "venue": "Место",
                    "address": "Адрес",
                    "guests": "Настройки гостей",
                    "back": "Назад",
                },
                state=state,
                timeout=None,
            )

            if field == "back":
                continue

            if field == "name":
                resp = await ask_user_raw(
                    message.chat.id,
                    f"Текущее название: {event.get('name')}\nВведите новое:",
                    state=state,
                    timeout=None,
                )
                if resp and resp.text:
                    old_name = event.get("name")
                    await app.update_event(selection, {"name": resp.text.strip()})
                    await send_safe(message.chat.id, "✅ Название обновлено.")
                    await app.save_event_log(
                        event_type="admin_event_action",
                        data={
                            "action": "edit_event",
                            "event_id": selection,
                            "field": "name",
                            "old": old_name,
                            "new": resp.text.strip(),
                        },
                        user_id=message.from_user.id,
                        username=message.from_user.username,
                    )

            elif field == "date":
                resp = await ask_user_raw(
                    message.chat.id,
                    f"Текущая дата: {event.get('date_display')}\n"
                    f"Введите новую дату (ДД.ММ.ГГГГ):",
                    state=state,
                    timeout=None,
                )
                if resp and resp.text:
                    try:
                        new_date = datetime.strptime(resp.text.strip(), "%d.%m.%Y")
                        # Preserve time from existing date
                        old_date = event.get("date")
                        if old_date:
                            new_date = new_date.replace(
                                hour=old_date.hour, minute=old_date.minute
                            )
                        await app.update_event(
                            selection,
                            {
                                "date": new_date,
                                "date_display": _make_date_display(new_date),
                            },
                        )
                        await send_safe(message.chat.id, "✅ Дата обновлена.")
                    except ValueError:
                        await send_safe(
                            message.chat.id, "❌ Неверный формат. Используйте ДД.ММ.ГГГГ"
                        )

            elif field == "time":
                resp = await ask_user_raw(
                    message.chat.id,
                    f"Текущее время: {event.get('time_display')}\nВведите новое:",
                    state=state,
                    timeout=None,
                )
                if resp and resp.text:
                    await app.update_event(selection, {"time_display": resp.text.strip()})
                    await send_safe(message.chat.id, "✅ Время обновлено.")

            elif field == "venue":
                resp = await ask_user_raw(
                    message.chat.id,
                    f"Текущее место: {event.get('venue') or 'Не указано'}\nВведите новое:",
                    state=state,
                    timeout=None,
                )
                if resp and resp.text:
                    await app.update_event(selection, {"venue": resp.text.strip()})
                    await send_safe(message.chat.id, "✅ Место обновлено.")

            elif field == "address":
                resp = await ask_user_raw(
                    message.chat.id,
                    f"Текущий адрес: {event.get('address') or 'Не указано'}\nВведите новый:",
                    state=state,
                    timeout=None,
                )
                if resp and resp.text:
                    await app.update_event(selection, {"address": resp.text.strip()})
                    await send_safe(message.chat.id, "✅ Адрес обновлен.")

            elif field == "guests":
                current_enabled = event.get("guests_enabled", False)
                current_max = event.get("max_guests_per_person", 3)
                current_min = event.get("guest_price_minimum", 0)

                guest_action = await ask_user_choice(
                    message.chat.id,
                    f"Текущие настройки гостей:\n"
                    f"• Разрешены: {'Да' if current_enabled else 'Нет'}\n"
                    f"• Макс. гостей: {current_max}\n"
                    f"• Мин. цена: {current_min}₽\n\n"
                    f"Что изменить?",
                    choices={
                        "toggle": f"{'Выключить' if current_enabled else 'Включить'} гостей",
                        "max": "Изменить макс. количество",
                        "min_price": "Изменить мин. цену",
                        "back": "Назад",
                    },
                    state=state,
                    timeout=None,
                )

                if guest_action == "toggle":
                    new_enabled = not current_enabled
                    await app.update_event(selection, {"guests_enabled": new_enabled})
                    await send_safe(
                        message.chat.id,
                        f"✅ Гости {'включены' if new_enabled else 'выключены'}.",
                    )
                elif guest_action == "max":
                    resp = await ask_user_raw(
                        message.chat.id,
                        f"Текущий максимум: {current_max}\nВведите новый:",
                        state=state,
                        timeout=None,
                    )
                    if resp and resp.text:
                        try:
                            new_max = max(1, int(resp.text.strip()))
                            await app.update_event(selection, {"max_guests_per_person": new_max})
                            await send_safe(message.chat.id, f"✅ Максимум гостей: {new_max}.")
                        except ValueError:
                            await send_safe(message.chat.id, "❌ Введите число.")
                elif guest_action == "min_price":
                    resp = await ask_user_raw(
                        message.chat.id,
                        f"Текущая мин. цена: {current_min}₽\nВведите новую (0 = как у регистранта):",
                        state=state,
                        timeout=None,
                    )
                    if resp and resp.text:
                        try:
                            new_min = max(0, int(resp.text.strip()))
                            await app.update_event(selection, {"guest_price_minimum": new_min})
                            await send_safe(message.chat.id, f"✅ Мин. цена гостя: {new_min}₽.")
                        except ValueError:
                            await send_safe(message.chat.id, "❌ Введите число.")
