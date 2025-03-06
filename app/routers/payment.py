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
from loguru import logger
from textwrap import dedent

from app.app import App, TargetCity
from app.router import is_admin, date_of_event, commands_menu
from botspot.user_interactions import ask_user_raw, ask_user_choice
from botspot.utils import send_safe

# Create router
router = Router()
app = App()


async def process_payment(
    message: Message, state: FSMContext, city: str, graduation_year: int, skip_instructions=False
):
    """Process payment for an event registration"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    user_id = message.from_user.id
    username = message.from_user.username

    # Check if we have original user information in the state
    # This happens when the function is called from a callback handler
    state_data = await state.get_data()
    original_user_id = state_data.get("original_user_id")
    original_username = state_data.get("original_username")

    # Use original user information if available
    if original_user_id:
        user_id = original_user_id
        username = original_username
        logger.info(f"Using original user information: ID={user_id}, username={username}")

    # Calculate payment amount
    regular_amount, discount, discounted_amount = app.calculate_payment_amount(
        city, graduation_year
    )

    # Only show instructions if not skipped
    if not skip_instructions:
        # Show typing status and delay
        try:
            from botspot.core.dependency_manager import get_dependency_manager

            deps = get_dependency_manager()
            if hasattr(deps, "bot"):
                bot = deps.bot
                await bot.send_chat_action(chat_id=message.chat.id, action="typing")
                await asyncio.sleep(3)  # 3 second delay
            else:
                logger.warning("Bot not available in dependency manager, skipping typing indicator")
                await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"Could not show typing indicator: {e}")
            await asyncio.sleep(3)

        # Check if it's an early registration (before March 15)
        early_registration_date = "2025-03-15"

        # Prepare payment message - split into parts for better UX
        payment_formula = ""
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

        # discount_amount = regular_amount - final_amount
        payment_msg_part2 = dedent(
            f"""
            Для вас минимальный взнос: {regular_amount} руб.
            
            При ранней регистрации (до {early_registration_date}) - скидка. 
            Минимальная сумма взноса при ранней регистрации - {discounted_amount}
            
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

    # Request screenshot separately to get the message object
    screenshot_request_msg = await send_safe(
        message.chat.id,
        "Пожалуйста, отправьте скриншот подтверждения оплаты или нажмите кнопку ниже, если хотите оплатить позже.",
        reply_markup=pay_later_markup,
    )

    # Wait for response (either screenshot or callback)
    response = await ask_user_raw(
        message.chat.id,
        "Ожидаю скриншот оплаты...",  # Use a non-empty message
        state=state,
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

    if response and hasattr(response, "photo") and response.photo:
        # Save payment info with pending status
        await app.save_payment_info(
            user_id, city, discounted_amount, regular_amount, response.message_id
        )

        # Forward screenshot to events chat (which is used as validation chat)
        try:
            # Get events chat ID from settings
            events_chat_id = app.settings.events_chat_id

            if events_chat_id:
                # Get user info for the message
                user_info = f"👤 Пользователь: {username or ''} (ID: {user_id})\n"
                user_info += f"📍 Город: {city}\n"
                user_info += f"💰 Сумма к оплате: {regular_amount} руб.\n"

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

                    # Get the photo file_id from the message
                    photo = response.photo[-1]  # Get the largest photo

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

                    # Send the photo with caption containing user info
                    forwarded_msg = await bot.send_photo(
                        chat_id=events_chat_id,
                        photo=photo.file_id,
                        caption=user_info,
                        reply_markup=validation_markup,
                    )

                    # Save the screenshot message ID for reference
                    await app.save_payment_info(
                        user_id, city, discounted_amount, regular_amount, forwarded_msg.message_id
                    )

                    logger.info(
                        f"Payment screenshot from user {user_id} sent to validation chat with caption"
                    )
                else:
                    logger.error(
                        "Bot not available in dependency manager, cannot forward screenshot"
                    )
            else:
                logger.warning("Events chat ID not set, cannot forward screenshot")
        except Exception as e:
            logger.error(f"Error forwarding screenshot to validation chat: {e}")

        # Notify user
        await send_safe(
            message.chat.id,
            "Спасибо за скриншот! Ваш платеж находится на проверке. Мы уведомим вас, когда он будет подтвержден.",
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

    # Get user registration for logging
    user_registration = await app.get_user_registration(user_id)

    # Log to events chat
    try:
        await app.log_payment_submission(
            user_id, username or "", user_registration or {}, discounted_amount, regular_amount
        )
    except Exception as e:
        logger.warning(f"Could not log payment submission: {e}")

    # Return True if payment was processed (screenshot received)
    return response and hasattr(response, "photo") and response.photo


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

            # Log payment postponed
            username = callback_query.from_user.username or ""
            try:
                await app.log_payment_submission(
                    user_id, username, user_registration, discounted_amount, regular_amount
                )
            except Exception as e:
                logger.warning(f"Could not log payment postponement: {e}")


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
    payment_registrations = [
        reg for reg in registrations if reg["target_city"] != TargetCity.SAINT_PETERSBURG.value
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

        # Process payment for the selected registration
        await process_payment(
            message,
            state,
            selected_reg["target_city"],
            selected_reg["graduation_year"],
            skip_instructions,
        )
    else:
        await send_safe(
            message.chat.id,
            "Произошла ошибка при выборе регистрации. Пожалуйста, попробуйте еще раз.",
            reply_markup=ReplyKeyboardRemove(),
        )


# Validation command handler
@router.message(Command("validate"))
async def validate_payment_handler(message: Message):
    """Handle payment validation from admins"""
    # Check if user is admin
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    if not is_admin(message.from_user):
        return

    # Check if this is a reply to a message
    if not message.reply_to_message:
        await send_safe(
            message.chat.id,
            "Эта команда должна быть ответом на скриншот платежа.",
        )
        return

    # Parse the command arguments to get the payment amount
    if message.text is None:
        await send_safe(
            message.chat.id,
            "Некорректная команда.",
        )
        return

    command_parts = message.text.split()

    # Extract payment amount
    payment_amount = None
    if len(command_parts) >= 2:
        try:
            payment_amount = int(command_parts[1])
        except ValueError:
            await send_safe(
                message.chat.id,
                "Некорректная сумма платежа. Пожалуйста, укажите число.",
            )
            return

    # Find the user information
    try:
        user_id = None
        city = None

        # Check if the message was forwarded from a user
        if message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
            logger.info(f"Found user_id {user_id} from forward_from")

            # Try to get city from caption or text
            if message.reply_to_message.caption is not None:
                for line in message.reply_to_message.caption.split("\n"):
                    if "Город:" in line:
                        try:
                            city = line.split("Город:")[1].strip()
                            logger.info(f"Found city {city} from caption")
                        except IndexError:
                            pass

        # If we couldn't find user_id from forward_from, check caption
        if not user_id and message.reply_to_message.caption is not None:
            caption = message.reply_to_message.caption
            # Extract user_id and city from caption
            for line in caption.split("\n"):
                if "ID:" in line:
                    try:
                        user_id = int(line.split("ID:")[1].strip().split()[0])
                        logger.info(f"Found user_id {user_id} from caption")
                    except (ValueError, IndexError):
                        pass
                if "Город:" in line:
                    try:
                        city = line.split("Город:")[1].strip()
                        logger.info(f"Found city {city} from caption")
                    except IndexError:
                        pass

        # If we still couldn't find info, check if there's a message before the screenshot
        if (not user_id or not city) and message.reply_to_message.reply_to_message:
            info_message = message.reply_to_message.reply_to_message
            if info_message.text:
                for line in info_message.text.split("\n"):
                    if "ID:" in line:
                        try:
                            user_id = int(line.split("ID:")[1].strip().split()[0])
                            logger.info(f"Found user_id {user_id} from reply chain")
                        except (ValueError, IndexError):
                            pass
                    if "Город:" in line:
                        try:
                            city = line.split("Город:")[1].strip()
                            logger.info(f"Found city {city} from reply chain")
                        except IndexError:
                            pass

        # If we still couldn't find the info, check command arguments
        if not user_id or not city:
            if len(command_parts) >= 4:
                try:
                    user_id = int(command_parts[2])
                    city = command_parts[3]
                    logger.info(f"Found user_id {user_id} and city {city} from command arguments")
                except (ValueError, IndexError):
                    pass

            # If we still don't have the info, ask admin to provide it
            if not user_id or not city:
                await send_safe(
                    message.chat.id,
                    "Не удалось автоматически определить пользователя и город. "
                    "Пожалуйста, используйте формат: /validate <сумма> <user_id> <город>",
                )
                return

        # Update payment status
        await app.update_payment_status(user_id, city, "confirmed")

        # Get the registration
        registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

        if not registration:
            await send_safe(
                message.chat.id,
                f"Регистрация не найдена для пользователя {user_id} в городе {city}.",
            )
            return

        # Log confirmation
        admin_username = message.from_user.username if message.from_user else None
        admin_id = message.from_user.id if message.from_user else None

        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "confirmed",
            f"Подтверждено администратором {admin_username or admin_id}. Сумма: {payment_amount} руб.",
        )

        # Notify user
        await send_safe(
            user_id,
            f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден! Спасибо за оплату.",
        )

        # Confirm to admin
        await send_safe(
            message.chat.id,
            f"✅ Платеж подтвержден для пользователя {registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')}).",
        )

    except Exception as e:
        logger.error(f"Error validating payment: {e}")
        await send_safe(
            message.chat.id,
            f"Произошла ошибка при валидации платежа: {e}",
        )


# Decline command handler
@router.message(Command("decline"))
async def decline_payment_handler(message: Message):
    """Handle payment decline from admins"""
    # Check if user is admin
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    if not is_admin(message.from_user):
        return

    # Check if this is a reply to a message
    if not message.reply_to_message:
        await send_safe(
            message.chat.id,
            "Эта команда должна быть ответом на скриншот платежа.",
        )
        return

    # Parse the command arguments to get the reason
    if message.text is None:
        await send_safe(
            message.chat.id,
            "Некорректная команда.",
        )
        return

    command_parts = message.text.split(maxsplit=1)
    reason = command_parts[1] if len(command_parts) > 1 else "Причина не указана"

    # Find the original message with user info
    try:
        # Since get_chat_history is not available, we'll use a different approach
        # We'll extract user info from the context of the conversation

        # Look for user ID in the message thread
        user_id = None
        city = None

        # Check if there's a reply chain we can follow
        if message.reply_to_message and message.reply_to_message.reply_to_message:
            info_message = message.reply_to_message.reply_to_message
            if info_message.text and "ID:" in info_message.text and "Город:" in info_message.text:
                # Extract user ID and city from the message
                for line in info_message.text.split("\n"):
                    if "ID:" in line:
                        try:
                            user_id = int(line.split("ID:")[1].strip().rstrip(")"))
                        except (ValueError, IndexError):
                            pass
                    if "Город:" in line:
                        try:
                            city = line.split("Город:")[1].strip()
                        except IndexError:
                            pass

        # If we couldn't find the info in the reply chain, ask admin to provide it
        if not user_id or not city:
            await send_safe(
                message.chat.id,
                "Не удалось автоматически определить пользователя и город. "
                "Пожалуйста, используйте формат: /decline <причина> <user_id> <город>",
            )

            # Check if admin provided user_id and city in the command
            command_text = message.text
            parts = command_text.split()
            if len(parts) >= 4:
                try:
                    # Format is: /decline <reason> <user_id> <city>
                    # We need to extract user_id and city from the end
                    user_id = int(parts[-2])
                    city = parts[-1]
                    # Recalculate reason without the user_id and city
                    reason = " ".join(parts[1:-2])
                except (ValueError, IndexError):
                    return
            else:
                return

        # Update payment status
        await app.update_payment_status(user_id, city, "declined", reason)

        # Get the registration
        registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

        if not registration:
            await send_safe(
                message.chat.id,
                f"Регистрация не найдена для пользователя {user_id} в городе {city}.",
            )
            return

        # Log decline
        admin_username = message.from_user.username if message.from_user else None
        admin_id = message.from_user.id if message.from_user else None

        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "declined",
            f"Отклонено администратором {admin_username or admin_id}. Причина: {reason}",
        )

        # Notify user
        await send_safe(
            user_id,
            f"❌ Ваш платеж для участия во встрече в городе {city} отклонен.\n\nПричина: {reason}\n\nПожалуйста, повторите оплату с учетом указанной причины и отправьте новый скриншот, используя команду /pay.",
        )

        # Confirm to admin
        await send_safe(
            message.chat.id,
            f"❌ Платеж отклонен для пользователя {registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')}).",
        )

    except Exception as e:
        logger.error(f"Error declining payment: {e}")
        await send_safe(
            message.chat.id,
            f"Произошла ошибка при отклонении платежа: {e}",
        )


# Add callback handler for "Pay Now" button
@router.callback_query(lambda c: c.data == "pay_now")
async def pay_now_callback(callback_query: CallbackQuery, state: FSMContext):
    """Handle pay now button click from start handler"""
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
    if city == TargetCity.SAINT_PETERSBURG.value:
        await send_safe(
            user_id,
            "Для встречи в Санкт-Петербурге оплата не требуется.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Get graduation year
    graduation_year = registration.get("graduation_year", 2025)

    # Process payment
    # Skip instructions if payment status is already set (user has seen them before)
    skip_instructions = registration.get("payment_status") is not None

    # Create a new message to use for the payment process
    # This avoids the issue with InaccessibleMessage
    intro_message = await send_safe(
        user_id,
        "Начинаем процесс оплаты...",
    )

    # Store the original user information in the state
    await state.update_data(
        original_user_id=user_id, original_username=callback_query.from_user.username
    )

    # Use the new message for payment processing
    await process_payment(intro_message, state, city, graduation_year, skip_instructions)


# Add callback handler for "Pay Later from Start" button
@router.callback_query(lambda c: c.data == "pay_later_from_start")
async def pay_later_from_start_callback(callback_query: CallbackQuery):
    """Handle pay later button click from start handler"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    user_id = callback_query.from_user.id

    # Answer callback to remove loading state
    await callback_query.answer()

    # Notify user
    await send_safe(
        user_id,
        "Хорошо! Вы можете оплатить позже, используя команду /pay",
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
    """Handle payment confirmation from admin via button"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    # Check if user is admin
    if not is_admin(callback_query.from_user):
        await callback_query.answer(
            "Только администраторы могут подтверждать платежи", show_alert=False
        )
        return

    # Check if message is available
    if callback_query.message is None or callback_query.message.chat is None:
        logger.error("Callback message or chat is None")
        await callback_query.answer("Ошибка: сообщение недоступно", show_alert=False)
        return

    # Parse the callback data
    try:
        # Make sure callback_query.data is not None before splitting
        if callback_query.data is None:
            logger.error("Callback data is None")
            await callback_query.answer(
                "Ошибка: данные обратного вызова отсутствуют", show_alert=False
            )
            return

        _, _, user_id_str, city = callback_query.data.split("_", 3)
        user_id = int(user_id_str)

        # Get the chat ID
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id

        # Answer the callback without alert
        await callback_query.answer()

        # Ask for payment amount directly using ask_user_raw
        amount_response = await ask_user_raw(
            chat_id,
            f"Укажите сумму платежа для пользователя ID:{user_id}, город: {city}",
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
        await app.update_payment_status(user_id, city, "confirmed")

        # Get the registration
        registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

        if not registration:
            await send_safe(
                chat_id,
                f"Регистрация не найдена для пользователя {user_id} в городе {city}",
            )
            return

        # Log confirmation
        admin_username = callback_query.from_user.username if callback_query.from_user else None
        admin_id = callback_query.from_user.id if callback_query.from_user else None

        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "confirmed",
            f"Подтверждено администратором {admin_username or admin_id}. Сумма: {payment_amount} руб.",
        )

        # Notify user
        await send_safe(
            user_id,
            f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден! Спасибо за оплату.",
        )

        # Update the original message if possible
        if message_id:
            from botspot.core.dependency_manager import get_dependency_manager

            deps = get_dependency_manager()
            bot = getattr(deps, "bot", None)
            
            if bot:
                # Get current caption from reply message
                current_caption = ""
                if message.reply_to_message:
                    current_caption = getattr(message.reply_to_message, "caption", "") or ""
                
                # Append confirmation to the existing caption
                new_caption = f"{current_caption}\n\n✅ ПЛАТЕЖ ПОДТВЕРЖДЕН\nСумма: {payment_amount} руб."
                
                # Limit caption length to Telegram's maximum
                if len(new_caption) > 1024:
                    new_caption = new_caption[-1024:]
                
                try:
                    # Update the caption and remove reply markup
                    await bot.edit_message_caption(
                        chat_id=message.chat.id,
                        message_id=message_id,
                        caption=new_caption,
                        reply_markup=None,
                    )
                except Exception as e:
                    logger.error(f"Error updating message after confirmation: {e}")

        # Clear state
        await state.clear()

    except Exception as e:
        logger.error(f"Error confirming payment via callback: {e}")
        await callback_query.answer(f"Ошибка: {e}", show_alert=False)


@router.callback_query(lambda c: c.data and c.data.startswith("decline_payment_"))
async def decline_payment_callback(callback_query: CallbackQuery, state: FSMContext):
    """Handle payment decline from admin via button"""
    if callback_query.from_user is None:
        logger.error("Callback from_user is None")
        return

    # Check if user is admin
    if not is_admin(callback_query.from_user):
        await callback_query.answer(
            "Только администраторы могут отклонять платежи", show_alert=False
        )
        return

    # Check if message is available
    if callback_query.message is None or callback_query.message.chat is None:
        logger.error("Callback message or chat is None")
        await callback_query.answer("Ошибка: сообщение недоступно", show_alert=False)
        return

    # Parse the callback data
    try:
        # Make sure callback_query.data is not None before splitting
        if callback_query.data is None:
            logger.error("Callback data is None")
            await callback_query.answer(
                "Ошибка: данные обратного вызова отсутствуют", show_alert=False
            )
            return

        _, _, user_id_str, city = callback_query.data.split("_", 3)
        user_id = int(user_id_str)

        # Get the chat ID
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id

        # Answer the callback without alert
        await callback_query.answer()

        # Ask for decline reason directly using ask_user_raw
        reason_response = await ask_user_raw(
            chat_id,
            f"Укажите причину отклонения платежа для пользователя ID:{user_id}, город: {city}",
            state=state,
            timeout=300,
        )

        if reason_response is None or reason_response.text is None:
            await send_safe(chat_id, "Время ожидания истекло или получен некорректный ответ.")
            return

        decline_reason = reason_response.text

        # Update payment status
        await app.update_payment_status(user_id, city, "declined", decline_reason)

        # Get the registration
        registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

        if not registration:
            await send_safe(
                chat_id,
                f"Регистрация не найдена для пользователя {user_id} в городе {city}",
            )
            return

        # Log decline
        admin_username = callback_query.from_user.username if callback_query.from_user else None
        admin_id = callback_query.from_user.id if callback_query.from_user else None

        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "declined",
            f"Отклонено администратором {admin_username or admin_id}. Причина: {decline_reason}",
        )

        # Notify user
        await send_safe(
            user_id,
            f"❌ Ваш платеж для участия во встрече в городе {city} отклонен.\n\nПричина: {decline_reason}\n\nПожалуйста, используйте команду /pay для повторной оплаты.",
        )

        # Update the original message if possible
        if message_id:
            from botspot.core.dependency_manager import get_dependency_manager

            deps = get_dependency_manager()
            bot = getattr(deps, "bot", None)
            
            if bot:
                # Get current caption from reply message
                current_caption = ""
                if message.reply_to_message:
                    current_caption = getattr(message.reply_to_message, "caption", "") or ""
                
                # Append decline reason to the existing caption
                new_caption = f"{current_caption}\n\n❌ ПЛАТЕЖ ОТКЛОНЕН\nПричина: {decline_reason}"
                
                # Limit caption length to Telegram's maximum
                if len(new_caption) > 1024:
                    new_caption = new_caption[-1024:]
                
                try:
                    # Update the caption and remove reply markup
                    await bot.edit_message_caption(
                        chat_id=message.chat.id,
                        message_id=message_id,
                        caption=new_caption,
                        reply_markup=None,
                    )
                except Exception as e:
                    logger.error(f"Error editing caption: {e}")
                    
                    # If editing caption fails, try to remove reply markup
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=message.chat.id, message_id=message_id, reply_markup=None
                        )
                    except Exception as e2:
                        logger.error(f"Error removing reply markup: {e2}")

        # Confirm to admin
        await send_safe(
            message.chat.id,
            f"❌ Платеж отклонен для пользователя {registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')}).",
        )

        # Clear state
        await state.clear()

    except Exception as e:
        logger.error(f"Error declining payment via callback: {e}")
        await callback_query.answer(f"Ошибка: {e}", show_alert=False)


# Handler for confirm amount
@router.message(PaymentStates.waiting_for_confirm_amount)
async def payment_confirm_amount_handler(message: Message, state: FSMContext):
    """Handle payment amount from admin"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Check if user is admin
    if not is_admin(message.from_user):
        return

    # Get the data from state
    data = await state.get_data()
    user_id = data.get("confirm_user_id")
    city = data.get("confirm_city")
    message_id = data.get("message_id")

    if not user_id or not city:
        await send_safe(
            message.chat.id,
            "Ошибка: не найдена информация о платеже для подтверждения",
        )
        await state.clear()
        return

    # Get the payment amount
    payment_amount = None
    try:
        # Ensure we're working with a string before conversion
        text = message.text if message.text is not None else ""
        payment_amount = int(text)
    except (ValueError, TypeError):
        await send_safe(
            message.chat.id,
            "Некорректная сумма платежа. Пожалуйста, укажите число.",
        )
        return

    # Update payment status
    await app.update_payment_status(user_id, city, "confirmed")

    # Get the registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

    if not registration:
        await send_safe(
            message.chat.id,
            f"Регистрация не найдена для пользователя {user_id} в городе {city}",
        )
        await state.clear()
        return

    # Log confirmation
    admin_username = message.from_user.username if message.from_user else None
    admin_id = message.from_user.id if message.from_user else None

    await app.log_payment_verification(
        user_id,
        registration.get("username", ""),
        registration,
        "confirmed",
        f"Подтверждено администратором {admin_username or admin_id}. Сумма: {payment_amount} руб.",
    )

    # Notify user
    await send_safe(
        user_id,
        f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден! Спасибо за оплату.",
    )

    # Update the original message if possible
    if message_id:
        from botspot.core.dependency_manager import get_dependency_manager

        deps = get_dependency_manager()
        bot = getattr(deps, "bot", None)
        
        if bot:
            # Get current caption from reply message
            current_caption = ""
            if message.reply_to_message:
                current_caption = getattr(message.reply_to_message, "caption", "") or ""
            
            # Append confirmation to the existing caption
            new_caption = f"{current_caption}\n\n✅ ПЛАТЕЖ ПОДТВЕРЖДЕН\nСумма: {payment_amount} руб."
            
            # Limit caption length to Telegram's maximum
            if len(new_caption) > 1024:
                new_caption = new_caption[-1024:]
            
            try:
                # Update the caption and remove reply markup
                await bot.edit_message_caption(
                    chat_id=message.chat.id,
                    message_id=message_id,
                    caption=new_caption,
                    reply_markup=None,
                )
            except Exception as e:
                logger.error(f"Error updating message after confirmation: {e}")

    # Clear state
    await state.clear()


# Handler for decline reason
@router.message(PaymentStates.waiting_for_decline_reason)
async def payment_decline_reason_handler(message: Message, state: FSMContext):
    """Handle payment decline reason from admin"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Check if user is admin
    if not is_admin(message.from_user):
        return

    # Get the data from state
    data = await state.get_data()
    user_id = data.get("decline_user_id")
    city = data.get("decline_city")
    message_id = data.get("message_id")

    if not user_id or not city:
        await send_safe(
            message.chat.id,
            "Ошибка: не найдена информация о платеже для отклонения",
        )
        await state.clear()
        return

    # Get the decline reason
    decline_reason = message.text

    if not decline_reason:
        await send_safe(
            message.chat.id,
            "Пожалуйста, укажите причину отклонения платежа",
        )
        return

    # Update payment status
    await app.update_payment_status(user_id, city, "declined", decline_reason)

    # Get the registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

    if not registration:
        await send_safe(
            message.chat.id,
            f"Регистрация не найдена для пользователя {user_id} в городе {city}",
        )
        await state.clear()
        return

    # Log decline
    admin_username = message.from_user.username if message.from_user else None
    admin_id = message.from_user.id if message.from_user else None

    await app.log_payment_verification(
        user_id,
        registration.get("username", ""),
        registration,
        "declined",
        f"Отклонено администратором {admin_username or admin_id}. Причина: {decline_reason}",
    )

    # Notify user
    await send_safe(
        user_id,
        f"❌ Ваш платеж для участия во встрече в городе {city} отклонен.\n\nПричина: {decline_reason}\n\nПожалуйста, используйте команду /pay для повторной оплаты.",
    )

    # Update the original message if possible
    if message_id:
        from botspot.core.dependency_manager import get_dependency_manager

        deps = get_dependency_manager()
        bot = getattr(deps, "bot", None)
        
        if bot:
            # Get current caption from reply message
            current_caption = ""
            if message.reply_to_message:
                current_caption = getattr(message.reply_to_message, "caption", "") or ""
            
            # Append decline reason to the existing caption
            new_caption = f"{current_caption}\n\n❌ ПЛАТЕЖ ОТКЛОНЕН\nПричина: {decline_reason}"
            
            # Limit caption length to Telegram's maximum
            if len(new_caption) > 1024:
                new_caption = new_caption[-1024:]
            
            try:
                # Update the caption and remove reply markup
                await bot.edit_message_caption(
                    chat_id=message.chat.id,
                    message_id=message_id,
                    caption=new_caption,
                    reply_markup=None,
                )
            except Exception as e:
                logger.error(f"Error editing caption: {e}")
                
                # If editing caption fails, try to remove reply markup
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=message.chat.id, message_id=message_id, reply_markup=None
                    )
                except Exception as e2:
                    logger.error(f"Error removing reply markup: {e2}")

    # Confirm to admin
    await send_safe(
        message.chat.id,
        f"❌ Платеж отклонен для пользователя {registration.get('username', user_id)} ({registration.get('full_name', 'Неизвестно')}).",
    )

    # Clear state
    await state.clear()
