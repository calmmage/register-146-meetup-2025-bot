from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardRemove,
    Message,
)
from dotenv import load_dotenv
from loguru import logger
from textwrap import dedent
from typing import Dict, List

from app.app import App, TargetCity, RegisteredUser, GraduateType
from app.routers.admin import admin_handler
from botspot import commands_menu
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe, is_admin

router = Router()
app = App()

# Load environment variables
load_dotenv()

# Dictionary to track log messages for each user
log_messages: Dict[int, List[Message]] = {}

date_of_event = {
    TargetCity.PERM: "29 Марта, Сб",
    TargetCity.MOSCOW: "5 Апреля, Сб",
    TargetCity.SAINT_PETERSBURG: "5 Апреля, Сб",
    TargetCity.BELGRADE: "5 Апреля, Сб",
}

padezhi = {
    TargetCity.PERM: "Перми",
    TargetCity.MOSCOW: "Москве",
    TargetCity.SAINT_PETERSBURG: "Санкт-Петербурге",
    TargetCity.BELGRADE: "Белграде",
}


async def handle_registered_user(message: Message, state: FSMContext, registration):
    """Handle interaction with already registered user"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Get all user registrations
    registrations = await app.get_user_registrations(message.from_user.id)

    # We always want to show the same consistent menu regardless of payment status
    # No special case for unpaid registration - everything is handled in the same interface

    if len(registrations) > 1:
        # User has multiple registrations
        info_text = "Вы зарегистрированы на встречи выпускников в нескольких городах:\n\n"

        for reg in registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)

            # Add payment status indicator
            payment_status = ""
            if city != TargetCity.SAINT_PETERSBURG.value and city != TargetCity.BELGRADE.value:
                status = reg.get("payment_status", "не оплачено")
                status_emoji = (
                    "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"
                )
                payment_status = f" - {status_emoji} {status}"

            info_text += f"• {city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'}){payment_status}\n"
            info_text += f"  ФИО: {reg['full_name']}\n"
            info_text += (
                f"  Год выпуска: {reg['graduation_year']}, Класс: {reg['class_letter']}\n\n"
            )

        info_text += "Что вы хотите сделать?"

        response = await ask_user_choice(
            message.chat.id,
            info_text,
            choices={
                "register_another": "Зарегистрироваться в другом городе",
                "manage": "Управлять регистрациями",
                "nothing": "Ничего, всё в порядке",
            },
            state=state,
            timeout=None,
        )

        if response == "register_another":
            await register_user(message, state, reuse_info=registration)
        elif response == "manage":
            await manage_registrations(message, state, registrations)
        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваши регистрации в силе. До встречи!",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        # User has only one registration
        reg = registration
        city = reg["target_city"]
        full_name = reg["full_name"]
        graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

        city_enum = next((c for c in TargetCity if c.value == city), None)

        # Check if payment is needed and not confirmed
        needs_payment = False
        if (
            city != TargetCity.SAINT_PETERSBURG.value
            and city != TargetCity.BELGRADE.value
            and graduate_type != GraduateType.TEACHER.value
            and reg.get("payment_status") != "confirmed"
        ):
            needs_payment = True

        # Payment status display
        payment_status = ""
        if (
            city != TargetCity.SAINT_PETERSBURG.value
            and city != TargetCity.BELGRADE.value
            and graduate_type != GraduateType.TEACHER.value
        ):
            status = reg.get("payment_status", "не оплачено")
            status_emoji = "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"
            payment_status = f"Статус оплаты: {status_emoji} {status}\n"

        info_text = dedent(
            f"""
            Вы зарегистрированы на встречу выпускников:
            
            ФИО: {reg["full_name"]}
            """
        )

        # Show different info based on graduate type
        if graduate_type == GraduateType.TEACHER.value:
            info_text += "Статус: Учитель\n"
        elif graduate_type == GraduateType.NON_GRADUATE.value:
            info_text += "Статус: Не выпускник\n"
        else:
            info_text += f"Год выпуска: {reg['graduation_year']}\n"
            info_text += f"Класс: {reg['class_letter']}\n"

        info_text += (
            f"Город: {city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'})\n"
        )
        info_text += payment_status
        info_text += "\nЧто вы хотите сделать?"

        choices = {}
        if needs_payment:
            choices["pay"] = "Оплатить участие"

        # Prepare choices for the menu
        choices.update(
            {
                "register_another": "Зарегистрироваться в другом городе",
                "cancel": "Отменить регистрацию",
            }
        )

        # Add payment option if needed

        choices["nothing"] = "Ничего, всё в порядке"

        response = await ask_user_choice(
            message.chat.id,
            info_text,
            choices=choices,
            state=state,
            timeout=None,
        )

        # Log single registration action choice
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {
                    "button": response,
                    "context": "single_registration_menu",
                    "city": city,
                    "needs_payment": needs_payment,
                    "payment_status": reg.get("payment_status"),
                },
                message.from_user.id,
                message.from_user.username,
            )

        if response == "cancel":
            await cancel_registration_handler(message, state)

        elif response == "pay":
            # Process payment for this registration
            from app.routers.payment import process_payment

            # Store the original user information in the state
            await state.update_data(
                original_user_id=message.from_user.id, original_username=message.from_user.username
            )

            # Get graduation year and graduate type
            graduation_year = reg["graduation_year"]
            graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

            # Process payment
            skip_instructions = reg.get("payment_status") is not None  # Skip if already seen
            await process_payment(
                message,
                state,
                city,
                graduation_year,
                skip_instructions,
                graduate_type=graduate_type,
            )

        elif response == "register_another":
            # Keep existing registration and start new one with reused info
            await send_safe(message.chat.id, "Давайте зарегистрируемся в другом городе.")
            await register_user(message, state, reuse_info=registration)

        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваша регистрация в силе. До встречи!",
                reply_markup=ReplyKeyboardRemove(),
            )


async def manage_registrations(message: Message, state: FSMContext, registrations):
    """Allow user to manage multiple registrations"""

    # Create choices for each city
    choices = {}
    for reg in registrations:
        city = reg["target_city"]
        choices[city] = f"Управлять регистрацией в городе {city}"

    choices["all"] = "Отменить все регистрации"
    choices["back"] = "Вернуться назад"

    # Log entering registration management
    if message.from_user:
        await app.save_event_log(
            "navigation",
            {
                "action": "enter_registration_management",
                "cities": [reg["target_city"] for reg in registrations],
            },
            message.from_user.id,
            message.from_user.username,
        )

    response = await ask_user_choice(
        message.chat.id,
        "Выберите регистрацию для управления:",
        choices=choices,
        state=state,
        timeout=None,
    )

    # Log button click
    if message.from_user:
        await app.save_event_log(
            "button_click",
            {
                "button": response,
                "context": "registration_management",
                "cities": [reg["target_city"] for reg in registrations],
            },
            message.from_user.id,
            message.from_user.username,
        )

    if response == "all":
        # Confirm deletion of all registrations
        confirm = await ask_user_choice(
            message.chat.id,
            "Вы уверены, что хотите отменить ВСЕ регистрации?",
            choices={"yes": "Да, отменить все", "no": "Нет, вернуться назад"},
            state=state,
            timeout=None,
        )

        # Log confirmation button click
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {"button": confirm, "context": "confirm_delete_all_registrations"},
                message.from_user.id,
                message.from_user.username,
            )

        if confirm == "yes":
            await app.delete_user_registration(message.from_user.id)

            # Log cancellation of all registrations
            # Get user info for logging
            user_reg = await app.get_user_registration(message.from_user.id)
            full_name = user_reg.get("full_name", "Unknown") if user_reg else "Unknown"
            city = "все города"  # All cities

            await app.log_registration_canceled(
                message.from_user.id, message.from_user.username or "", full_name, city
            )

            await send_safe(
                message.chat.id,
                "Все ваши регистрации отменены. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            # Go back to registration management
            await manage_registrations(message, state, registrations)

    elif response == "back":
        # Go back to main menu
        await handle_registered_user(message, state, registrations[0])

    else:
        # Manage specific city registration
        city = response
        reg = next(r for r in registrations if r["target_city"] == city)

        city_enum = next((c for c in TargetCity if c.value == city), None)

        info_text = dedent(
            f"""
            Регистрация в городе {city}:
            
            ФИО: {reg["full_name"]}
            Год выпуска: {reg["graduation_year"]}
            Класс: {reg["class_letter"]}
            Дата: {date_of_event[city_enum] if city_enum else "неизвестна"}
            
            Что вы хотите сделать?
            """
        )

        action = await ask_user_choice(
            message.chat.id,
            info_text,
            choices={
                "cancel": "Отменить регистрацию",
                "back": "Вернуться назад",
            },
            state=state,
            timeout=None,
        )

        # Log city-specific action
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {"button": action, "context": "city_registration_management", "city": city},
                message.from_user.id,
                message.from_user.username,
            )

        if action == "cancel":
            # Delete this registration
            await app.delete_user_registration(message.from_user.id, city)

            # Log cancellation
            await app.log_registration_canceled(
                message.from_user.id,
                message.from_user.username or "",
                reg.get("full_name", "Unknown"),
                city,
            )

            # Check if user has other registrations
            remaining = await app.get_user_registrations(message.from_user.id)

            if remaining:
                await send_safe(
                    message.chat.id,
                    f"Регистрация в городе {city} отменена. У вас остались другие регистрации.",
                )
                await handle_registered_user(message, state, remaining[0])
            else:
                await send_safe(
                    message.chat.id,
                    "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                    reply_markup=ReplyKeyboardRemove(),
                )

        else:  # "back"
            # Go back to registration management
            await manage_registrations(message, state, registrations)


async def register_user(
    message: Message, state: FSMContext, preselected_city=None, reuse_info=None
):
    """Register a user for an event"""
    user_id = message.from_user.id
    username = message.from_user.username

    # Initialize log messages list for this user if not exists
    if user_id not in log_messages:
        log_messages[user_id] = []

    # Initialize all variables that could be unbound
    full_name = None
    graduation_year = None
    class_letter = None
    location = None
    graduate_type = GraduateType.GRADUATE  # Default type - will be overridden in specific cases

    # Log registration start
    log_msg = await app.log_registration_step(
        user_id,
        username,
        "Начало регистрации",
        f"Предвыбранный город: {preselected_city}, Повторное использование данных: {'Да' if reuse_info else 'Нет'}",
    )
    if log_msg:
        log_messages[user_id].append(log_msg)

    # Get existing registrations to avoid duplicates
    existing_registrations = await app.get_user_registrations(user_id)
    existing_cities = [reg["target_city"] for reg in existing_registrations]

    # step 1 - greet user, ask location
    if preselected_city:
        # Use preselected city if provided
        location = next((c for c in TargetCity if c.value == preselected_city), None)

        # Log preselected city
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Выбор города",
            f"Предвыбранный город: {location.value if location else preselected_city}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    if not location:
        # Filter out cities the user is already registered for
        available_cities = {
            city.value: f"{city.value} ({date_of_event[city]})"
            for city in TargetCity
            if city.value not in existing_cities
        }

        # If no cities left, inform the user
        if not available_cities:
            await send_safe(
                message.chat.id,
                "Вы уже зарегистрированы на встречи во всех доступных городах!",
                reply_markup=ReplyKeyboardRemove(),
            )

            # Log no cities available
            log_msg = await app.log_registration_step(
                user_id,
                username,
                "Нет доступных городов",
                "Пользователь уже зарегистрирован во всех городах",
            )
            if log_msg:
                log_messages[user_id].append(log_msg)

            return

        question = dedent(
            """
            Выберите город, где планируете посетить встречу:
            """
        )

        response = await ask_user_choice(
            message.chat.id,
            question,
            choices=available_cities,
            state=state,
            timeout=None,
        )
        location = TargetCity(response)

        # Log city selection
        log_msg = await app.log_registration_step(
            user_id, username, "Выбор города", f"Выбранный город: {location.value}"
        )

        # Also log to event_logs collection
        await app.save_event_log(
            "registration_step",
            {
                "step": "city_selection",
                "city": location.value,
                "available_cities": list(available_cities.keys()),
                "existing_cities": existing_cities,
            },
            user_id,
            username,
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # If we have info to reuse, skip asking for name and class
    if reuse_info:
        full_name = reuse_info["full_name"]
        graduation_year = reuse_info["graduation_year"]
        class_letter = reuse_info["class_letter"]
        graduate_type = GraduateType(reuse_info.get("graduate_type", GraduateType.GRADUATE.value))

        # Confirm reusing the information
        confirm_text = dedent(
            f"""
            Хотите использовать те же данные для регистрации в городе {location.value}?
            
            ФИО: {full_name}
            Год выпуска: {graduation_year}
            Класс: {class_letter}
            """
        )

        confirm = await ask_user_choice(
            message.chat.id,
            confirm_text,
            choices={"yes": "Да, использовать эти данные", "no": "Нет, ввести новые данные"},
            state=state,
            timeout=None,
        )

        # Log reuse decision
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Повторное использование данных",
            f"Решение: {'Использовать существующие данные' if confirm == 'yes' else 'Ввести новые данные'}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

        if confirm == "no":
            # User wants to enter new info
            reuse_info = None

    # If not reusing info, ask for it
    if not reuse_info:
        # Ask for full name with validation
        full_name = None
        while full_name is None:
            question = dedent(
                """
                Представьтесь, пожалуйста.
                Можно имя и фамилию, можно полные ФИО
                """
            )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # Validate full name
            valid, error = app.validate_full_name(response)
            if valid:
                full_name = response
            else:
                await send_safe(message.chat.id, f"❌ {error} Пожалуйста, попробуйте еще раз.")

        # Log full name
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Ввод ФИО",
            f"ФИО: {full_name}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

        # Ask for graduation year and class letter with validation
        graduation_year = None
        class_letter = None

        while graduation_year is None or class_letter is None or not class_letter:
            if graduation_year is not None and class_letter is None:
                # We have a year but need a class letter
                question = "А букву класса?"
            else:
                question = dedent(
                    """
                    Пожалуйста, введите год выпуска и букву класса.
                    Например, "2003 Б".
                    
                    <tg-spoiler>Если вы учитель школы 146 (нынешний или бывший), нажмите: /i_am_a_teacher
                    Если вы не выпускник, но друг школы 146 - нажмите: /i_am_a_friend</tg-spoiler>
                    """
                )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # Check for special commands
            if response == "/i_am_a_teacher":
                # User is a teacher
                graduation_year = 0  # Special value for teachers
                class_letter = "Т"  # "Т" for "Учитель"
                graduate_type = GraduateType.TEACHER

                # Log teacher status
                log_msg = await app.log_registration_step(
                    user_id,
                    username,
                    "Статус участника",
                    "Учитель",
                )
                if log_msg:
                    log_messages[user_id].append(log_msg)

                # await send_safe(
                #     message.chat.id,
                #     "Вы зарегистрированы как учитель. Участие для учителей бесплатное.",
                # )
                break

            elif response == "/i_am_a_friend":
                # User is not a graduate
                graduation_year = 2000  # Special value for non-graduates
                class_letter = "Н"  # "Н" for "Не выпускник"
                graduate_type = GraduateType.NON_GRADUATE

                # Log non-graduate status
                log_msg = await app.log_registration_step(
                    user_id,
                    username,
                    "Статус участника",
                    "Не выпускник",
                )
                if log_msg:
                    log_messages[user_id].append(log_msg)

                await send_safe(message.chat.id, "Вы зарегистрированы как друг школы 146!")
                break

            # If we already have a year and just need the letter
            elif graduation_year is not None and class_letter is None:
                # Validate just the class letter
                class_letter = response.strip().split()[-1]
                valid, error = app.validate_class_letter(response)
                if valid:
                    class_letter = response.upper()
                else:
                    await send_safe(message.chat.id, f"❌ {error} Пожалуйста, попробуйте еще раз.")
            else:
                # Parse and validate both year and letter
                year, letter, error = app.parse_graduation_year_and_class_letter(response)

                if error:
                    await send_safe(message.chat.id, f"❌ {error}")
                    # If we got a valid year but no letter, save the year
                    if year is not None and letter == "":
                        graduation_year = year
                else:
                    graduation_year = year
                    class_letter = letter
                    graduate_type = GraduateType.GRADUATE

        # Log graduation info
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Ввод года выпуска и класса",
            f"Год: {graduation_year}, Класс: {class_letter}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # Internal validation - log error but don't expose to user
    if not all([full_name, graduation_year is not None, class_letter, location, graduate_type]):
        logger.error(
            f"Registration validation failed - missing required fields: "
            f"full_name={full_name}, "
            f"graduation_year={graduation_year}, "
            f"class_letter={class_letter}, "
            f"location={location}, "
            f"graduate_type={graduate_type}"
        )

    # Save the registration
    await app.save_registered_user(
        RegisteredUser(
            full_name=full_name,
            graduation_year=graduation_year,
            class_letter=class_letter,
            target_city=location,
            graduate_type=graduate_type,
        ),
        user_id=user_id,
        username=username,
    )

    # Log registration completion
    log_msg = await app.log_registration_step(
        user_id,
        username,
        "Регистрация завершена",
        f"Город: {location.value}, ФИО: {full_name}, Выпуск: {graduation_year} {class_letter}",
    )
    if log_msg:
        log_messages[user_id].append(log_msg)

    # Log to events chat
    await app.log_registration_completed(
        user_id,
        username,
        full_name,
        graduation_year,
        class_letter,
        location.value,
        graduate_type.value,
    )

    # Clear log messages
    await delete_log_messages(user_id)

    # Send confirmation message with payment info in one message
    confirmation_msg = (
        f"Спасибо, {full_name}!\n"
        f"Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}. "
    )

    # Skip payment flow for St. Petersburg, Belgrade and teachers
    if location.value == TargetCity.SAINT_PETERSBURG.value:
        # Mark Saint Petersburg registrations as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (Санкт-Петербург)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля встречи в Санкт-Петербурге оплата не требуется. Все расходы участники несут самостоятельно."
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    elif location.value == TargetCity.BELGRADE.value:
        # Mark Belgrade registrations as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (Белград)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля встречи в Белграде оплата не требуется. Все расходы участники несут самостоятельно."
        confirmation_msg += (
            "\n\nПрисоединяйтесь к группе встречи в Telegram: https://t.me/+8-4xPvS-PTcxZTEy"
        )
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    elif graduate_type == GraduateType.TEACHER:
        # Mark teachers as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (учитель)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля учителей участие бесплатное. Спасибо за вашу работу!"
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )

        # Auto-export to sheets after registration with confirmed payment
        await app.export_registered_users_to_google_sheets()
    else:
        # Regular flow for everyone else who needs to pay
        confirmation_msg += "Сейчас пришлем информацию об оплате..."
        await send_safe(message.chat.id, confirmation_msg)

        # Import the process_payment function here to avoid circular imports
        from app.routers.payment import process_payment

        # Store the original user information in the state
        await state.update_data(original_user_id=user_id, original_username=username)

        # Process payment directly
        await process_payment(
            message, state, location.value, graduation_year, graduate_type=graduate_type.value
        )


# Add this function to delete log messages
async def delete_log_messages(user_id: int) -> None:
    """Delete all log messages for a user"""
    if user_id not in log_messages:
        return

    from botspot.core.dependency_manager import get_dependency_manager

    deps = get_dependency_manager()
    bot = deps.bot

    for msg in log_messages[user_id]:
        try:
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            logger.error(f"Failed to delete log message: {e}")

    # Clear the list
    log_messages[user_id] = []


@commands_menu.add_command("cancel_registration", "Отменить регистрацию")
@router.message(Command("cancel_registration"))
async def cancel_registration_handler(message: Message, state: FSMContext):
    """
    Cancel user registration command handler.
    """
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Log the cancel registration command
    await app.save_event_log(
        "command",
        {
            "command": "/cancel_registration",
            "content": message.text,
            "chat_type": message.chat.type,
        },
        message.from_user.id,
        message.from_user.username,
    )

    user_id = message.from_user.id
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        await send_safe(
            message.chat.id,
            "У вас нет активных регистраций. Используйте /start для регистрации на встречу.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if len(registrations) == 1:
        # User has only one registration, ask for confirmation
        reg = registrations[0]
        city = reg["target_city"]
        full_name = reg["full_name"]
        city_enum = next((c for c in TargetCity if c.value == city), None)

        confirm_text = dedent(
            f"""
            Вы уверены, что хотите отменить регистрацию на встречу в городе {city}?
            
            ФИО: {full_name}
            Год выпуска: {reg["graduation_year"]}
            Класс: {reg["class_letter"]}
            Город: {city} ({date_of_event[city_enum] if city_enum else "дата неизвестна"})
            """
        )

        response = await ask_user_choice(
            message.chat.id,
            confirm_text,
            choices={"yes": "Да, отменить", "no": "Нет, сохранить"},
            state=state,
            timeout=None,
        )

        if response == "yes":
            # Cancel registration
            await app.delete_user_registration(user_id, city)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                city,
            )

            await send_safe(
                message.chat.id,
                "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await send_safe(
                message.chat.id,
                "Отмена регистрации отменена. Ваша регистрация сохранена.",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        # User has multiple registrations, ask which one to cancel
        choices = {}
        for reg in registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)
            choices[city] = (
                f"{city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'})"
            )

        choices["all"] = "Отменить все регистрации"
        choices["cancel"] = "Ничего не отменять"

        response = await ask_user_choice(
            message.chat.id,
            "Выберите, какую регистрацию вы хотите отменить:",
            choices=choices,
            state=state,
            timeout=None,
        )

        if response == "cancel":
            await send_safe(
                message.chat.id,
                "Отмена операции. Ваши регистрации сохранены.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if response == "all":
            # Get user info for logging before deleting
            user_reg = registrations[0]
            full_name = user_reg.get("full_name", "Unknown")

            # Cancel all registrations
            await app.delete_user_registration(user_id)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                None,  # Indicates all cities
            )

            await send_safe(
                message.chat.id,
                "Все ваши регистрации отменены. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            # Cancel specific city registration
            city = response
            reg = next(r for r in registrations if r["target_city"] == city)
            full_name = reg["full_name"]

            # Cancel registration
            await app.delete_user_registration(user_id, city)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                city,
            )

            await send_safe(
                message.chat.id,
                f"Ваша регистрация в городе {city} отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )


@commands_menu.add_command("status", "Статус регистрации")
@router.message(Command("status"))
async def status_handler(message: Message, state: FSMContext):
    """
    Show user registration status
    """
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Log the status command
    await app.save_event_log(
        "command",
        {"command": "/status", "content": message.text, "chat_type": message.chat.type},
        message.from_user.id,
        message.from_user.username,
    )

    user_id = message.from_user.id
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        await send_safe(
            message.chat.id,
            "У вас нет активных регистраций. Используйте /start для регистрации на встречу.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    status_text = "📋 Ваши регистрации:\n\n"

    for reg in registrations:
        city = reg["target_city"]
        city_enum = next((c for c in TargetCity if c.value == city), None)
        full_name = reg["full_name"]
        graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

        # Add city and date information
        status_text += f"🏙️ Город: {city}"
        if city_enum and city_enum in date_of_event:
            status_text += f" ({date_of_event[city_enum]})"
        status_text += "\n"

        # Add personal information
        status_text += f"👤 ФИО: {full_name}\n"

        # Show different info based on graduate type
        if graduate_type == GraduateType.TEACHER.value:
            status_text += "👨‍🏫 Статус: Учитель\n"
        elif graduate_type == GraduateType.NON_GRADUATE.value:
            status_text += "👥 Статус: Не выпускник\n"
        else:
            status_text += f"🎓 Выпуск: {reg['graduation_year']} {reg['class_letter']}\n"

        # Add payment status
        if city == TargetCity.SAINT_PETERSBURG.value or city == TargetCity.BELGRADE.value:
            status_text += "💰 Оплата: За свой счет\n"
        elif graduate_type == GraduateType.TEACHER.value:
            status_text += "💰 Оплата: Бесплатно (учитель)\n"
        else:
            payment_status = reg.get("payment_status", "не оплачено")
            status_emoji = (
                "✅"
                if payment_status == "confirmed"
                else "❌" if payment_status == "declined" else "⏳"
            )
            status_text += f"💰 Статус оплаты: {status_emoji} {payment_status}\n"

            # Add payment amount if available
            if "payment_amount" in reg:
                status_text += f"💵 Сумма оплаты: {reg['payment_amount']} руб.\n"
            elif payment_status == "pending" and "discounted_payment_amount" in reg:
                status_text += f"💵 Ожидаемая сумма: {reg['discounted_payment_amount']} руб.\n"

        # Add separator between registrations
        status_text += "\n"

    # Add available commands information
    status_text += "Доступные команды:\n"
    status_text += "- /start - управление регистрациями\n"
    status_text += "- /pay - оплатить участие\n"
    status_text += "- /cancel_registration - отменить регистрацию\n"

    await send_safe(message.chat.id, status_text, reply_markup=ReplyKeyboardRemove())


@commands_menu.add_command("start", "Start the bot")
@router.message(CommandStart())
@router.message(F.text, F.chat.type == "private")  # only handle private messages
async def start_handler(message: Message, state: FSMContext):
    """
    Main scenario flow.
    """
    # Log the start command
    if message.from_user:
        await app.save_event_log(
            "command",
            {"command": "/start", "content": message.text, "chat_type": message.chat.type},
            message.from_user.id,
            message.from_user.username,
        )

    if is_admin(message.from_user):
        result = await admin_handler(message, state)
        if result != "register":
            return

    # Check if user is already registered
    existing_registration = await app.get_user_registration(message.from_user.id)

    if existing_registration:
        # User is already registered, show options
        await handle_registered_user(message, state, existing_registration)
    else:
        # New user, start registration
        await register_user(message, state)
