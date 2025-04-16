import re
from aiogram.types import Message
from datetime import datetime
from enum import Enum
from loguru import logger
from pydantic import SecretStr, BaseModel
from pydantic_settings import BaseSettings
from typing import Optional, Tuple, List, Dict

from botspot import get_database
from botspot.utils import send_safe


class TargetCity(Enum):
    PERM = "Пермь"
    MOSCOW = "Москва"
    SAINT_PETERSBURG = "Санкт-Петербург"
    BELGRADE = "Белград"


class GraduateType(str, Enum):
    GRADUATE = "GRADUATE"
    TEACHER = "TEACHER"
    NON_GRADUATE = "NON_GRADUATE"
    ORGANIZER = "ORGANIZER"


# Mapping for human-readable graduate types
GRADUATE_TYPE_MAP = {
    GraduateType.GRADUATE.value: "Выпускник",
    GraduateType.TEACHER.value: "Учитель",
    GraduateType.NON_GRADUATE.value: "Друг",
    GraduateType.ORGANIZER.value: "Организатор",
}
GRADUATE_TYPE_MAP_PLURAL = {
    GraduateType.GRADUATE.value: "Выпускники",
    GraduateType.TEACHER.value: "Учителя",
    GraduateType.NON_GRADUATE.value: "Друзья",
    GraduateType.ORGANIZER.value: "Организаторы",
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
    events_chat_id: int
    payment_phone_number: str
    payment_name: str

    delay_messages: bool = True

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
    event_logs_collection_name = "event_logs"
    deleted_users_collection_name = "deleted_users"

    def __init__(self, **kwargs):
        from app.export import SheetExporter

        self.settings = AppSettings(**kwargs)
        self.sheet_exporter = SheetExporter(self.settings.spreadsheet_id, app=self)

        self._collection = None
        self._event_logs = None
        self._deleted_users = None

    async def startup(self):
        """
        Run startup tasks like fixing the database and initializing collections
        """
        logger.info("Running app startup tasks...")

        # Initialize collections
        _ = self.collection
        _ = self.event_logs
        _ = self.deleted_users

        # Fix database (SPb, Belgrade, teachers should have 'confirmed' payment status)
        fix_results = await self._fix_database()
        if fix_results["total_fixed"] > 0:
            logger.info(f"Database fix applied to {fix_results['total_fixed']} records:")
            logger.info(f"- SPb: {fix_results['spb_fixed']}")
            logger.info(f"- Belgrade: {fix_results['belgrade_fixed']}")
            logger.info(f"- Teachers: {fix_results['teachers_fixed']}")

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_database().get_collection(self.registration_collection_name)
        return self._collection

    @property
    def event_logs(self):
        if self._event_logs is None:
            self._event_logs = get_database().get_collection(self.event_logs_collection_name)
        return self._event_logs

    @property
    def deleted_users(self):
        if self._deleted_users is None:
            self._deleted_users = get_database().get_collection(self.deleted_users_collection_name)
        return self._deleted_users

    async def save_registered_user(
        self, registered_user: RegisteredUser, user_id: int = None, username: str = None
    ):
        """Save a user registration with optional user_id and username"""
        # Convert the model to a dict and extract the enum value before saving
        data = registered_user.model_dump()
        # Convert the enums to their string values for MongoDB storage
        data["target_city"] = data["target_city"].value
        if "graduate_type" in data and isinstance(data["graduate_type"], GraduateType):
            data["graduate_type"] = data["graduate_type"].value.upper()  # Ensure uppercase

        # Add user_id and username if provided
        if user_id is not None:
            data["user_id"] = user_id
        if username is not None:
            data["username"] = username

        # Copy data for event log (exclude some fields for brevity)
        log_data = {
            "action": "save_registration",
            "full_name": data.get("full_name"),
            "graduation_year": data.get("graduation_year"),
            "class_letter": data.get("class_letter"),
            "target_city": data.get("target_city"),
            "graduate_type": data.get("graduate_type"),
        }

        # Check if user is already registered for this specific city
        is_update = False
        if user_id is not None:
            existing = await self.collection.find_one(
                {"user_id": user_id, "target_city": data["target_city"]}
            )

            if existing:
                # Update existing registration for this city
                await self.collection.update_one({"_id": existing["_id"]}, {"$set": data})
                log_data["action"] = "update_registration"
                log_data["existing_id"] = str(existing["_id"])
                is_update = True

        if not is_update:
            # Insert new record
            result = await self.collection.insert_one(data)
            log_data["new_id"] = str(result.inserted_id)

        # Log the registration action
        await self.save_event_log("user_registration", log_data, user_id, username)

    async def get_user_registrations(self, user_id: int):
        """Get all registrations for a user"""
        cursor = self.collection.find({"user_id": user_id})
        return await cursor.to_list(length=None)

    async def get_user_registration(self, user_id: int):
        """Get existing registration for a user (returns first one found)"""
        registrations = await self.get_user_registrations(user_id)
        return registrations[0] if registrations else None

    async def delete_user_registration(
        self, user_id: int, city: str = None, username: str = None, full_name: str = None
    ):
        """
        Move a user's registration to deleted_users collection instead of permanent deletion

        Args:
            user_id: The user's Telegram ID
            city: Optional city to delete specific registration. If None, deletes all.
            username: Optional user's Telegram username for logging
            full_name: Optional user's full name for logging
        """
        # Log the deletion event
        log_data = {"action": "delete_registration"}
        if city:
            log_data["city"] = city
        if full_name:
            log_data["full_name"] = full_name

        await self.save_event_log("user_deletion", log_data, user_id, username)

        # Move the user to deleted_users collection
        return await self.move_user_to_deleted(user_id, city)

    def validate_full_name(self, full_name: str) -> Tuple[bool, str]:
        """
        Validate a user's full name

        Args:
            full_name: The full name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if full_name is None
        if full_name is None:
            return False, "Отсутствует имя. Пожалуйста, попробуйте ещё раз."

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
        if year < 1995:
            return False, f"Год выпуска должен быть не раньше 1995."

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

    async def export_deleted_users_to_csv(self):
        """Export deleted users to CSV"""
        return await self.sheet_exporter.export_deleted_users_to_csv()

    async def export_feedback_to_sheets(self):
        """Export feedback to Google Sheets"""
        return await self.sheet_exporter.export_feedback_to_sheets()

    async def export_feedback_to_csv(self):
        """Export feedback to CSV"""
        return await self.sheet_exporter.export_feedback_to_csv()

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
        self, user_id: int, username: str | None, step: str, data: str = ""
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
        elif graduate_type == GraduateType.ORGANIZER.value:
            message += f"🛠️ Статус: Организатор\n"
        else:
            message += f"🎓 Выпуск: {graduation_year} {class_letter}\n"

        message += f"🏙️ Город: {city}\n"

        # Add payment status for different participant types
        if graduate_type == GraduateType.TEACHER.value:
            message += f"💰 Оплата: Бесплатно (учитель)\n"
        elif graduate_type == GraduateType.ORGANIZER.value:
            message += f"💰 Оплата: Бесплатно (организатор)\n"
        elif city == TargetCity.SAINT_PETERSBURG.value:
            message += f"💰 Оплата: За свой счет (Санкт-Петербург)\n"
        elif city == TargetCity.BELGRADE.value:
            message += f"💰 Оплата: За свой счет (Белград)\n"

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
        # Teachers and Saint Petersburg/Belgrade attendees are free
        if (
            graduate_type == GraduateType.TEACHER.value
            or city == TargetCity.SAINT_PETERSBURG.value
            or city == TargetCity.BELGRADE.value
        ):
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
        username: str = None,
        payment_status: str = "pending",
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
            username: Optional user's Telegram username for logging
            payment_status: Payment status (pending, confirmed, None for just registered)
        """
        # Update the user's registration with payment info
        update_data = {
            "discounted_payment_amount": discounted_amount,
            "regular_payment_amount": regular_amount,
            "payment_screenshot_id": screenshot_message_id,
            "payment_status": payment_status,
            "payment_timestamp": datetime.now().isoformat(),
        }

        # Add formula amount if provided
        if formula_amount is not None:
            update_data["formula_payment_amount"] = formula_amount

        # Get user registration for logging
        user_data = await self.collection.find_one({"user_id": user_id, "target_city": city})
        full_name = user_data.get("full_name") if user_data else None

        # Log payment info submission
        log_data = {
            "action": "save_payment_info",
            "city": city,
            "discounted_amount": discounted_amount,
            "regular_amount": regular_amount,
            "has_screenshot": screenshot_message_id is not None,
            "full_name": full_name,
        }
        if formula_amount is not None:
            log_data["formula_amount"] = formula_amount

        await self.save_event_log("payment_info", log_data, user_id, username)

        # Update the database
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
        admin_id: int = None,
        admin_username: str = None,
    ):
        """
        Update the payment status for a user

        Args:
            user_id: The user's Telegram ID
            city: The city of the event
            status: The new payment status (confirmed, declined, pending)
            admin_comment: Optional comment from admin
            payment_amount: Amount paid by the user (in rubles)
            admin_id: Optional admin's Telegram ID for logging
            admin_username: Optional admin's Telegram username for logging
        """
        update_data = {"payment_status": status, "payment_verified_at": datetime.now().isoformat()}

        if admin_comment:
            update_data["admin_comment"] = admin_comment

        # Get user registration for logging
        registration = None
        if payment_amount is not None or status:
            registration = await self.collection.find_one({"user_id": user_id, "target_city": city})

        # Prepare log data
        log_data = {
            "action": "update_payment_status",
            "user_id": user_id,
            "city": city,
            "new_status": status,
        }

        if registration:
            log_data["full_name"] = registration.get("full_name")
            log_data["previous_status"] = registration.get("payment_status")

        if admin_comment:
            log_data["admin_comment"] = admin_comment

        if admin_id:
            log_data["admin_id"] = admin_id

        if admin_username:
            log_data["admin_username"] = admin_username

        total_payment = None
        if payment_amount is not None:
            # Add payment amount to log data
            log_data["payment_amount"] = payment_amount

            if registration and "payment_amount" in registration:
                # Add the new payment to the existing amount
                total_payment = registration["payment_amount"] + payment_amount
                update_data["payment_amount"] = total_payment
                log_data["previous_amount"] = registration["payment_amount"]
                log_data["total_after"] = total_payment

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
                total_payment = payment_amount
                update_data["payment_amount"] = payment_amount
                update_data["payment_history"] = [
                    {
                        "amount": payment_amount,
                        "timestamp": datetime.now().isoformat(),
                        "total_after": payment_amount,
                    }
                ]
                log_data["total_after"] = payment_amount

        # Log the payment status update
        await self.save_event_log(
            "payment_status_update", log_data, admin_id or user_id, admin_username
        )

        # Update the database
        await self.collection.update_one(
            {"user_id": user_id, "target_city": city}, {"$set": update_data}
        )

    async def normalize_graduate_types(self, admin_id: int = None, admin_username: str = None):
        """One-time fix to normalize all graduate_type values to uppercase in the database."""
        result = await self.collection.update_many(
            {"graduate_type": {"$exists": True}},
            [{"$set": {"graduate_type": {"$toUpper": "$graduate_type"}}}],
        )

        # Log the normalization operation
        log_data = {"action": "normalize_graduate_types", "modified_count": result.modified_count}

        if admin_id:
            log_data["admin_id"] = admin_id

        if admin_username:
            log_data["admin_username"] = admin_username

        await self.save_event_log("admin_action", log_data, admin_id, admin_username)

        return result.modified_count

    async def _get_users_base(
        self, payment_status: Optional[str] = None, city: Optional[str] = None
    ) -> List[Dict]:
        """
        Base method to get users with various filters

        Args:
            payment_status: Filter by payment status ("confirmed", "pending", "declined", None for any)
            city: Filter by city (None for all cities)

        Returns:
            List of user registrations matching the criteria
        """
        query = {}

        # Build the query conditions
        and_conditions = []

        # Filter by payment status
        if payment_status == "unpaid":
            and_conditions.append({"payment_status": {"$ne": "confirmed"}})
        elif payment_status == "paid":
            and_conditions.append({"payment_status": "confirmed"})

        # Filter by city if specified
        if city and city != "all":
            # Map city key to actual value
            city_mapping = {
                "MOSCOW": TargetCity.MOSCOW.value,
                "PERM": TargetCity.PERM.value,
                "SAINT_PETERSBURG": TargetCity.SAINT_PETERSBURG.value,
                "BELGRADE": TargetCity.BELGRADE.value,
            }
            if city in city_mapping:
                and_conditions.append({"target_city": city_mapping[city]})

        # Add the conditions to the query if we have any
        if and_conditions:
            query["$and"] = and_conditions

        cursor = self.collection.find(query)
        return await cursor.to_list(length=None)

    async def get_unpaid_users(self, city: Optional[str] = None) -> List[Dict]:
        """
        Get all users who have not paid yet (payment_status is not "confirmed")

        Args:
            city: Optional city to filter by

        Returns:
            List of user registrations with unpaid status
        """
        return await self._get_users_base(payment_status="unpaid", city=city)

    async def get_users_without_feedback(self, city: Optional[str] = None) -> List[Dict]:
        """
        Get all users who have not provided feedback yet

        Args:
            city: Optional city to filter by

        Returns:
            List of user registrations without feedback
        """
        all_users = await self._get_users_base(city=city)
        users_without_feedback = []
        
        for user in all_users:
            if not await self.has_provided_feedback(user["user_id"]):
                users_without_feedback.append(user)
                
        return users_without_feedback

    async def get_users_with_feedback(self, city: Optional[str] = None) -> List[Dict]:
        """
        Get all users who have provided feedback

        Args:
            city: Optional city to filter by

        Returns:
            List of user registrations with feedback
        """
        all_users = await self._get_users_base(city=city)
        users_with_feedback = []
        
        for user in all_users:
            if await self.has_provided_feedback(user["user_id"]):
                users_with_feedback.append(user)
                
        return users_with_feedback

    async def get_paid_users(self, city: Optional[str] = None) -> List[Dict]:
        """
        Get all users who have paid (payment_status is "confirmed")

        Args:
            city: Optional city to filter by

        Returns:
            List of user registrations with paid status
        """
        return await self._get_users_base(payment_status="paid", city=city)

    async def get_all_users(self, city: Optional[str] = None) -> List[Dict]:
        """
        Get all users regardless of payment status

        Args:
            city: Optional city to filter by

        Returns:
            List of all user registrations
        """
        return await self._get_users_base(city=city)

    async def _fix_database(self) -> Dict[str, int]:
        """
        Fix the database by setting payment_status to "confirmed" for:
        1. All users in Saint Petersburg (free event)
        2. All users in Belgrade (free event)
        3. All users with graduate_type=TEACHER (free for teachers)
        4. All users with graduate_type=ORGANIZER (free for organizers)

        Returns:
            Dictionary with counts of fixed records for each category
        """
        results = {
            "spb_fixed": 0,
            "belgrade_fixed": 0,
            "teachers_fixed": 0,
            "organizers_fixed": 0,
            "total_fixed": 0,
        }

        # Fix Saint Petersburg registrations
        spb_result = await self.collection.update_many(
            {
                "target_city": TargetCity.SAINT_PETERSBURG.value,
                "payment_status": {"$ne": "confirmed"},
            },
            {"$set": {"payment_status": "confirmed"}},
        )
        results["spb_fixed"] = spb_result.modified_count

        # Fix Belgrade registrations
        belgrade_result = await self.collection.update_many(
            {"target_city": TargetCity.BELGRADE.value, "payment_status": {"$ne": "confirmed"}},
            {"$set": {"payment_status": "confirmed"}},
        )
        results["belgrade_fixed"] = belgrade_result.modified_count

        # Fix teacher registrations
        teachers_result = await self.collection.update_many(
            {"graduate_type": GraduateType.TEACHER.value, "payment_status": {"$ne": "confirmed"}},
            {"$set": {"payment_status": "confirmed"}},
        )
        results["teachers_fixed"] = teachers_result.modified_count

        # Fix organizer registrations
        organizers_result = await self.collection.update_many(
            {"graduate_type": GraduateType.ORGANIZER.value, "payment_status": {"$ne": "confirmed"}},
            {"$set": {"payment_status": "confirmed"}},
        )
        results["organizers_fixed"] = organizers_result.modified_count

        # Calculate total fixed
        results["total_fixed"] = (
            results["spb_fixed"]
            + results["belgrade_fixed"]
            + results["teachers_fixed"]
            + results["organizers_fixed"]
        )

        # Log the fix operation if any records were updated
        if results["total_fixed"] > 0:
            log_data = {
                "action": "fix_database",
                "modified_count": results["total_fixed"],
                "spb_fixed": results["spb_fixed"],
                "belgrade_fixed": results["belgrade_fixed"],
                "teachers_fixed": results["teachers_fixed"],
                "organizers_fixed": results["organizers_fixed"],
            }
            await self.save_event_log("admin_action", log_data)

        return results

    async def save_event_log(
        self,
        event_type: str,
        data: Dict,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> None:
        """
        Save a record to the event logs collection

        Args:
            event_type: Type of the event (e.g., 'registration', 'payment', 'cancellation')
            data: Additional data about the event
            user_id: Optional user's Telegram ID
            username: Optional user's Telegram username
        """
        log_entry = {
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }

        if user_id is not None:
            log_entry["user_id"] = user_id
        if username is not None:
            log_entry["username"] = username

        await self.event_logs.insert_one(log_entry)

    async def save_feedback(
        self,
        user_id: int,
        username: str = None,
        full_name: str = None,
        city: str = None,
        attended: bool = None,
        recommendation_level: str = None,
        venue_rating: str = None,
        food_rating: str = None,
        entertainment_rating: str = None,
        help_interest: str = None,
        comments: str = None,
        feedback_format_preference: str = None,
    ) -> str:
        """
        Save a user's feedback to the database

        Args:
            user_id: User's Telegram ID
            username: User's Telegram username
            full_name: User's full name
            city: City the user attended
            attended: Whether the user attended the event
            recommendation_level: Rating for overall recommendation (1-5)
            venue_rating: Rating for the venue (1-5)
            food_rating: Rating for the food and drinks (1-5)
            entertainment_rating: Rating for entertainment (1-5)
            help_interest: Interest in helping with future events
            comments: Additional comments from the user
            feedback_format_preference: User's preference for feedback format (bot or google_forms)

        Returns:
            ID of the inserted feedback document
        """
        user_info = await self.collection.find_one({"user_id": user_id})

        # Create the feedback document
        feedback = {
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "attended": attended,
        }

        # Add optional fields if provided
        if username:
            feedback["username"] = username

        if full_name:
            feedback["full_name"] = full_name
        elif user_info and "full_name" in user_info:
            feedback["full_name"] = user_info.get("full_name")

        if city:
            feedback["city"] = city

        if recommendation_level:
            feedback["recommendation_level"] = recommendation_level

        if venue_rating:
            feedback["venue_rating"] = venue_rating

        if food_rating:
            feedback["food_rating"] = food_rating

        if entertainment_rating:
            feedback["entertainment_rating"] = entertainment_rating

        if help_interest:
            feedback["help_interest"] = help_interest

        if comments:
            feedback["comments"] = comments

        if feedback_format_preference:
            feedback["feedback_format_preference"] = feedback_format_preference

        # Create or get feedback collection
        if not hasattr(self, "_feedback_collection"):
            self._feedback_collection = get_database().get_collection("feedback")

        # Insert the feedback document
        result = await self._feedback_collection.insert_one(feedback)

        # Also log this event
        await self.save_event_log(
            "feedback_submitted",
            {
                "user_id": user_id,
                "username": username,
                "feedback_id": str(result.inserted_id),
                "attended": attended,
                "city": city,
                "feedback_format_preference": feedback_format_preference,
            },
            user_id,
            username,
        )

        return str(result.inserted_id)

    async def move_user_to_deleted(self, user_id: int, city: Optional[str] = None) -> bool:
        """
        Move a user from registered_users to deleted_users collection

        Args:
            user_id: The user's Telegram ID
            city: Optional city to move specific registration. If None, moves all registrations.

        Returns:
            Boolean indicating whether any records were moved
        """
        # Build query
        query = {"user_id": user_id}
        if city:
            query["target_city"] = city

        # Find records to move
        cursor = self.collection.find(query)
        records = await cursor.to_list(length=None)

        if not records:
            logger.warning(f"No records found to move for user_id={user_id}, city={city}")
            return False

        # Add deletion timestamp to each record
        now = datetime.now().isoformat()
        for record in records:
            record["deletion_timestamp"] = now

        # Insert into deleted_users collection
        if len(records) == 1:
            await self.deleted_users.insert_one(records[0])
            logger.info(f"Moved 1 record to deleted_users: user_id={user_id}, city={city}")
        else:
            await self.deleted_users.insert_many(records)
            logger.info(f"Moved {len(records)} records to deleted_users: user_id={user_id}")

        # Now that records are backed up, delete from main collection
        if city:
            result = await self.collection.delete_one(query)
        else:
            result = await self.collection.delete_many(query)

        return result.deleted_count > 0

    async def has_provided_feedback(self, user_id: int) -> bool:
        """
        Check if a user has already provided feedback

        Args:
            user_id: The user's Telegram ID

        Returns:
            True if user has provided feedback, False otherwise
        """
        if not hasattr(self, "_feedback_collection"):
            self._feedback_collection = get_database().get_collection("feedback")
            
        feedback = await self._feedback_collection.find_one({"user_id": user_id})
        return feedback is not None
