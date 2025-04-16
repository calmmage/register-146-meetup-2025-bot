import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from app.app import App

from botspot import commands_menu
from botspot.user_interactions import ask_user_choice, ask_user_raw
from botspot.utils import send_safe

router = Router()


async def save_feedback_and_thank(
    message,
    state,
    app: App,
    user_id,
    username,
    full_name,
    city=None,
    attended=None,
    recommendation=None,
    venue_rating=None,
    food_rating=None,
    entertainment_rating=None,
    help_interest=None,
    comments=None,
    is_cancel=False,
):
    """Helper function to save feedback and send thank you message"""
    # Save all feedback data to the database
    await app.save_feedback(
        user_id=user_id,
        username=username,
        full_name=full_name,
        city=city,
        attended=attended,
        recommendation_level=recommendation,
        venue_rating=venue_rating,
        food_rating=food_rating,
        entertainment_rating=entertainment_rating,
        help_interest=help_interest,
        comments=comments,
    )

    # Standard thank you message
    await send_safe(
        message.chat.id,
        "Спасибо за ответ! Мы будем ждать новых возможностей чтобы увидеться с тобой в ближайшее время. "
        "Смотри на канал @school146club и общий чат на 685 выпускников 146 "
        "(вход модерируется по ссылке https://t.me/+_wm7MlaGhCExOTg6) "
        "чтобы узнать о наших следующих мероприятиях.",
    )

    if is_cancel:
        return True

    if app.settings.delay_messages:
        await asyncio.sleep(5)

    # Ask about club projects
    response = await ask_user_raw(
        message.chat.id,
        "Хочешь еще в какие-то проекты Клуба Друзей 146 включаться? Если да, ответь сюда сообщением.",
        state=state,
        timeout=1200,  # 20 minutes timeout
    )

    if response:
        # Log the response
        await app.save_event_log(
            "feedback",
            {
                "type": "club_participation_interest",
                "response": response.text,
            },
            user_id,
            username,
        )

        await send_safe(
            message.chat.id,
            "Спасибо, мы обязательно к тебе вернемся в ближайшие дни - будет интересно обсудить. "
            "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
        )

        await send_safe(
            app.settings.events_chat_id,
            f"Пользователь {full_name} ({user_id}) заинтересован быть активистомх. Ответ: {response.text}",
        )
    else:
        await send_safe(
            message.chat.id,
            "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
        )
    return True


@commands_menu.add_command("feedback", "Оставить отзыв о встрече выпускников")
@router.message(Command("feedback"))
async def feedback_handler(message: Message, state: FSMContext, app: App):
    """Handle user feedback for alumni meetup"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # from app.router import app

    # Get existing user data if available
    user_data = await app.collection.find_one({"user_id": message.from_user.id})
    full_name = user_data.get("full_name") if user_data else None

    # Start feedback flow
    await send_safe(
        message.chat.id,
        "Привет! \n"
        "Я чат-бот, собираю обратную связь по встрече выпускников. \n\n"
        "Благодаря в том числе и твоей обратной связи мы продолжаем улучшать наши мероприятия, "
        "помоги нам пожалуйста, потрать 4 минуты :)",
    )

    if app.settings.delay_messages:
        await asyncio.sleep(5)

    # Step 1: Ask if user attended the meetup
    attendance = await ask_user_choice(
        message.chat.id,
        "Ты был на встрече выпускников?",
        choices={
            "yes": "Да",
            "no": "Нет",
            "cancel": "Отмена опроса",
        },
        state=state,
        timeout=None,
        columns=2,
        default_choice="cancel",
        highlight_default=False,
    )

    if attendance == "cancel":
        # Save minimal feedback before exiting
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            is_cancel=True,
        )
        return

    attended = attendance == "yes"

    # If they didn't attend, save feedback and finish
    if not attended:
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=False,
        )
        return

    # User attended, continue with feedback questions

    # Step 2: Ask which city the user attended
    city = await ask_user_choice(
        message.chat.id,
        "В каком городе?",
        choices={
            "perm": "Пермь, в субботу 29 марта",
            "moscow": "Москва, в субботу 05 апреля",
            "saint_petersburg": "Питер, в субботу 05 апреля",
            "belgrade": "Белград, в субботу 05 апреля",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        highlight_default=False,
        state=state,
        timeout=None,
        default_choice="cancel",
    )

    if city == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            is_cancel=True,
        )
        return

    if city == "skip":
        city = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    await app.save_event_log(
        "feedback",
        {
            "type": "city_selection",
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 3: Ask recommendation level
    recommendation = await ask_user_choice(
        message.chat.id,
        "Круто! Насколько ты бы порекомендовал своим одноклассникам участвовать в следующем году?\n\n"
        "1 - лучше заняться чем-то другим\n"
        "2 - зайти на полчаса\n"
        "3 - посидеть пару часов с одноклассниками поговорить\n"
        "4 - посидеть до закрытия - познакомиться с другими поколениями выпускников\n"
        "5 - моя бы воля - сделали бы afterparty до последнего танцующего!",
        choices={
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        state=state,
        default_choice="cancel",
        highlight_default=False,
        timeout=None,
        columns=5,
    )

    if recommendation == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            city=city,
            is_cancel=True,
        )
        return

    if recommendation == "skip":
        recommendation = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    # Log recommendation level
    await app.save_event_log(
        "feedback",
        {
            "type": "recommendation_level",
            "level": recommendation,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 4: Ask venue rating
    venue_rating = await ask_user_choice(
        message.chat.id,
        "Насколько тебе понравилась площадка?\n\n"
        "1 - совсем не понравилась\n"
        "5 - супер, обязательно в этом же месте в следующем году!",
        choices={
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        state=state,
        highlight_default=False,
        timeout=None,
        default_choice="cancel",
        columns=5,
    )

    if venue_rating == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            city=city,
            recommendation=recommendation,
            is_cancel=True,
        )
        return

    if venue_rating == "skip":
        venue_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    # Log venue rating
    await app.save_event_log(
        "feedback",
        {
            "type": "venue_rating",
            "rating": venue_rating,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 5: Ask food and drinks rating
    food_rating = await ask_user_choice(
        message.chat.id,
        "Насколько понравилась еда и напитки?\n\n"
        "1 - несъедобно\n"
        "5 - каждый бы день так есть и пить!",
        choices={
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        default_choice="cancel",
        highlight_default=False,
        state=state,
        timeout=None,
        columns=5,
    )

    if food_rating == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            city=city,
            recommendation=recommendation,
            venue_rating=venue_rating,
            is_cancel=True,
        )
        return

    if food_rating == "skip":
        food_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    # Log food rating
    await app.save_event_log(
        "feedback",
        {
            "type": "food_rating",
            "rating": food_rating,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 6: Ask entertainment rating
    entertainment_rating = await ask_user_choice(
        message.chat.id,
        "Насколько понравились развлекательные мероприятия?\n\n"
        "1 - в следующей раз не буду участвовать ни за какие коврижки\n"
        "5 - только ради них можно было приходить!",
        choices={
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        default_choice="cancel",
        state=state,
        timeout=None,
        highlight_default=False,
        columns=5,
    )

    if entertainment_rating == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            city=city,
            recommendation=recommendation,
            venue_rating=venue_rating,
            food_rating=food_rating,
            is_cancel=True,
        )
        return

    if entertainment_rating == "skip":
        entertainment_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    # Log entertainment rating
    await app.save_event_log(
        "feedback",
        {
            "type": "entertainment_rating",
            "rating": entertainment_rating,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 7: Ask if willing to help organize next year
    help_interest = await ask_user_choice(
        message.chat.id,
        "Ты готов был бы помогать в организации встрече в твоем городе весной 2026?\n\n"
        "1 - да, запишите меня!\n"
        "2 - нет, пока что нет пропускной способности, а прийти буду рад!\n"
        "3 - пока что сложно сказать так заранее",
        choices={
            "yes": "1",
            "no": "2",
            "maybe": "3",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        state=state,
        timeout=None,
        columns=3,
        default_choice="cancel",
        highlight_default=True,
    )

    if help_interest == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            message.from_user.id,
            message.from_user.username,
            full_name,
            attended=True,
            city=city,
            recommendation=recommendation,
            venue_rating=venue_rating,
            food_rating=food_rating,
            entertainment_rating=entertainment_rating,
            is_cancel=True,
        )
        return

    if help_interest == "skip":
        help_interest = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    # Log willingness to help
    await app.save_event_log(
        "feedback",
        {
            "type": "willing_to_help",
            "response": help_interest,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 8: Ask for specific comments
    comments_text = None
    comments = await ask_user_raw(
        message.chat.id,
        "Есть ли у тебя конкретные комментарии? Напиши пожалуйста сюда ответным сообщением.",
        state=state,
        timeout=None,
    )
    if comments and comments.text:
        comments_text = comments.text

    # Save all feedback and thank the user using the helper function
    await save_feedback_and_thank(
        message,
        state,
        app,
        message.from_user.id,
        message.from_user.username,
        full_name,
        city=city,
        attended=True,
        recommendation=recommendation,
        venue_rating=venue_rating,
        food_rating=food_rating,
        entertainment_rating=entertainment_rating,
        help_interest=help_interest,
        comments=comments_text,
    )
