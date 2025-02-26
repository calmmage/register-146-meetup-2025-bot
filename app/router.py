from aiogram import Router, html, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from dotenv import load_dotenv
from textwrap import dedent

from app.app import App, TargetCity, RegisteredUser
from botspot import commands_menu
from botspot.core.dependency_manager import get_dependency_manager
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe, is_admin
from botspot.utils.admin_filter import AdminFilter

router = Router()
app = App()

# Load environment variables
load_dotenv()


date_of_event = {
    TargetCity.PERM: "22 Марта, Сб",
    TargetCity.MOSCOW: "29 Марта, Сб",
    TargetCity.SAINT_PETERSBURG: "29 Марта, Сб",
}

padezhi = {
    TargetCity.PERM: "Перми",
    TargetCity.MOSCOW: "Москве",
    TargetCity.SAINT_PETERSBURG: "Санкт-Петербурге",
}


@commands_menu.add_command("start", "Start the bot")
@router.message(CommandStart())
@router.message()  # general chat handler
async def start_handler(message: Message, state: FSMContext):
    """
    Main scenario flow.
    """

    if is_admin(message.from_user):
        # Show admin options
        response = await ask_user_choice(
            message.chat.id,
            "Вы администратор бота. Что вы хотите сделать?",
            choices={
                "register": "Зарегистрироваться на встречу",
                "export": "Экспортировать данные",
                "view_stats": "Посмотреть статистику",
            },
            state=state,
            timeout=None,
        )

        if response == "export":
            await export_handler(message, state)
            return
        elif response == "view_stats":
            await show_stats(message)
            return
        # For "register", continue with normal flow

    # Check if user is already registered
    existing_registration = await app.get_user_registration(message.from_user.id)

    if existing_registration:
        # User is already registered, show options
        await handle_registered_user(message, state, existing_registration)
    else:
        # New user, start registration
        await register_user(message, state)


async def handle_registered_user(message: Message, state: FSMContext, registration):
    """Handle interaction with already registered user"""

    # Format the existing registration info
    city = registration["target_city"]
    city_enum = next((c for c in TargetCity if c.value == city), None)

    info_text = dedent(
        f"""
        Вы уже зарегистрированы на встречу выпускников:
        
        ФИО: {registration["full_name"]}
        Год выпуска: {registration["graduation_year"]}
        Класс: {registration["class_letter"]}
        Город: {city} ({date_of_event[city_enum] if city_enum else "дата неизвестна"})
        
        Что вы хотите сделать?
    """
    )

    response = await ask_user_choice(
        message.chat.id,
        info_text,
        choices={
            "change": "Изменить данные регистрации",
            "cancel": "Отменить регистрацию",
            "register_another": "Зарегистрироваться в другом городе",
            "nothing": "Ничего, всё в порядке",
        },
        state=state,
        timeout=None,
    )

    if response == "change":
        # Delete current registration and start new one
        await app.delete_user_registration(message.from_user.id)
        await send_safe(message.chat.id, "Давайте обновим вашу регистрацию.")
        await register_user(message, state)

    elif response == "cancel":
        # Delete registration
        await app.delete_user_registration(message.from_user.id)
        await send_safe(
            message.chat.id,
            "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
            reply_markup=ReplyKeyboardRemove(),
        )

    elif response == "register_another":
        # Keep existing registration and start new one
        await send_safe(message.chat.id, "Давайте зарегистрируемся в другом городе.")
        await register_user(message, state)

    else:  # "nothing"
        await send_safe(
            message.chat.id,
            "Отлично! Ваша регистрация в силе. До встречи!",
            reply_markup=ReplyKeyboardRemove(),
        )


async def register_user(message: Message, state: FSMContext):
    # step 1 - greet user, ask location

    question = dedent(
        """
        Привет! Это бот для регистрации на встречу выпускников школы 146.
        Выберите город, где планируете посетить встречу:
        """
    )

    choices = {city.value: f"{city.value} ({date_of_event[city]})" for city in TargetCity}

    response = await ask_user_choice(
        message.chat.id,
        question,
        choices=choices,
        state=state,
        timeout=None,
    )
    location = TargetCity(response)

    question = dedent(
        """
        Как вас зовут?
        Пожалуйста, введите полное ФИО.
        """
    )

    # step 2 - ask for full name
    full_name = None
    while full_name is None:
        full_name = await ask_user(
            message.chat.id,
            question,
            state=state,
            timeout=None,
        )

    # step 3 - ask for year of graduation and class letter
    question = dedent(
        """
        Пожалуйста, введите год выпуска и букву класса.
        Например, "2025 Б".
        """
    )
    response = None
    while response is None:
        response = await ask_user(
            message.chat.id,
            question,
            state=state,
            timeout=None,
        )

    graduation_year, class_letter = app.parse_graduation_year_and_class_letter(response)

    registered_user = RegisteredUser(
        full_name=full_name,
        graduation_year=graduation_year,
        class_letter=class_letter,
        target_city=location,
    )

    # Save with user_id and username
    await app.save_registered_user(
        registered_user, user_id=message.from_user.id, username=message.from_user.username
    )

    await send_safe(
        message.chat.id,
        f"Спасибо, {html.bold(full_name)}!\n"
        "Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}.",
        reply_markup=ReplyKeyboardRemove(),
    )


@commands_menu.add_command("export", "Export registered users to Google Sheets or CSV")
@router.message(AdminFilter(), Command("export"))
async def export_handler(message: Message, state: FSMContext):
    """Export registered users to Google Sheets or CSV"""
    notif = await send_safe(message.chat.id, "Preparing export...")

    # Ask user for export format
    response = await ask_user_choice(
        message.chat.id,
        "Choose export format:",
        choices={"sheets": "Google Sheets", "csv": "CSV File"},
        state=state,
        timeout=None,
    )

    if response == "sheets":
        # Export to Google Sheets
        await notif.edit_text("Exporting data to Google Sheets...")
        result = await app.export_registered_users()
        await send_safe(message.chat.id, result)
    else:
        # Export to CSV
        await notif.edit_text("Exporting data to CSV file...")
        csv_content, result_message = await app.export_to_csv()

        if csv_content:
            # Send the CSV content as a file using send_safe
            await send_safe(message.chat.id, csv_content, filename="registered_users.csv")
        else:
            await send_safe(message.chat.id, result_message)

    await notif.delete()


# General message handler for any text
@router.message(F.text)
async def general_message_handler(message: Message, state: FSMContext):
    """Handle any text message by routing to the start command"""
    await send_safe(
        message.chat.id, "Для регистрации или управления вашей записью используйте команду /start"
    )
    # Option 2: Uncomment to just run the basic flow for any message
    # await start_handler(message, state)


async def show_stats(message: Message):
    """Show registration statistics"""
    # Count registrations by city
    cursor = app.collection.aggregate([{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}])
    stats = await cursor.to_list(length=None)

    # Format stats
    stats_text = "Статистика регистраций:\n\n"
    total = 0

    for stat in stats:
        city = stat["_id"]
        count = stat["count"]
        total += count
        stats_text += f"{city}: {count} человек\n"

    stats_text += f"\nВсего: {total} человек"

    await send_safe(message.chat.id, stats_text)
