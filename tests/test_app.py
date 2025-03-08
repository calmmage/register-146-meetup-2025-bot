import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.app import App, AppSettings, TargetCity, GraduateType


class TestApp:
    """Tests for the App class"""
    
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
            spreadsheet_id="mock_spreadsheet_id",
            payment_phone_number="1234567890",
            payment_name="Test User"
        )
    
    def teardown_method(self):
        """Clean up after each test"""
        # Stop all patchers
        self.db_patcher.stop()
    
    def test_app_initialization(self):
        """Test the App constructor and settings"""
        # Test that settings were initialized correctly
        assert self.app.settings.telegram_bot_token.get_secret_value() == "mock_token"
        assert self.app.settings.spreadsheet_id == "mock_spreadsheet_id"
        assert self.app.settings.payment_phone_number == "1234567890"
        assert self.app.settings.payment_name == "Test User"
        
        # Test that exporter was initialized
        assert self.app.sheet_exporter is not None
        
        # Test that collection is None by default
        assert self.app._collection is None
    
    def test_collection_property(self):
        """Test the collection property lazy loading"""
        # Before accessing, _collection should be None
        assert self.app._collection is None
        
        # Accessing the property should initialize it
        collection = self.app.collection
        assert collection == self.mock_collection
        
        # The property should now be cached
        assert self.app._collection == self.mock_collection
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_to_chat_logs(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging to the logs chat"""
        # Set logs chat ID
        self.app.settings.logs_chat_id = 123456
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Mock send_safe
        mock_send_safe.return_value = "mock_message"
        
        # Call the method
        result = await self.app.log_to_chat("Test log message", "logs")
        
        # Verify the result
        mock_send_safe.assert_called_once_with(123456, "Test log message")
        assert result == "mock_message"
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_to_chat_events(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging to the events chat"""
        # Set events chat ID
        self.app.settings.events_chat_id = 654321
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Mock send_safe
        mock_send_safe.return_value = "mock_message"
        
        # Call the method
        result = await self.app.log_to_chat("Test event message", "events")
        
        # Verify the result
        mock_send_safe.assert_called_once_with(654321, "Test event message")
        assert result == "mock_message"
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_to_chat_invalid_type(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging with an invalid chat type"""
        # Explicitly set the logs and events chat IDs to None
        self.app.settings.logs_chat_id = None
        self.app.settings.events_chat_id = None
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Call the method with an invalid chat type
        result = await self.app.log_to_chat("Test log message", "invalid_type")
        
        # Verify the result
        mock_send_safe.assert_not_called()
        assert result is None
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_registration_step(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging a registration step"""
        # Set logs chat ID
        self.app.settings.logs_chat_id = 123456
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Mock send_safe
        mock_send_safe.return_value = "mock_message"
        
        # Call the method
        result = await self.app.log_registration_step(
            user_id=98765,
            username="test_user",
            step="Full Name",
            data="Иванов Иван"
        )
        
        # Verify the result
        mock_send_safe.assert_called_once()
        call_args = mock_send_safe.call_args[0]
        assert call_args[0] == 123456
        # Check message contains all the information
        message = call_args[1]
        assert "test_user" in message
        assert "Full Name" in message
        assert "Иванов Иван" in message
        assert result == "mock_message"
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_registration_completed(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging a completed registration"""
        # Set events chat ID
        self.app.settings.events_chat_id = 654321
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Mock send_safe
        mock_send_safe.return_value = "mock_message"
        
        # Call the method
        await self.app.log_registration_completed(
            user_id=98765,
            username="test_user",
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            city=TargetCity.MOSCOW.value,
            graduate_type=GraduateType.GRADUATE.value
        )
        
        # Verify the call
        mock_send_safe.assert_called_once()
        call_args = mock_send_safe.call_args[0]
        assert call_args[0] == 654321
        # Check message contains all the information
        message = call_args[1]
        assert "НОВАЯ РЕГИСТРАЦИЯ" in message
        assert "test_user" in message
        assert "Иванов Иван" in message
        assert "2010 А" in message
        assert "Москва" in message
    
    @pytest.mark.asyncio
    @patch("app.app.send_safe")
    @patch("botspot.core.dependency_manager.get_dependency_manager")
    async def test_log_registration_canceled(self, mock_get_dependency_manager, mock_send_safe):
        """Test logging a canceled registration"""
        # Set events chat ID
        self.app.settings.events_chat_id = 654321
        
        # Mock dependency manager
        mock_deps = MagicMock()
        mock_get_dependency_manager.return_value = mock_deps
        
        # Mock send_safe
        mock_send_safe.return_value = "mock_message"
        
        # Call the method
        await self.app.log_registration_canceled(
            user_id=98765,
            username="test_user",
            full_name="Иванов Иван",
            city=TargetCity.MOSCOW.value
        )
        
        # Verify the call
        mock_send_safe.assert_called_once()
        call_args = mock_send_safe.call_args[0]
        assert call_args[0] == 654321
        # Check message contains all the information
        message = call_args[1]
        assert "ОТМЕНА РЕГИСТРАЦИИ" in message
        assert "test_user" in message
        assert "Иванов Иван" in message
        assert "Москва" in message