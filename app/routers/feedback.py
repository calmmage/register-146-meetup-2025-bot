from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from botspot import commands_menu
from botspot.user_interactions import ask_user_choice, ask_user_raw
from botspot.utils import send_safe

router = Router()


@commands_menu.add_command("feedback", "Оставить отзыв о встрече выпускников")
@router.message(Command("feedback"))
async def feedback_handler(message: Message, state: FSMContext):
    """Handle user feedback for alumni meetup"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Start feedback flow
    await send_safe(
        message.chat.id,
        "Я чат-бот, собираю обратную связь по встрече выпускников. "
        "Благодаря в том числе и твоей обратной связи мы продолжаем улучшать наши мероприятия, "
        "помоги нам пожалуйста, потрать 4 минуты.",
    )

    # Step 1: Ask if user attended the meetup
    attendance = await ask_user_choice(
        message.chat.id,
        "Ты был на встрече выпускников?",
        choices={
            "yes": "Да",
            "no": "Нет",
            # "cancel": "Не хочу отвечать, закончить сеанс обратной связи",
        },
        state=state,
        timeout=None,
        columns=2,
    )

    # if attendance == "cancel":
    #     await send_safe(
    #         message.chat.id,
    #         "Принято! До связи с Клубом. Если хочешь с нами связаться проактивно, "
    #         "всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
    #     )
    #     return

    if attendance == "no":
        await send_safe(
            message.chat.id,
            "Жаль что не получилось присоединиться! Мы будем ждать новых возможностей "
            "чтобы увидеться с тобой в ближайшее время. Смотри на канал @school146club "
            "и общий чат на 685 выпускников 146 (вход модерируется по ссылке "
            "https://t.me/+_wm7MlaGhCExOTg6) чтобы узнать о наших следующих мероприятиях.",
        )

        # Ask if user wants to participate in other Club projects
        try:
            response = await ask_user_raw(
                message.chat.id,
                "Хочешь еще в какие-то проекты Клуба Друзей 146 включаться? Если да, ответь сюда сообщением.",
                state=state,
                timeout=1200,  # 20 minutes timeout
            )

            if response:
                # User responded
                from app.router import app

                # Log the response
                await app.save_event_log(
                    "feedback",
                    {
                        "type": "club_participation_interest",
                        "response": response.text,
                    },
                    message.from_user.id,
                    message.from_user.username,
                )

                await send_safe(
                    message.chat.id,
                    "Спасибо, мы обязательно к тебе вернемся в ближайшие дни - будет интересно обсудить. "
                    "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
                )
            else:
                # Timeout or user cancelled
                await send_safe(
                    message.chat.id,
                    "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
                )
        except Exception as e:
            logger.error(f"Error waiting for club participation response: {e}")
            await send_safe(
                message.chat.id,
                "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
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
        },
        state=state,
        timeout=None,
        # columns=2,
    )

    # Log city selection
    from app.router import app

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
        },
        state=state,
        timeout=None,
        columns=5,
    )

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
        },
        state=state,
        timeout=None,
        default_choice=None,
        columns=5,
    )

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
        },
        state=state,
        timeout=None,
        columns=5,
    )

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
        },
        state=state,
        timeout=None,
        columns=5,
    )

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
    willing_to_help = await ask_user_choice(
        message.chat.id,
        "Ты готов был бы помогать в организации встрече в твоем городе весной 2026?\n\n"
        "1 - да, запишите меня!\n"
        "2 - нет, пока что нет пропускной способности, а прийти буду рад!\n"
        "3 - пока что сложно сказать так заранее",
        choices={
            "yes": "1",
            "no": "2",
            "maybe": "3",
        },
        state=state,
        timeout=None,
        columns=3,
    )

    # Log willingness to help
    await app.save_event_log(
        "feedback",
        {
            "type": "willing_to_help",
            "response": willing_to_help,
            "city": city,
        },
        message.from_user.id,
        message.from_user.username,
    )

    # Step 8: Ask for specific comments
    comments = await ask_user_raw(
        message.chat.id,
        "Есть ли у тебя конкретные комментарии? Напиши пожалуйста сюда ответным сообщением.",
        state=state,
        timeout=None,
    )

    # Log comments
    if comments and comments.text:
        await app.save_event_log(
            "feedback",
            {
                "type": "specific_comments",
                "comments": comments.text,
                "city": city,
            },
            message.from_user.id,
            message.from_user.username,
        )

    # Thank the user for feedback
    await send_safe(
        message.chat.id,
        "Спасибо за ответ! Мы будем ждать новых возможностей чтобы увидеться с тобой в ближайшее время. "
        "Смотри на канал @school146club и общий чат на 685 выпускников 146 "
        "(вход модерируется по ссылке https://t.me/+_wm7MlaGhCExOTg6) "
        "чтобы узнать о наших следующих мероприятиях.",
    )

    # Ask if user wants to participate in other Club projects
    try:
        response = await ask_user_raw(
            message.chat.id,
            "Хочешь еще в какие-то проекты Клуба Друзей 146 включаться? Если да, ответь сюда сообщением.",
            state=state,
            timeout=1200,  # 20 minutes timeout
        )

        if response:
            # User responded
            # Log the response
            await app.save_event_log(
                "feedback",
                {
                    "type": "club_participation_interest",
                    "response": response.text,
                },
                message.from_user.id,
                message.from_user.username,
            )

            await send_safe(
                message.chat.id,
                "Спасибо, мы обязательно к тебе вернемся в ближайшие дни - будет интересно обсудить. "
                "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
            )
        else:
            # Timeout or user cancelled
            await send_safe(
                message.chat.id,
                "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
            )
    except Exception as e:
        logger.error(f"Error waiting for club participation response: {e}")
        await send_safe(
            message.chat.id,
            "Если хочешь с нами связаться проактивно, всегда рады, пиши: @marish_me, @petr_lavrov, @istominivan",
        )
