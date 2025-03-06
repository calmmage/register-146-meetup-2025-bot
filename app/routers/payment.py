"""Payment router for the 146 Meetup Register Bot."""

import asyncio
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from datetime import datetime
from loguru import logger
from textwrap import dedent

from app.app import App, TargetCity, GraduateType
from app.router import is_admin, date_of_event, commands_menu
from botspot.user_interactions import ask_user_raw, ask_user_choice
from botspot.utils import send_safe

# Create router
router = Router()
app = App()


# Check if it's an early registration (before March 15)
EARLY_REGISTRATION_DATE = datetime.strptime("2025-03-15", "%Y-%m-%d")
EARLY_REGISTRATION_DATE_HUMAN = "15 Марта"


async def process_payment(
    message: Message,
    state: FSMContext,
    city: str,
    graduation_year: int,
    skip_instructions=False,
    graduate_type: str = GraduateType.GRADUATE.value,
):
    """Process payment for an event registration"""
    # Check if we have original user information in the state
    # This happens when the function is called from a callback handler
    state_data = await state.get_data()
    user_id = state_data.get("original_user_id")
    username = state_data.get("original_username")
    logger.info(f"Using original user information: ID={user_id}, username={username}")

    # Get user registration to get graduate_type
    if user_id:
        registration = await app.get_user_registration(user_id)
        if registration and "graduate_type" in registration:
            graduate_type = registration["graduate_type"]

    # Calculate payment amount
    regular_amount, discount, discounted_amount = app.calculate_payment_amount(
        city, graduation_year, graduate_type
    )

    # Only show instructions if not skipped
    if not skip_instructions:
        from botspot.core.dependency_manager import get_dependency_manager

        deps = get_dependency_manager()
        await deps.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        await asyncio.sleep(3)  # 3 second delay

        # Prepare payment message - split into parts for better UX
        if city == TargetCity.MOSCOW.value:
            payment_formula = "1000р + 200 * (2025 - год выпуска)"
        elif city == TargetCity.PERM.value:
            payment_formula = "500р + 100 * (2025 - год выпуска)"
        else:  # Saint Petersburg
            payment_formula = "за свой счет"

        payment_msg_part1 = dedent(
            f"""
            💰 Оплата мероприятия
            
            Для оплаты мероприятия используется следующая формула:
            
            {city} → {payment_formula}
        """
        )

        # Send part 1
        await send_safe(message.chat.id, payment_msg_part1)

        # Delay between messages
        await asyncio.sleep(5)

        # Check if we're before the early registration deadline
        today = datetime.now()
        is_early_registration_period = today < EARLY_REGISTRATION_DATE

        # discount_amount = regular_amount - final_amount
        if is_early_registration_period:
            payment_msg_part2 = dedent(
                f"""
                Для вас минимальный взнос: {regular_amount} руб.
                
                При ранней оплате (до {EARLY_REGISTRATION_DATE_HUMAN}) - скидка. 
                Минимальная сумма взноса при ранней оплате - {discounted_amount} руб.
                
                Но если перевести больше, то на мероприятие сможет прийти еще один первокурсник 😊
                """
            )
        else:
            payment_msg_part2 = dedent(
                f"""
                Для вас минимальный взнос: {regular_amount} руб.
                
                Но если перевести больше, то на мероприятие сможет прийти еще один первокурсник 😊
                """
            )

        # Send part 2
        await send_safe(message.chat.id, payment_msg_part2)

        # Delay between messages
        await asyncio.sleep(3)

        # Prepare part 3 with payment details
        payment_msg_part3 = dedent(
            f"""
            Реквизиты для оплаты:
            В Тинькофф банк по номеру телефона
            Номер телефона - {app.settings.payment_phone_number}
            Получатель - {app.settings.payment_name}
            """
        )

        # Send part 3
        await send_safe(message.chat.id, payment_msg_part3)

        # Delay between messages
        await asyncio.sleep(3)

    # Create inline keyboard with "Pay Later" button
    pay_later_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплачу позже", callback_data=f"pay_later_{city}")]
        ]
    )

    # Wait for response (either screenshot or callback)
    response = await ask_user_raw(
        message.chat.id,
        "Пожалуйста, отправьте скриншот подтверждения оплаты (фото или PDF) или нажмите кнопку ниже, если хотите оплатить позже.",
        state=state,
        reply_markup=pay_later_markup,
        timeout=1200,
    )

    if response is None:
        # No response received
        await send_safe(
            message.chat.id,
            "⏰ Не получен ответ в течение 20 минут. Пожалуйста, используйте команду /pay для оплаты.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Check if response has photo or document (PDF)
    has_photo = response and hasattr(response, "photo") and response.photo
    has_pdf = (
        response
        and hasattr(response, "document")
        and response.document
        and response.document.mime_type == "application/pdf"
    )

    if has_photo or has_pdf:
        # Save payment info with pending status
        await app.save_payment_info(
            user_id, city, discounted_amount, regular_amount, response.message_id
        )

        # Forward screenshot to events chat (which is used as validation chat)
        try:
            # Get events chat ID from settings
            events_chat_id = app.settings.events_chat_id

            if events_chat_id:
                # if today is before early registration -> "discounted_amount (later {regular amount}}" else "regular_amount"

                today = datetime.now()
                if today < EARLY_REGISTRATION_DATE:
                    needs_to_pay = f"{discounted_amount} руб (после {EARLY_REGISTRATION_DATE_HUMAN} - {regular_amount} руб)"
                else:
                    needs_to_pay = f"{regular_amount} руб"

                # Get user info for the message
                user_info = f"👤 Пользователь: {username or ''} (ID: {user_id})\n"
                user_info += f"📍 Город: {city}\n"
                user_info += f"💰 Сумма к оплате: {needs_to_pay}\n"

                # Get user registration for additional info
                user_registration = await app.get_user_registration(user_id)
                if user_registration:
                    user_info += f"👤 ФИО: {user_registration.get('full_name', 'Неизвестно')}\n"
                    user_info += f"🎓 Выпуск: {user_registration.get('graduation_year', 'Неизвестно')} {user_registration.get('class_letter', '')}\n"

                # Get bot instance
                from botspot.core.dependency_manager import get_dependency_manager

                deps = get_dependency_manager()
                if hasattr(deps, "bot"):
                    bot = deps.bot

                    # Create validation buttons
                    validation_markup = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="✅ Подтвердить",
                                    callback_data=f"confirm_payment_{user_id}_{city}",
                                ),
                                InlineKeyboardButton(
                                    text="❌ Отклонить",
                                    callback_data=f"decline_payment_{user_id}_{city}",
                                ),
                            ]
                        ]
                    )

                    # Send the photo or document with caption containing user info
                    if has_photo:
                        # Get the photo file_id from the message
                        photo = response.photo[-1]  # Get the largest photo

                        # Send the photo with caption
                        forwarded_msg = await bot.send_photo(
                            chat_id=events_chat_id,
                            photo=photo.file_id,
                            caption=user_info,
                            reply_markup=validation_markup,
                        )
                    else:  # has_pdf
                        # Send the PDF document with caption
                        forwarded_msg = await bot.send_document(
                            chat_id=events_chat_id,
                            document=response.document.file_id,
                            caption=user_info,
                            reply_markup=validation_markup,
                        )

                    # Save the screenshot message ID for reference
                    await app.save_payment_info(
                        user_id, city, discounted_amount, regular_amount, forwarded_msg.message_id
                    )

                    logger.info(
                        f"Payment proof from user {user_id} sent to validation chat with caption"
                    )
                else:
                    logger.error(
                        "Bot not available in dependency manager, cannot forward screenshot"
                    )
            else:
                logger.warning("Events chat ID not set, cannot forward screenshot")
        except Exception as e:
            logger.error(f"Error forwarding payment proof to validation chat: {e}")

        # Notify user
        await send_safe(
            message.chat.id,
            "Спасибо за подтверждение оплаты! Ваш платеж находится на проверке. Мы уведомим вас, когда он будет подтвержден.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        # No screenshot received
        await send_safe(
            message.chat.id,
            "Хорошо! Вы можете оплатить позже, используя команду /pay",
            reply_markup=ReplyKeyboardRemove(),
        )

        # Save payment info with pending status
        await app.save_payment_info(user_id, city, discounted_amount, regular_amount)

    # Return True if payment was processed (screenshot or PDF received)
    return has_photo or has_pdf


# Add callback handler for "Pay Later" button
@router.callback_query(lambda c: c.data and c.data.startswith("pay_later_"))
async def pay_later_callback(callback_query: CallbackQuery):
    """Handle pay later button click"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    user_id = callback_query.from_user.id

    # Extract city from callback data
    city = callback_query.data.split("_")[2] if callback_query.data else ""

    # Answer callback to remove loading state
    await callback_query.answer()

    # Notify user
    await send_safe(
        user_id,
        "Хорошо! Вы можете оплатить позже, используя команду /pay",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Save payment info with pending status if city is valid
    if city:
        # Get user registration
        user_registration = await app.get_user_registration(user_id)
        if user_registration and user_registration.get("target_city") == city:
            graduation_year = user_registration.get("graduation_year", 2025)

            # Calculate payment amount
            regular_amount, discount, discounted_amount = app.calculate_payment_amount(
                city, graduation_year
            )

            # Save payment info
            await app.save_payment_info(user_id, city, discounted_amount, regular_amount)


# Add payment command handler
@commands_menu.add_command("pay", "Оплатить участие")
@router.message(Command("pay"))
async def pay_handler(message: Message, state: FSMContext):
    """Handle payment for registered users"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    user_id = message.from_user.id

    # Check if user is registered
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        await send_safe(
            message.chat.id,
            "Вы еще не зарегистрированы на встречу. Используйте /start для регистрации.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Filter registrations that require payment
    # Skip St. Petersburg and teachers
    payment_registrations = [
        reg
        for reg in registrations
        if reg["target_city"] != TargetCity.SAINT_PETERSBURG.value
        and reg.get("graduate_type", GraduateType.GRADUATE.value) != GraduateType.TEACHER.value
    ]

    if not payment_registrations:
        await send_safe(
            message.chat.id,
            "У вас нет регистраций, требующих оплаты.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # If user has multiple registrations requiring payment, ask which one to pay for
    if len(payment_registrations) > 1:
        choices = {}
        for reg in payment_registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)
            status = reg.get("payment_status", "не оплачено")
            status_emoji = "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"

            if city_enum is not None:
                choices[city] = f"{city} ({date_of_event[city_enum]}) - {status_emoji} {status}"
            else:
                choices[city] = f"{city} - {status_emoji} {status}"

        response = await ask_user_choice(
            message.chat.id,
            "У вас несколько регистраций. Для какого города вы хотите оплатить участие?",
            choices=choices,
            state=state,
            timeout=None,
        )

        # Find the selected registration
        selected_reg = next(
            (reg for reg in payment_registrations if reg["target_city"] == response), None
        )
    else:
        # Only one registration requiring payment
        selected_reg = payment_registrations[0]

    if selected_reg:
        # Check if user has already seen payment instructions
        # We'll use payment_status to determine this - if it's set, they've seen instructions
        skip_instructions = selected_reg.get("payment_status") is not None

        # Store the original user information in the state
        await state.update_data(
            original_user_id=user_id, original_username=message.from_user.username
        )

        # Get graduate_type if available
        graduate_type = selected_reg.get("graduate_type", GraduateType.GRADUATE.value)

        # Process payment for the selected registration
        await process_payment(
            message,
            state,
            selected_reg["target_city"],
            selected_reg["graduation_year"],
            skip_instructions,
            graduate_type=graduate_type,
        )
    else:
        await send_safe(
            message.chat.id,
            "Произошла ошибка при выборе регистрации. Пожалуйста, попробуйте еще раз.",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.callback_query(lambda c: c.data == "pay_now")
async def pay_now_callback(callback_query: CallbackQuery, state: FSMContext):
    """Handle pay now button click from start handler - now calls the payment process directly"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    user_id = callback_query.from_user.id

    # Answer callback to remove loading state
    await callback_query.answer()

    # Get user registration
    registration = await app.get_user_registration(user_id)

    if not registration:
        await send_safe(
            user_id,
            "Вы еще не зарегистрированы на встречу. Используйте /start для регистрации.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Check if this registration requires payment
    city = registration.get("target_city")
    graduate_type = registration.get("graduate_type", GraduateType.GRADUATE.value)

    if city == TargetCity.SAINT_PETERSBURG.value:
        await send_safe(
            user_id,
            "Для встречи в Санкт-Петербурге оплата не требуется.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if graduate_type == GraduateType.TEACHER.value:
        await send_safe(
            user_id,
            "Для учителей участие бесплатное. Спасибо за вашу работу!",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Get graduation year
    graduation_year = registration.get("graduation_year", 2025)

    # Process payment
    # Skip instructions if payment status is already set (user has seen them before)
    skip_instructions = registration.get("payment_status") is not None

    # Store the original user information in the state
    await state.update_data(
        original_user_id=user_id, original_username=callback_query.from_user.username
    )

    await process_payment(
        callback_query.message,
        state,
        city,
        graduation_year,
        skip_instructions,
        graduate_type=graduate_type,
    )


# This is no longer needed since we've consolidated the flow, but keeping it for backward
# compatibility with any existing buttons in user conversations
@router.callback_query(lambda c: c.data == "pay_later_from_start")
async def pay_later_from_start_callback(callback_query: CallbackQuery, state: FSMContext):
    """Handle pay later button click from start handler - now redirects to main registration flow"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    user_id = callback_query.from_user.id

    # Answer callback to remove loading state
    await callback_query.answer("Перенаправление в управление регистрацией")

    # Get user registration
    registration = await app.get_user_registration(user_id)

    if registration:
        # Redirect to the main registration management flow
        from app.router import handle_registered_user

        await handle_registered_user(callback_query.message, state, registration)
    else:
        # This shouldn't happen, but just in case
        await send_safe(
            user_id,
            "У вас нет активных регистраций. Используйте /start для регистрации на встречу.",
            reply_markup=ReplyKeyboardRemove(),
        )


# End of file - remove everything below this line


# Define payment states
class PaymentStates(StatesGroup):
    waiting_for_confirm_amount = State()
    waiting_for_decline_reason = State()


# Add callback handlers for payment confirmation/decline buttons
@router.callback_query(lambda c: c.data and c.data.startswith("confirm_payment_"))
async def confirm_payment_callback(callback_query: CallbackQuery, state: FSMContext):
    """Confirm a payment"""
    # Extract user_id and city from callback data
    parts = callback_query.data.split("_")
    if len(parts) < 3:
        await callback_query.answer("Invalid callback data")
        return

    user_id = int(parts[2])
    city = parts[3] if len(parts) > 3 else None

    if not city:
        await callback_query.answer("Missing city information")
        return

    # Get registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})
    if not registration:
        await callback_query.answer("Registration not found")
        return

    # Get the discounted amount to suggest as default
    discounted_amount = registration.get("discounted_payment_amount", 0)
    regular_amount = registration.get("regular_payment_amount", 0)

    # Determine the relevant recommendation amount based on the current date
    today = datetime.now()
    recommended_amount = discounted_amount if today < EARLY_REGISTRATION_DATE else regular_amount

    chat_id = callback_query.message.chat.id
    # Ask for payment amount directly using ask_user_raw, suggesting the recommended amount
    amount_response = await ask_user_raw(
        chat_id,
        f"Укажите сумму платежа для пользователя ID:{user_id}, город: {city}\n(Рекомендуемая сумма: {recommended_amount} руб.)",
        state=state,
        timeout=300,
    )

    if amount_response is None or amount_response.text is None:
        await send_safe(chat_id, "Время ожидания истекло или получен некорректный ответ.")
        return

    # Try to parse the amount
    try:
        payment_amount = int(amount_response.text)
    except ValueError:
        await send_safe(
            chat_id, "Некорректная сумма платежа. Пожалуйста, используйте команду снова."
        )
        return

    # Update payment status
    await app.update_payment_status(user_id, city, "confirmed", payment_amount=payment_amount)

    # Log the confirmation
    admin = callback_query.from_user
    admin_info = f"{admin.username or admin.id}" if admin else "Unknown"

    # Get updated registration with total payment amount
    updated_registration = await app.collection.find_one({"user_id": user_id, "target_city": city})
    total_payment = updated_registration.get("payment_amount", payment_amount)

    # Check if this was an additional payment
    is_additional_payment = total_payment != payment_amount

    # Check if the total payment amount is less than the recommended amount
    payment_message = ""

    if is_additional_payment:
        payment_message = (
            f"✅ Ваш дополнительный платеж на сумму {payment_amount} руб. подтвержден!\n"
        )
        payment_message += (
            f"Общая сумма внесенных платежей: {total_payment} руб. Спасибо за оплату."
        )
    else:
        payment_message = f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден! Сумма: {payment_amount} руб. Спасибо за оплату."

    if total_payment < recommended_amount:
        shortfall = recommended_amount - total_payment
        payment_message += f"\n\nОбратите внимание, что ваш общий взнос на {shortfall} руб. меньше рекомендуемой суммы ({recommended_amount} руб.). "
        payment_message += "Если у вас будет возможность, вы можете доплатить эту сумму позже, используя команду /pay."

    # Notify user
    await send_safe(
        user_id,
        payment_message,
    )

    # Update callback message
    if callback_query.message:
        # Get user info for the confirmation message
        user_info = f"{registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')})"

        # Update the message text or caption
        if is_additional_payment:
            payment_status = f"✅ ДОПОЛНИТЕЛЬНЫЙ ПЛАТЕЖ ПОДТВЕРЖДЕН\nСумма: {payment_amount} руб.\nВсего оплачено: {total_payment} руб."
        else:
            payment_status = f"✅ ПЛАТЕЖ ПОДТВЕРЖДЕН\nСумма: {payment_amount} руб."

        # Add note about payment being less than recommended if applicable
        if total_payment < recommended_amount:
            payment_status += (
                f"\n⚠️ На {recommended_amount - total_payment} руб. меньше рекомендуемой суммы!"
            )

        # Add payment history if available
        payment_history = updated_registration.get("payment_history", [])
        if len(payment_history) > 1:
            payment_status += "\n\nИстория платежей:"
            for i, payment in enumerate(payment_history):
                payment_status += f"\n{i+1}. {payment['amount']} руб. ({payment['timestamp'][:10]})"

        if callback_query.message.caption:
            caption = callback_query.message.caption
            new_caption = f"{caption}\n\n{payment_status}"

            # Limit caption length
            if len(new_caption) > 1024:
                new_caption = new_caption[-1024:]

            await callback_query.message.edit_caption(caption=new_caption, reply_markup=None)
        else:
            text = callback_query.message.text or ""
            new_text = f"{text}\n\n{payment_status} для {user_info}"

            await callback_query.message.edit_text(text=new_text, reply_markup=None)

    # Confirm to admin with a brief notification
    await callback_query.answer("Платеж подтвержден")

    # Auto-export to sheets after payment confirmation
    await app.export_registered_users_to_google_sheets()


@router.callback_query(lambda c: c.data and c.data.startswith("decline_payment_"))
async def decline_payment_callback(callback_query: CallbackQuery, state: FSMContext):
    """Ask for decline reason"""
    # Extract user_id and city from callback data
    parts = callback_query.data.split("_")
    if len(parts) < 3:
        await callback_query.answer("Invalid callback data")
        return

    user_id = int(parts[2])
    city = parts[3] if len(parts) > 3 else None

    if not city:
        await callback_query.answer("Missing city information")
        return

    # Save data for the next step
    await state.set_state(PaymentStates.waiting_for_decline_reason)
    await state.update_data(
        decline_user_id=user_id, decline_city=city, callback_message=callback_query.message
    )

    # Ask for decline reason by editing the original message
    if callback_query.message:
        # Keep the original caption/text but add a prompt
        if callback_query.message.caption:
            caption = callback_query.message.caption
            new_caption = f"{caption}\n\n⚠️ Укажите причину отклонения платежа в ответном сообщении:"

            # Limit caption length
            if len(new_caption) > 1024:
                new_caption = new_caption[-1024:]

            await callback_query.message.edit_caption(caption=new_caption, reply_markup=None)
        else:
            text = callback_query.message.text or ""
            new_text = f"{text}\n\n⚠️ Укажите причину отклонения платежа в ответном сообщении:"

            await callback_query.message.edit_text(text=new_text, reply_markup=None)
    else:
        # Fallback if message is not available
        await callback_query.answer("Укажите причину отклонения в следующем сообщении")


@router.message(PaymentStates.waiting_for_decline_reason)
async def payment_decline_reason_handler(message: Message, state: FSMContext):
    """Handle payment decline reason"""
    # Check if user is admin
    if not is_admin(message.from_user):
        return

    # Get data from state
    data = await state.get_data()
    user_id = data.get("decline_user_id")
    city = data.get("decline_city")
    callback_message = data.get("callback_message")

    if not user_id or not city:
        await message.reply("Ошибка: не найдена информация о платеже")
        await state.clear()
        return

    # Get decline reason
    decline_reason = message.text or "Причина не указана"

    # Update payment status
    await app.update_payment_status(user_id, city, "declined", decline_reason)

    # Get registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})
    if not registration:
        await message.reply(f"Регистрация не найдена для пользователя {user_id}")
        await state.clear()
        return

    # Notify user
    await send_safe(
        user_id,
        f"❌ Ваш платеж для участия во встрече в городе {city} отклонен.\n\nПричина: {decline_reason}\n\nПожалуйста, используйте команду /pay для повторной оплаты.",
    )

    # Update the original callback message if available
    if callback_message:
        # Get user info for the decline message
        user_info = f"{registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')})"

        try:
            # Update the message text or caption
            if hasattr(callback_message, "caption") and callback_message.caption:
                caption = callback_message.caption
                # Remove the prompt if it exists
                caption = caption.split("\n\n⚠️ Укажите причину")[0]
                new_caption = f"{caption}\n\n❌ ПЛАТЕЖ ОТКЛОНЕН\nПричина: {decline_reason}"

                # Limit caption length
                if len(new_caption) > 1024:
                    new_caption = new_caption[-1024:]

                await callback_message.edit_caption(caption=new_caption, reply_markup=None)
            elif hasattr(callback_message, "text"):
                text = callback_message.text or ""
                # Remove the prompt if it exists
                text = text.split("\n\n⚠️ Укажите причину")[0]
                new_text = (
                    f"{text}\n\n❌ ПЛАТЕЖ ОТКЛОНЕН для {user_info}\nПричина: {decline_reason}"
                )

                await callback_message.edit_text(text=new_text, reply_markup=None)
        except Exception as e:
            logger.error(f"Error updating callback message: {e}")

    # Confirm to admin with a brief reply
    await message.reply(f"❌ Платеж отклонен")

    # Clear state
    await state.clear()
