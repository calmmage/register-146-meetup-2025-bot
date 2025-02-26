from aiogram import Router, html
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from botspot import commands_menu
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe
from textwrap import dedent
from app.app import App, TargetCity, RegisteredUser

router = Router()
app = App()


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
async def start_handler(message: Message, state: FSMContext):
    """
    Main scenario flow.
    """

    # todo: check if user is already registered
    # if not -> main flow
    # todo: if yes -> give options:
    # - cancel registration
    # - show registration info
    # - change registration info
    # - register for another city

    await register_user(message, state)


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

    await app.save_registered_user(registered_user)

    await send_safe(
        message.chat.id,
        f"Спасибо, {html.bold(full_name)}!\n"
        "Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}.",
        reply_markup=ReplyKeyboardRemove(),
    )


# @router.message()
# async def chat_handler():
#     text = "Привет! Это бот для регистрации на встречу выпускников школы 146.\n"
#     "ask"

# @commands_menu.add_command("help", "Show this help message")
# @router.message(Command("help"))
# async def help_handler(message: Message):
#     """Basic help command handler"""
#     await send_safe(
#         message.chat.id,
#         f"This is {app.name}. Use /start to begin."
#         "Available commands:\n"
#         "/start - Start the bot\n"
#         "/help - Show this help message\n"
#         "/help_botspot - Show Botspot help\n"
#         "/timezone - Set your timezone\n"
#         "/error_test - Test error handling",
#     )
