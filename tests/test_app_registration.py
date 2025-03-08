import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.app import App, RegisteredUser, TargetCity, GraduateType


class TestAppRegistration:
    """Tests for App registration-related methods"""

    def setup_method(self):
        """Set up test environment before each test"""
        # Create a mock collection
        self.mock_collection = AsyncMock()

        # Mock the get_database().get_collection() chain
        mock_db = MagicMock()
        mock_db.get_collection.return_value = self.mock_collection

        # Create a patcher for get_database
        self.db_patcher = patch("app.app.get_database", return_value=mock_db)
        self.db_patcher.start()

        # Create app instance
        self.app = App(
            telegram_bot_token="mock_token",
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

        # Sample user data
        self.sample_user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.MOSCOW,
            user_id=123456,
            username="ivan_ivanov",
            graduate_type=GraduateType.GRADUATE,
        )

    @pytest.mark.asyncio
    async def test_save_registered_user_new(self):
        """Test saving a new registered user"""
        # Mock find_one to return None (no existing registration)
        self.mock_collection.find_one.return_value = None

        # Call the method
        await self.app.save_registered_user(
            self.sample_user, user_id=self.sample_user.user_id, username=self.sample_user.username
        )

        # Check that insert_one was called
        self.mock_collection.insert_one.assert_called_once()

        # Get the data passed to insert_one
        insert_data = self.mock_collection.insert_one.call_args[0][0]

        # Verify the data is correct
        assert insert_data["full_name"] == "Иванов Иван"
        assert insert_data["graduation_year"] == 2010
        assert insert_data["class_letter"] == "А"
        assert insert_data["target_city"] == TargetCity.MOSCOW.value
        assert insert_data["user_id"] == 123456
        assert insert_data["username"] == "ivan_ivanov"
        assert insert_data["graduate_type"] == GraduateType.GRADUATE.value

    @pytest.mark.asyncio
    async def test_save_registered_user_update(self):
        """Test updating an existing registered user"""
        # Mock find_one to return an existing registration
        existing_user = {
            "_id": "mock_id",
            "full_name": "Иванов Иван",
            "graduation_year": 2010,
            "class_letter": "Б",  # Different class letter
            "target_city": TargetCity.MOSCOW.value,
            "user_id": 123456,
            "username": "ivan_ivanov",
            "graduate_type": GraduateType.GRADUATE.value,
        }
        self.mock_collection.find_one.return_value = existing_user

        # Create updated user with different class letter
        updated_user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",  # Changed from Б to А
            target_city=TargetCity.MOSCOW,
            user_id=123456,
            username="ivan_ivanov",
            graduate_type=GraduateType.GRADUATE,
        )

        # Call the method
        await self.app.save_registered_user(
            updated_user, user_id=updated_user.user_id, username=updated_user.username
        )

        # Check that update_one was called
        self.mock_collection.update_one.assert_called_once()

        # Check the update parameters
        call_args = self.mock_collection.update_one.call_args[0]

        # Verify the filter criteria (should find by _id)
        assert call_args[0] == {"_id": "mock_id"}

        # Verify the update data
        update_data = call_args[1]["$set"]
        assert update_data["class_letter"] == "А"  # Updated class letter

    @pytest.mark.asyncio
    async def test_get_user_registrations(self):
        """Test getting all registrations for a user"""
        # Sample registrations
        sample_registrations = [
            {
                "full_name": "Иванов Иван",
                "graduation_year": 2010,
                "class_letter": "А",
                "target_city": TargetCity.MOSCOW.value,
                "user_id": 123456,
                "username": "ivan_ivanov",
                "graduate_type": GraduateType.GRADUATE.value,
            },
            {
                "full_name": "Иванов Иван",
                "graduation_year": 2010,
                "class_letter": "А",
                "target_city": TargetCity.PERM.value,
                "user_id": 123456,
                "username": "ivan_ivanov",
                "graduate_type": GraduateType.GRADUATE.value,
            },
        ]

        # Mock find to return a cursor that will return our sample registrations
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_registrations)
        self.mock_collection.find = MagicMock(return_value=mock_cursor)

        # Call the method
        registrations = await self.app.get_user_registrations(123456)

        # Verify the find query
        self.mock_collection.find.assert_called_once_with({"user_id": 123456})

        # Verify the results
        assert len(registrations) == 2
        assert registrations[0]["target_city"] == TargetCity.MOSCOW.value
        assert registrations[1]["target_city"] == TargetCity.PERM.value

    @pytest.mark.asyncio
    async def test_get_user_registration_exists(self):
        """Test getting a single registration when user has registrations"""
        # Mock get_user_registrations to return sample registrations
        sample_registrations = [
            {
                "full_name": "Иванов Иван",
                "graduation_year": 2010,
                "class_letter": "А",
                "target_city": TargetCity.MOSCOW.value,
                "user_id": 123456,
                "username": "ivan_ivanov",
                "graduate_type": GraduateType.GRADUATE.value,
            }
        ]

        # Use patch to mock the get_user_registrations method
        with patch.object(
            self.app, "get_user_registrations", AsyncMock(return_value=sample_registrations)
        ):
            # Call the method
            registration = await self.app.get_user_registration(123456)

            # Verify the method was called with correct parameters
            self.app.get_user_registrations.assert_called_once_with(123456)

            # Verify the result
            assert registration is not None
            assert registration["target_city"] == TargetCity.MOSCOW.value

    @pytest.mark.asyncio
    async def test_get_user_registration_not_exists(self):
        """Test getting a single registration when user has no registrations"""
        # Mock get_user_registrations to return empty list
        with patch.object(self.app, "get_user_registrations", AsyncMock(return_value=[])):
            # Call the method
            registration = await self.app.get_user_registration(123456)

            # Verify the method was called with correct parameters
            self.app.get_user_registrations.assert_called_once_with(123456)

            # Verify the result
            assert registration is None

    @pytest.mark.asyncio
    async def test_delete_user_registration_specific_city(self):
        """Test deleting a user's registration for a specific city"""
        # Mock delete_one to return a result with deleted_count=1
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        self.mock_collection.delete_one.return_value = mock_result

        # Call the method
        result = await self.app.delete_user_registration(123456, city=TargetCity.MOSCOW.value)

        # Verify the delete query
        self.mock_collection.delete_one.assert_called_once_with(
            {"user_id": 123456, "target_city": TargetCity.MOSCOW.value}
        )

        # Verify the result
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_user_registration_all_cities(self):
        """Test deleting all of a user's registrations"""
        # Mock delete_many to return a result with deleted_count=2
        mock_result = MagicMock()
        mock_result.deleted_count = 2
        self.mock_collection.delete_many.return_value = mock_result

        # Call the method
        result = await self.app.delete_user_registration(123456)

        # Verify the delete query
        self.mock_collection.delete_many.assert_called_once_with({"user_id": 123456})

        # Verify the result
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_user_registration_none_found(self):
        """Test attempting to delete registrations that don't exist"""
        # Mock delete_many to return a result with deleted_count=0
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        self.mock_collection.delete_many.return_value = mock_result

        # Call the method
        result = await self.app.delete_user_registration(123456)

        # Verify the delete query
        self.mock_collection.delete_many.assert_called_once_with({"user_id": 123456})

        # Verify the result
        assert result is False
