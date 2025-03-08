import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Set required environment variables for all tests"""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("DATABASE_NAME", "test_db")
    monkeypatch.setenv("COLLECTION_NAME", "test_collection")
    monkeypatch.setenv("PAYMENT_PHONE_NUMBER", "test_phone")
    monkeypatch.setenv("PAYMENT_NAME", "Test Receiver")
    monkeypatch.setenv("EVENTS_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "test_sheet_id")
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"type": "service_account", "test": "value"}')


@pytest.fixture(autouse=True)
def mock_botspot_deps():
    """Mock BotSpot dependencies for all tests"""
    with patch("botspot.core.dependency_manager.get_dependency_manager") as mock_deps:
        mock_manager = MagicMock()
        mock_manager.bot = AsyncMock()
        mock_deps.return_value = mock_manager
        yield mock_deps