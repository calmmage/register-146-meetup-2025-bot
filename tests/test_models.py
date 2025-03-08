import pytest
from pydantic import ValidationError

from app.app import RegisteredUser, TargetCity, GraduateType


class TestRegisteredUser:
    """Tests for the RegisteredUser model"""
    
    def test_registered_user_create(self):
        """Test creating a RegisteredUser instance"""
        # Create a minimal user
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.MOSCOW
        )
        
        # Verify required fields
        assert user.full_name == "Иванов Иван"
        assert user.graduation_year == 2010
        assert user.class_letter == "А"
        assert user.target_city == TargetCity.MOSCOW
        
        # Verify default values
        assert user.user_id is None
        assert user.username is None
        assert user.graduate_type == GraduateType.GRADUATE
    
    def test_registered_user_with_all_fields(self):
        """Test creating a RegisteredUser with all fields"""
        # Create a complete user
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.MOSCOW,
            user_id=123456,
            username="ivan_ivanov",
            graduate_type=GraduateType.TEACHER
        )
        
        # Verify all fields
        assert user.full_name == "Иванов Иван"
        assert user.graduation_year == 2010
        assert user.class_letter == "А"
        assert user.target_city == TargetCity.MOSCOW
        assert user.user_id == 123456
        assert user.username == "ivan_ivanov"
        assert user.graduate_type == GraduateType.TEACHER
    
    def test_registered_user_model_dump(self):
        """Test model_dump method for serialization"""
        # Create a user
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.MOSCOW,
            user_id=123456,
            username="ivan_ivanov"
        )
        
        # Convert to dict
        data = user.model_dump()
        
        # Verify the dict contains the correct data
        assert isinstance(data, dict)
        assert data["full_name"] == "Иванов Иван"
        assert data["graduation_year"] == 2010
        assert data["class_letter"] == "А"
        assert data["target_city"] == TargetCity.MOSCOW
        assert data["user_id"] == 123456
        assert data["username"] == "ivan_ivanov"
        assert data["graduate_type"] == GraduateType.GRADUATE
    
    def test_registered_user_validation(self):
        """Test validation rules"""
        # Test missing required fields
        with pytest.raises(ValidationError):
            RegisteredUser(
                full_name="Иванов Иван",
                # Missing graduation_year
                class_letter="А",
                target_city=TargetCity.MOSCOW
            )
        
        # Test the model accepts any integer for graduation_year 
        # (additional validation is in the App.validate_graduation_year method)
        user = RegisteredUser(
            full_name="Иванов Иван", 
            graduation_year=1500,  # Very early year (valid for model, invalid in App validation)
            class_letter="А",
            target_city=TargetCity.MOSCOW
        )
        assert user.graduation_year == 1500
    
    def test_target_city_enum(self):
        """Test the TargetCity enum values"""
        # Check enum values
        assert TargetCity.PERM.value == "Пермь"
        assert TargetCity.MOSCOW.value == "Москва"
        assert TargetCity.SAINT_PETERSBURG.value == "Санкт-Петербург"
    
    def test_graduate_type_enum(self):
        """Test the GraduateType enum values"""
        # Check enum values
        assert GraduateType.GRADUATE.value == "GRADUATE"
        assert GraduateType.TEACHER.value == "TEACHER"
        assert GraduateType.NON_GRADUATE.value == "NON_GRADUATE"