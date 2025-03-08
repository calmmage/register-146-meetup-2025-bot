import pytest

from app.app import AppSettings


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("PAYMENT_PHONE_NUMBER", "test_number")
    monkeypatch.setenv("PAYMENT_NAME", "test_name")


class TestSimplifiedSettings:
    """Simplified tests for AppSettings class"""

    def test_app_settings_from_args(self):
        """Test creating settings from constructor arguments"""
        # Create settings from arguments
        settings = AppSettings(
            telegram_bot_token="mock_token",
            spreadsheet_id="mock_spreadsheet_id",
            logs_chat_id=123456,
            events_chat_id=654321,
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

        # Verify values
        assert settings.telegram_bot_token.get_secret_value() == "mock_token"
        assert settings.spreadsheet_id == "mock_spreadsheet_id"
        assert settings.logs_chat_id == 123456
        assert settings.events_chat_id == 654321
        assert settings.payment_phone_number == "1234567890"
        assert settings.payment_name == "Test User"
