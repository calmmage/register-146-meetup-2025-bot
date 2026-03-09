import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from app.app import App

from botspot import commands_menu
from app.user_interactions import ask_user_choice, ask_user_choice_raw
from botspot.utils import send_safe

router = Router()


async def ask_low_rating_feedback(
    message,
    state,
    app: App,
    rating_type: str,
    rating_value: str | None,
    user_id: int,
    username: str | None,
) -> str | None:
    """Ask for specific feedback when a low rating (1-3) is given"""
    if rating_value and int(rating_value) <= 3:
        feedback = await ask_user_choice_raw(
            message.chat.id,
            f"Спасибо за честный ответ! Можешь поделиться, что именно не понравилось в {rating_type} или что можно улучшить?",
            choices={
                "skip": "Пропустить вопрос",
            },
            state=state,
            timeout=None,
        )

        if feedback and isinstance(feedback, str):
            # Button was clicked
            if feedback == "skip":
                await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")
                return None
        elif feedback and feedback.text:
            # User sent a text message
            await app.save_event_log(
                "feedback",
                {
                    "type": "low_rating_feedback",
                    "rating_type": rating_type,
                    "rating_value": rating_value,
                    "feedback": feedback.text,
                },
                user_id,
                username,
            )
            return feedback.text
    return None


async def save_feedback_and_thank(
    message,
    state,
    app: App,
    feedback_data: dict,
    is_cancel: bool = False,
) -> bool:
    """Helper function to save feedback and send thank you message"""
    # Save all feedback data to the database
    await app.save_feedback(feedback_data)

    # Standard thank you message
    thank_you_msg = "Спасибо за ответ! Мы будем ждать новых возможностей чтобы увидеться с тобой в ближайшее время. "
    thank_you_msg += "Смотри на канал @school146club и общий чат на 713 выпускников 146 "
    thank_you_msg += "(вход модерируется по ссылке https://t.me/+Y5AbalGQBktmOGFi) "
    thank_you_msg += "чтобы узнать о наших следующих мероприятиях.\n\n"

    # Add photo album links
    thank_you_msg += "📸 Фотоальбомы с встреч:\n\n"

    city = feedback_data.get("city")
    if city == "perm":
        thank_you_msg += "• Ваш город - Пермь: https://disk.yandex.ru/d/bK6dVlNET7Uifg\n"
        thank_you_msg += "• Москва: https://disk.yandex.ru/d/gF_eko0YLslsOQ\n"
    elif city == "moscow":
        thank_you_msg += "• Ваш город - Москва: https://disk.yandex.ru/d/gF_eko0YLslsOQ\n"
        thank_you_msg += "• Пермь: https://disk.yandex.ru/d/bK6dVlNET7Uifg\n"
    else:
        thank_you_msg += "• Пермь: https://disk.yandex.ru/d/bK6dVlNET7Uifg\n"
        thank_you_msg += "• Москва: https://disk.yandex.ru/d/gF_eko0YLslsOQ\n"

    if is_cancel:
        thank_you_msg += (
            "\nНа этом сеанс обратной связи закончен. До скорых встреч на наших мероприятиях! 🎉"
        )

    await send_safe(
        message.chat.id,
        thank_you_msg,
    )

    if is_cancel:
        return True

    if app.settings.delay_messages:
        await asyncio.sleep(5)

    # Ask about club projects
    response = await ask_user_choice_raw(
        message.chat.id,
        "Хочешь еще в какие-то проекты Клуба Друзей 146 включаться? Если да, ответь сюда сообщением.",
        choices={
            "skip": "Пропустить вопрос",
        },
        state=state,
        timeout=1200,  # 20 minutes timeout
    )

    if response and isinstance(response, str):
        # Button was clicked
        if response == "skip":
            await send_safe(
                message.chat.id,
                "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
            )
            await send_safe(
                message.chat.id,
                "На этом сеанс обратной связи закончен. До скорых встреч на наших мероприятиях! 🎉",
            )
            return True
    elif response and response.text:
        # User sent a text message
        # Log the response
        await app.save_event_log(
            "feedback",
            {
                "type": "club_participation_interest",
                "response": response.text,
            },
            feedback_data["user_id"],
            feedback_data.get("username"),
        )

        await send_safe(
            message.chat.id,
            "Спасибо, мы обязательно к тебе вернемся в ближайшие дни - будет интересно обсудить. "
            "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
        )

        await send_safe(
            app.settings.events_chat_id,
            f"Пользователь {feedback_data.get('full_name')} ({feedback_data['user_id']}) заинтересован быть активистомх. Ответ: {response.text}",
        )
    else:
        await send_safe(
            message.chat.id,
            "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
        )
    await send_safe(
        message.chat.id,
        "На этом сеанс обратной связи закончен. До скорых встреч на наших мероприятиях! 🎉",
    )
    return True


@commands_menu.add_command("feedback", "Оставить отзыв о встрече выпускников")
@router.message(Command("feedback"))
async def feedback_handler(message: Message, state: FSMContext, app: App):
    """Handle user feedback for alumni meetup"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Get existing user data if available
    user_data = await app.collection.find_one({"user_id": message.from_user.id})
    full_name = user_data.get("full_name") if user_data else None

    # Initialize feedback data dict
    feedback_data = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": full_name,
    }

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
            feedback_data,
            is_cancel=True,
        )
        return

    feedback_data["attended"] = attendance == "yes"

    # If they didn't attend, save feedback and finish
    if not feedback_data["attended"]:
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            feedback_data,
        )
        return

    # User attended, continue with feedback questions

    # Step 2: Ask which city the user attended
    # Build choices from events that have passed or are archived
    city_choices = {}
    all_events = await app.get_all_events()
    for ev in all_events:
        status = ev.get("status", "")
        if status in ("archived", "passed"):
            ev_id = str(ev["_id"])
            label = f"{ev.get('city', 'Unknown')}, {ev.get('date_display', '')}"
            city_choices[ev_id] = label
    city_choices["skip"] = "Пропустить вопрос"
    city_choices["cancel"] = "Отмена"

    city = await ask_user_choice(
        message.chat.id,
        "В каком городе?",
        choices=city_choices,
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
            feedback_data,
            is_cancel=True,
        )
        return

    if city == "skip":
        city = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["city"] = city

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
            feedback_data,
            is_cancel=True,
        )
        return

    if recommendation == "skip":
        recommendation = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["recommendation_level"] = recommendation

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

    # Ask for feedback if rating is low
    low_rating_feedback = await ask_low_rating_feedback(
        message,
        state,
        app,
        "общей рекомендации",
        recommendation,
        message.from_user.id,
        message.from_user.username,
    )
    if low_rating_feedback:
        feedback_data["recommendation_feedback"] = low_rating_feedback

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
            feedback_data,
            is_cancel=True,
        )
        return

    if venue_rating == "skip":
        venue_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["venue_rating"] = venue_rating

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

    # Ask for feedback if rating is low
    low_rating_feedback = await ask_low_rating_feedback(
        message,
        state,
        app,
        "площадке",
        venue_rating,
        message.from_user.id,
        message.from_user.username,
    )
    if low_rating_feedback:
        feedback_data["venue_feedback"] = low_rating_feedback

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
            feedback_data,
            is_cancel=True,
        )
        return

    if food_rating == "skip":
        food_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["food_rating"] = food_rating

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

    # Ask for feedback if rating is low
    low_rating_feedback = await ask_low_rating_feedback(
        message,
        state,
        app,
        "еде и напитках",
        food_rating,
        message.from_user.id,
        message.from_user.username,
    )
    if low_rating_feedback:
        feedback_data["food_feedback"] = low_rating_feedback

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
            feedback_data,
            is_cancel=True,
        )
        return

    if entertainment_rating == "skip":
        entertainment_rating = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["entertainment_rating"] = entertainment_rating

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

    # Ask for feedback if rating is low
    low_rating_feedback = await ask_low_rating_feedback(
        message,
        state,
        app,
        "развлекательных мероприятиях",
        entertainment_rating,
        message.from_user.id,
        message.from_user.username,
    )
    if low_rating_feedback:
        feedback_data["entertainment_feedback"] = low_rating_feedback

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
            feedback_data,
            is_cancel=True,
        )
        return

    if help_interest == "skip":
        help_interest = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["help_interest"] = help_interest

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
    comments = await ask_user_choice_raw(
        message.chat.id,
        "Если хочешь написать что-то, что мы не включили в опрос, напиши ниже",
        choices={
            "skip": "Пропустить вопрос",
        },
        state=state,
        timeout=None,
    )

    if comments and isinstance(comments, str):
        # Button was clicked
        if comments == "skip":
            await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")
    elif comments and comments.text:
        # User sent a text message
        comments_text = comments.text

    feedback_data["comments"] = comments_text

    # Step 9: Ask about feedback format preference
    feedback_format = await ask_user_choice(
        message.chat.id,
        "Как удобнее заполнять обратную связь?",
        choices={
            "bot": "Вот так через бота",
            "google_forms": "Гугл формы",
            "skip": "Пропустить вопрос",
            "cancel": "Отмена",
        },
        state=state,
        timeout=None,
        columns=2,
        default_choice="cancel",
        highlight_default=False,
    )

    if feedback_format == "cancel":
        # Save feedback data and thank the user
        await save_feedback_and_thank(
            message,
            state,
            app,
            feedback_data,
            is_cancel=True,
        )
        return

    if feedback_format == "skip":
        feedback_format = None
        await send_safe(message.chat.id, "Спасибо! Вопрос пропущен.")

    feedback_data["feedback_format_preference"] = feedback_format

    # Log feedback format preference
    await app.save_event_log(
        "feedback",
        {
            "type": "feedback_format_preference",
            "preference": feedback_format,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Save all feedback and thank the user using the helper function
    await save_feedback_and_thank(
        message,
        state,
        app,
        feedback_data,
    )
