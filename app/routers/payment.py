"""Payment router for the 146 Meetup Register Bot."""

import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from botspot.user_interactions import ask_user_raw, ask_user_choice
from botspot.utils import send_safe
from loguru import logger
from textwrap import dedent

from app.app import App, TargetCity
from app.router import is_admin, date_of_event, commands_menu

# Create router
router = Router()
app = App()


async def process_payment(message: Message, state: FSMContext, city: str, graduation_year: int):
    """Process payment for an event registration"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return
        
    user_id = message.from_user.id
    username = message.from_user.username

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
    # early_registration_date = datetime.strptime("2025-03-15", "%Y-%m-%d")
    early_registration_date = "2025-03-15"
    # today = datetime.now()
    # early_registration = today < early_registration_date

    # Calculate payment amount
    regular_amount, discount, discounted_amount = app.calculate_payment_amount(
        city, graduation_year  # , early_registration
    )

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
    await asyncio.sleep(10)

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
    await asyncio.sleep(5)

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
    await asyncio.sleep(10)

    # Ask for payment confirmation
    response = await ask_user_raw(
        message.chat.id,
        "Пожалуйста, отправьте скриншот подтверждения оплаты или нажмите кнопку ниже, если хотите оплатить позже.",
        state=state,
        timeout=1200,
    )

    if response == "Оплачу позже":
        await send_safe(
            message.chat.id,
            "Хорошо! Вы можете оплатить позже, используя команду /pay",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if response is None:
        # No response received
        await send_safe(
            message.chat.id,
            "⏰ Не получен ответ в течение 20 минут. Пожалуйста, используйте команду /pay для оплаты.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if response and hasattr(response, 'photo') and response.photo:
        # Save payment info with pending status
        await app.save_payment_info(user_id, city, discounted_amount, regular_amount, response.message_id)
        
        # Forward screenshot to events chat (which is used as validation chat)
        try:
            # Get events chat ID from settings
            events_chat_id = app.settings.events_chat_id
            
            if events_chat_id:
                # Get user info for the message
                user_info = f"👤 Пользователь: {username or 'Неизвестно'} (ID: {user_id})\n"
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
                    
                    # First send user info
                    info_msg = await bot.send_message(events_chat_id, user_info)
                    
                    # Then forward the screenshot
                    forwarded_msg = await bot.forward_message(
                        chat_id=events_chat_id,
                        from_chat_id=message.chat.id,
                        message_id=response.message_id
                    )
                    
                    # Add validation instructions
                    await bot.send_message(
                        events_chat_id,
                        "Для валидации платежа, ответьте на скриншот командой:\n"
                        "/validate <сумма> - для подтверждения платежа\n"
                        "/decline <причина> - для отклонения платежа",
                        reply_to_message_id=forwarded_msg.message_id
                    )
                    
                    logger.info(f"Payment screenshot from user {user_id} forwarded to validation chat")
                else:
                    logger.error("Bot not available in dependency manager, cannot forward screenshot")
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
        # Process payment for the selected registration
        await process_payment(
            message, state, selected_reg["target_city"], selected_reg["graduation_year"]
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
    if len(command_parts) < 2:
        await send_safe(
            message.chat.id,
            "Пожалуйста, укажите сумму платежа: /validate <сумма>",
        )
        return
    
    try:
        payment_amount = int(command_parts[1])
    except ValueError:
        await send_safe(
            message.chat.id,
            "Некорректная сумма платежа. Пожалуйста, укажите число.",
        )
        return
    
    # Find the original message with user info
    # We need to find the message that contains the user ID
    # This is typically sent before the screenshot
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
                for line in info_message.text.split('\n'):
                    if "ID:" in line:
                        try:
                            user_id = int(line.split("ID:")[1].strip().rstrip(')'))
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
                "Пожалуйста, используйте формат: /validate <сумма> <user_id> <город>",
            )
            
            # Check if admin provided user_id and city in the command
            if len(command_parts) >= 4:
                try:
                    user_id = int(command_parts[2])
                    city = command_parts[3]
                except (ValueError, IndexError):
                    return
            else:
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
            f"Подтверждено администратором {admin_username or admin_id}. Сумма: {payment_amount} руб."
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
                for line in info_message.text.split('\n'):
                    if "ID:" in line:
                        try:
                            user_id = int(line.split("ID:")[1].strip().rstrip(')'))
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
            f"Отклонено администратором {admin_username or admin_id}. Причина: {reason}"
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