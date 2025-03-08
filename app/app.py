import re
from aiogram.types import Message
from datetime import datetime
from enum import Enum
from loguru import logger
from pydantic import SecretStr, BaseModel
from pydantic_settings import BaseSettings
from typing import Optional, Tuple

from botspot import get_database
from botspot.utils import send_safe


class TargetCity(Enum):
    PERM = "Пермь"
    MOSCOW = "Москва"
    SAINT_PETERSBURG = "Санкт-Петербург"


class GraduateType(str, Enum):
    GRADUATE = "GRADUATE"
    TEACHER = "TEACHER"
    NON_GRADUATE = "NON_GRADUATE"


# Mapping for human-readable graduate types
GRADUATE_TYPE_MAP = {
    GraduateType.GRADUATE.value: "Выпускник",
    GraduateType.TEACHER.value: "Учитель",
    GraduateType.NON_GRADUATE.value: "Не выпускник",
}

# Mapping for payment statuses
PAYMENT_STATUS_MAP = {
    "confirmed": "Оплачено",
    "pending": "Оплачу позже",
    "declined": "Отклонено",
    None: "Не оплачено",
    "Не оплачено": "Не оплачено",  # For backward compatibility with existing data
}


class AppSettings(BaseSettings):
    """Basic app configuration"""

    telegram_bot_token: SecretStr
    spreadsheet_id: Optional[str] = None
    logs_chat_id: Optional[int] = None
    events_chat_id: Optional[int] = None
    payment_phone_number: str
    payment_name: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


class RegisteredUser(BaseModel):
    full_name: str
    graduation_year: int
    class_letter: str
    target_city: TargetCity
    user_id: Optional[int] = None
    username: Optional[str] = None
    graduate_type: GraduateType = GraduateType.GRADUATE


class App:
    name = "146 Meetup Register Bot"

    registration_collection_name = "registered_users"

    def __init__(self, **kwargs):
        from app.export import SheetExporter

        self.settings = AppSettings(**kwargs)
        self.sheet_exporter = SheetExporter(self.settings.spreadsheet_id, app=self)

        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_database().get_collection(self.registration_collection_name)
        return self._collection

    async def save_registered_user(
        self, registered_user: RegisteredUser, user_id: int = None, username: str = None
    ):
        """Save a user registration with optional user_id and username"""
        # Convert the model to a dict and extract the enum value before saving
        data = registered_user.model_dump()
        # Convert the enums to their string values for MongoDB storage
        data["target_city"] = data["target_city"].value
        if "graduate_type" in data and isinstance(data["graduate_type"], GraduateType):
            data["graduate_type"] = data["graduate_type"].value

        # Add user_id and username if provided
        if user_id is not None:
            data["user_id"] = user_id
        if username is not None:
            data["username"] = username

        # Check if user is already registered for this specific city
        if user_id is not None:
            existing = await self.collection.find_one(
                {"user_id": user_id, "target_city": data["target_city"]}
            )

            if existing:
                # Update existing registration for this city
                await self.collection.update_one({"_id": existing["_id"]}, {"$set": data})
                return

        # Insert new record
        await self.collection.insert_one(data)

    async def get_user_registrations(self, user_id: int):
        """Get all registrations for a user"""
        cursor = self.collection.find({"user_id": user_id})
        return await cursor.to_list(length=None)

    async def get_user_registration(self, user_id: int):
        """Get existing registration for a user (returns first one found)"""
        registrations = await self.get_user_registrations(user_id)
        return registrations[0] if registrations else None

    async def delete_user_registration(self, user_id: int, city: str = None):
        """
        Delete a user's registration

        Args:
            user_id: The user's Telegram ID
            city: Optional city to delete specific registration. If None, deletes all.
        """
        if city:
            result = await self.collection.delete_one({"user_id": user_id, "target_city": city})
        else:
            result = await self.collection.delete_many({"user_id": user_id})

        return result.deleted_count > 0

    def validate_full_name(self, full_name: str) -> Tuple[bool, str]:
        """
        Validate a user's full name

        Args:
            full_name: The full name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if name has at least 2 words
        words = full_name.strip().split()
        if len(words) < 2:
            return False, "Пожалуйста, укажите хотя бы имя и фамилию :)"

        # Check if name contains only Russian letters, spaces, and hyphens
        if not re.match(r"^[а-яА-ЯёЁ\s\-]+$", full_name):
            return False, "По-русски, пожалуйста :)"

        return True, ""

    def validate_graduation_year(self, year: int) -> Tuple[bool, str]:
        """
        Validate a graduation year

        Args:
            year: The graduation year to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        current_year = datetime.now().year

        # Check if year is in valid range
        if year < 1996:
            return False, f"Год выпуска должен быть не раньше 1996."

        if year >= current_year:
            if year <= current_year + 4:
                return (
                    False,
                    f"Извините, регистрация только для выпускников. Приходите после выпуска!",
                )
            else:
                return False, f"Год выпуска не может быть позже {current_year + 4}."

        return True, ""

    def validate_class_letter(self, letter: str) -> Tuple[bool, str]:
        """
        Validate a class letter

        Args:
            letter: The class letter to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not letter:
            return False, "Пожалуйста, укажите букву класса."

        # Check if letter contains only Russian letters
        if not re.match(r"^[а-яА-ЯёЁ]+$", letter):
            return False, "Буква класса должна быть на русском языке."

        # Check if letter is only one character
        if len(letter) > 1:
            return False, "Буква класса должна быть только одним символом."

        return True, ""

    def parse_graduation_year_and_class_letter(
        self, year_and_class: str
    ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """
        Parse graduation year and class letter from user input

        Args:
            year_and_class: The user input to parse

        Returns:
            Tuple of (year, class_letter, error_message)
        """
        year_and_class = year_and_class.strip()

        # Case 0: the class letter is not specified
        if year_and_class.isdigit():
            year = int(year_and_class)
            valid, error = self.validate_graduation_year(year)
            if not valid:
                return None, None, error
            return year, "", "Пожалуйста, укажите также букву класса."

        try:
            # Case 1 - "2025 Б"
            parts = year_and_class.split()
            if len(parts) == 2:
                year = int(parts[0])
                letter = parts[1].upper()
            # Case 2 - "2025Б"
            elif len(year_and_class) > 4 and year_and_class[0:4].isdigit():
                year = int(year_and_class[0:4])
                letter = year_and_class[4:].upper()
            # Case 3: fallback to simple split
            else:
                year, letter = year_and_class.split(maxsplit=1)
                year = int(year)
                letter = letter.upper()

            # Validate year
            valid_year, error_year = self.validate_graduation_year(year)
            if not valid_year:
                return None, None, error_year

            # Validate letter
            valid_letter, error_letter = self.validate_class_letter(letter)
            if not valid_letter:
                return None, None, error_letter

            return year, letter, None

        except (ValueError, IndexError):
            return (
                None,
                None,
                "Неверный формат. Пожалуйста, введите год выпуска и букву класса (например, '2003 Б').",
            )

    def export_registered_users_to_google_sheets(self):
        return self.sheet_exporter.export_registered_users()

    async def export_to_csv(self):
        """Export registered users to CSV"""
        return await self.sheet_exporter.export_to_csv()

    async def log_to_chat(self, message: str, chat_type: str = "logs") -> Optional[Message]:
        """
        Log a message to the specified chat

        Args:
            message: The message to log
            chat_type: Either "logs" or "events"

        Returns:
            The sent message object or None if chat ID is not configured
        """
        chat_id = None
        if chat_type == "logs" and self.settings.logs_chat_id:
            chat_id = self.settings.logs_chat_id
        elif chat_type == "events" and self.settings.events_chat_id:
            chat_id = self.settings.events_chat_id

        if not chat_id:
            return None

        try:
            from botspot.core.dependency_manager import get_dependency_manager

            deps = get_dependency_manager()

            return await send_safe(chat_id, message)
        except Exception as e:
            logger.error(f"Failed to log to {chat_type} chat: {e}")
            return None

    async def log_registration_step(
        self, user_id: int, username: str, step: str, data: str = ""
    ) -> Optional[Message]:
        """
        Log a registration step to the logs chat

        Args:
            user_id: User's Telegram ID
            username: User's Telegram username
            step: The registration step being performed
            data: Additional data about the step

        Returns:
            The sent message object or None if logs chat ID is not configured
        """
        message = f"👤 Пользователь: {username or user_id}\n"
        message += f"🔄 Шаг: {step}\n"

        if data:
            message += f"📝 Данные: {data}"

        return await self.log_to_chat(message, "logs")

    async def log_registration_completed(
        self,
        user_id: int,
        username: str,
        full_name: str,
        graduation_year: int,
        class_letter: str,
        city: str,
        graduate_type: str = GraduateType.GRADUATE.value,
    ) -> None:
        """
        Log a completed registration to the events chat

        Args:
            user_id: User's Telegram ID
            username: User's Telegram username
            full_name: User's full name
            graduation_year: User's graduation year
            class_letter: User's class letter
            city: The city of the event
            graduate_type: Type of participant (graduate, teacher, non_graduate)
        """
        message = f"✅ НОВАЯ РЕГИСТРАЦИЯ\n\n"
        message += f"👤 Пользователь: {username or user_id}\n"
        message += f"📋 ФИО: {full_name}\n"

        # Format graduation info based on graduate type
        if graduate_type == GraduateType.TEACHER.value:
            message += f"👨‍🏫 Статус: Учитель\n"
        elif graduate_type == GraduateType.NON_GRADUATE.value:
            message += f"👥 Статус: Не выпускник\n"
        else:
            message += f"🎓 Выпуск: {graduation_year} {class_letter}\n"

        message += f"🏙️ Город: {city}\n"

        # Add payment status for different participant types
        if graduate_type == GraduateType.TEACHER.value:
            message += f"💰 Оплата: Бесплатно (учитель)\n"
        elif city == TargetCity.SAINT_PETERSBURG.value:
            message += f"💰 Оплата: За свой счет (Санкт-Петербург)\n"

        await self.log_to_chat(message, "events")

    async def log_registration_canceled(
        self,
        user_id: int,
        username: str,
        full_name: str,
        city: str,
    ) -> None:
        """
        Log a canceled registration to the events chat

        Args:
            user_id: User's Telegram ID
            username: User's Telegram username
            city: The city of the canceled registration (or None if all)
        """
        message = f"❌ ОТМЕНА РЕГИСТРАЦИИ\n\n"
        message += f"👤 Пользователь: {username or user_id}\n"
        message += f"📋 ФИО: {full_name}\n"

        if city:
            message += f"🏙️ Город: {city}\n"
        else:
            message += "🏙️ Все города\n"

        await self.log_to_chat(message, "events")

    def calculate_payment_amount(
        self, city: str, graduation_year: int, graduate_type: str = GraduateType.GRADUATE.value
    ) -> tuple[int, int, int, int]:
        """
        Calculate the payment amount based on city, graduation year, and graduate type

        Args:
            city: The city of the event
            graduation_year: The user's graduation year
            graduate_type: The type of participant (graduate, teacher, non_graduate)

        Returns:
            Tuple of (regular_amount, discount, discounted_amount)
        """
        # Teachers and Saint Petersburg attendees are free
        if graduate_type == GraduateType.TEACHER.value or city == TargetCity.SAINT_PETERSBURG.value:
            return 0, 0, 0, 0

        # For non-graduates, use fixed recommended amounts
        if graduate_type == GraduateType.NON_GRADUATE.value:
            if city == TargetCity.MOSCOW.value:
                return 4000, 1000, 3000, 4000
            elif city == TargetCity.PERM.value:
                return 2000, 500, 1500, 2000
            else:
                return 0, 0, 0, 0

        # Regular payment calculation for graduates
        current_year = 2025
        years_since_graduation = max(0, current_year - graduation_year)

        formula_amount = 0
        if city == TargetCity.MOSCOW.value:
            formula_amount = 1000 + (200 * years_since_graduation)
        elif city == TargetCity.PERM.value:
            formula_amount = 500 + (100 * years_since_graduation)

        regular_amount = 0
        if years_since_graduation <= 15:
            regular_amount = formula_amount
        else:
            if city == TargetCity.MOSCOW.value:
                regular_amount = 4000
            elif city == TargetCity.PERM.value:
                regular_amount = 2000

        # Early registration discount
        discount = 0
        # if early_registration:
        if city == TargetCity.MOSCOW.value:
            discount = 1000
        elif city == TargetCity.PERM.value:
            discount = 500

        # Final amount after discount
        discounted_amount = max(0, regular_amount - discount)

        return regular_amount, discount, discounted_amount, formula_amount

    async def save_payment_info(
        self,
        user_id: int,
        city: str,
        discounted_amount: int,
        regular_amount: int,
        screenshot_message_id: int = None,
        formula_amount: int = None,
    ):
        """
        Save payment information for a user

        Args:
            user_id: The user's Telegram ID
            city: The city of the event
            discounted_amount: The payment amount with early discount
            regular_amount: The regular payment amount without discount
            screenshot_message_id: ID of the message containing the payment screenshot
            formula_amount: The payment amount calculated by formula
        """
        # Update the user's registration with payment info
        update_data = {
            "discounted_payment_amount": discounted_amount,
            "regular_payment_amount": regular_amount,
            "payment_screenshot_id": screenshot_message_id,
            "payment_status": "pending",
            "payment_timestamp": datetime.now().isoformat(),
        }

        # Add formula amount if provided
        if formula_amount is not None:
            update_data["formula_payment_amount"] = formula_amount

        await self.collection.update_one(
            {"user_id": user_id, "target_city": city},
            {"$set": update_data},
        )

    async def update_payment_status(
        self,
        user_id: int,
        city: str,
        status: str,
        admin_comment: str = None,
        payment_amount: int = None,
    ):
        """
        Update the payment status for a user

        Args:
            user_id: The user's Telegram ID
            city: The city of the event
            status: The new payment status (confirmed, declined, pending)
            admin_comment: Optional comment from admin
            payment_amount: Amount paid by the user (in rubles)
        """
        update_data = {"payment_status": status, "payment_verified_at": datetime.now().isoformat()}

        if admin_comment:
            update_data["admin_comment"] = admin_comment

        if payment_amount is not None:
            # Get current registration to check for existing payment
            registration = await self.collection.find_one({"user_id": user_id, "target_city": city})

            if registration and "payment_amount" in registration:
                # Add the new payment to the existing amount
                total_payment = registration["payment_amount"] + payment_amount
                update_data["payment_amount"] = total_payment

                # Store payment history as an array of individual payments
                payment_history = registration.get("payment_history", [])
                payment_history.append(
                    {
                        "amount": payment_amount,
                        "timestamp": datetime.now().isoformat(),
                        "total_after": total_payment,
                    }
                )
                update_data["payment_history"] = payment_history
            else:
                # First payment
                update_data["payment_amount"] = payment_amount
                update_data["payment_history"] = [
                    {
                        "amount": payment_amount,
                        "timestamp": datetime.now().isoformat(),
                        "total_after": payment_amount,
                    }
                ]

        await self.collection.update_one(
            {"user_id": user_id, "target_city": city}, {"$set": update_data}
        )
