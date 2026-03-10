import pytest
from pydantic import ValidationError

from app.app import RegisteredUser, GraduateType


class TestRegisteredUser:
    """Tests for the RegisteredUser model"""

    def test_registered_user_create(self):
        """Test creating a RegisteredUser instance"""
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city="Москва",
            event_id="aabbccddeeff00112233aabb",
        )

        assert user.full_name == "Иванов Иван"
        assert user.graduation_year == 2010
        assert user.class_letter == "А"
        assert user.target_city == "Москва"

        assert user.user_id is None
        assert user.username is None
        assert user.graduate_type == GraduateType.GRADUATE

    def test_registered_user_with_all_fields(self):
        """Test creating a RegisteredUser with all fields"""
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city="Москва",
            event_id="aabbccddeeff00112233aabb",
            user_id=123456,
            username="ivan_ivanov",
            graduate_type=GraduateType.TEACHER,
        )

        assert user.full_name == "Иванов Иван"
        assert user.graduation_year == 2010
        assert user.class_letter == "А"
        assert user.target_city == "Москва"
        assert user.user_id == 123456
        assert user.username == "ivan_ivanov"
        assert user.graduate_type == GraduateType.TEACHER

    def test_registered_user_model_dump(self):
        """Test model_dump method for serialization"""
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city="Москва",
            event_id="aabbccddeeff00112233aabb",
            user_id=123456,
            username="ivan_ivanov",
        )

        data = user.model_dump()

        assert isinstance(data, dict)
        assert data["full_name"] == "Иванов Иван"
        assert data["graduation_year"] == 2010
        assert data["class_letter"] == "А"
        assert data["target_city"] == "Москва"
        assert data["user_id"] == 123456
        assert data["username"] == "ivan_ivanov"
        assert data["graduate_type"] == GraduateType.GRADUATE

    def test_registered_user_validation(self):
        """Test validation rules"""
        with pytest.raises(ValidationError):
            RegisteredUser(
                full_name="Иванов Иван",
                class_letter="А",
                target_city="Москва",
            )

        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=1500,
            class_letter="А",
            target_city="Москва",
            event_id="aabbccddeeff00112233aabb",
        )
        assert user.graduation_year == 1500

    def test_target_city_is_string(self):
        """Test that target_city accepts plain strings"""
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city="Москва",
            event_id="aabbccddeeff00112233aabb",
        )
        assert user.target_city == "Москва"
        assert isinstance(user.target_city, str)

    def test_graduate_type_enum(self):
        """Test the GraduateType enum values"""
        assert GraduateType.GRADUATE.value == "GRADUATE"
        assert GraduateType.TEACHER.value == "TEACHER"
        assert GraduateType.NON_GRADUATE.value == "NON_GRADUATE"
