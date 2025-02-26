from pydantic import SecretStr, BaseModel
from pydantic_settings import BaseSettings

from botspot import get_database

from enum import Enum


class TargetCity(Enum):
    PERM = "Пермь"
    MOSCOW = "Москва"
    SAINT_PETERSBURG = "Санкт-Петербург"


class AppConfig(BaseSettings):
    """Basic app configuration"""

    telegram_bot_token: SecretStr

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


class RegisteredUser(BaseModel):
    full_name: str
    graduation_year: int
    class_letter: str
    target_city: TargetCity


class App:
    name = "Mini Botspot Template"

    registration_collection_name = "registered_users"

    def __init__(self, **kwargs):
        self.config = AppConfig(**kwargs)

        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_database().get_collection(self.registration_collection_name)
        return self._collection

    async def save_registered_user(self, registered_user: RegisteredUser):
        # Convert the model to a dict and extract the enum value before saving
        data = registered_user.model_dump()
        # Convert the enum to its string value for MongoDB storage
        data["target_city"] = data["target_city"].value
        await self.collection.insert_one(data)

    # def validate_graduation_year(self):

    def parse_graduation_year_and_class_letter(self, year_and_class: str) -> tuple[int, str]:
        year_and_class = year_and_class.strip()

        # Case 0: the class letter is not specified
        if year_and_class.isdigit():
            return int(year_and_class), ""

        # Case 1 - "2025 Б"
        parts = year_and_class.split()
        if len(parts) == 2:
            return int(parts[0]), parts[1].upper()

        # Case 2 - "2025Б"
        if len(year_and_class) > 4 and year_and_class[0:4].isdigit():
            return int(year_and_class[0:4]), year_and_class[4:].upper()

        # Case 4: fallback to simple split
        year, class_letter = year_and_class.split(maxsplit=1)
        return int(year), class_letter.upper()
