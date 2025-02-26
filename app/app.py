from enum import Enum
from pydantic import SecretStr, BaseModel
from pydantic_settings import BaseSettings
from typing import Optional, Tuple
from aiogram.types import Message
from loguru import logger
import re
import datetime


from botspot import get_database
from botspot.utils import send_safe


class TargetCity(Enum):
    PERM = "Пермь"
    MOSCOW = "Москва"
    SAINT_PETERSBURG = "Санкт-Петербург"


class AppConfig(BaseSettings):
    """Basic app configuration"""

    telegram_bot_token: SecretStr
    spreadsheet_id: Optional[str] = None
    logs_chat_id: Optional[int] = None
    events_chat_id: Optional[int] = None

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


class App:
    name = "Mini Botspot Template"

    registration_collection_name = "registered_users"

    def __init__(self, **kwargs):
        from app.export import SheetExporter

        self.config = AppConfig(**kwargs)
        self.sheet_exporter = SheetExporter(self.config.spreadsheet_id, app=self)

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
        # Convert the enum to its string value for MongoDB storage
        data["target_city"] = data["target_city"].value

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
            return False, "ФИО должно содержать как минимум имя и фамилию."
        
        # Check if name contains only Russian letters, spaces, and hyphens
        if not re.match(r'^[а-яА-ЯёЁ\s\-]+$', full_name):
            return False, "ФИО должно содержать только русские буквы."
        
        return True, ""
    
    def validate_graduation_year(self, year: int) -> Tuple[bool, str]:
        """
        Validate a graduation year
        
        Args:
            year: The graduation year to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        current_year = datetime.datetime.now().year
        
        # Check if year is in valid range
        if year < 1996:
            return False, f"Год выпуска должен быть не раньше 1996."
        
        if year > current_year:
            if year <= current_year + 4:
                return False, f"Извините, регистрация только для выпускников. Приходите после выпуска!"
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
        if not re.match(r'^[а-яА-ЯёЁ]+$', letter):
            return False, "Буква класса должна быть на русском языке."
        
        return True, ""
    
    def parse_graduation_year_and_class_letter(self, year_and_class: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
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
            return None, None, "Неверный формат. Пожалуйста, введите год выпуска и букву класса (например, '2025 Б')."

    def export_registered_users(self):
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
        if chat_type == "logs" and self.config.logs_chat_id:
            chat_id = self.config.logs_chat_id
        elif chat_type == "events" and self.config.events_chat_id:
            chat_id = self.config.events_chat_id

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

    async def log_registration_complete(
        self, user_id: int, username: str, registration: dict
    ) -> None:
        """
        Log a completed registration to the events chat

        Args:
            user_id: User's Telegram ID
            username: User's Telegram username
            registration: The registration data
        """
        city = registration["target_city"]

        message = f"✅ НОВАЯ РЕГИСТРАЦИЯ\n\n"
        message += f"👤 Пользователь: {username or user_id}\n"
        message += f"📋 ФИО: {registration['full_name']}\n"
        message += f"🎓 Выпуск: {registration['graduation_year']} {registration['class_letter']}\n"
        message += f"🏙️ Город: {city}\n"

        await self.log_to_chat(message, "events")

    async def log_registration_canceled(
        self, user_id: int, username: str, city: str = None
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

        if city:
            message += f"🏙️ Город: {city}\n"
        else:
            message += "🏙️ Все города\n"

        await self.log_to_chat(message, "events")
