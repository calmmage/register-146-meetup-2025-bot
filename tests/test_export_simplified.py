import base64
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.app import App
from app.export import SheetExporter


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("PAYMENT_PHONE_NUMBER", "test_number")
    monkeypatch.setenv("PAYMENT_NAME", "test_name")


class TestSheetExporterSimplified:
    """Simplified tests for the SheetExporter class"""

    def setup_method(self):
        """Set up test environment before each test"""
        # Create a mock collection
        self.mock_collection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_collection.find = MagicMock(return_value=mock_cursor)

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
            payment_name="Test User",
        )

        # Create exporter with the mocked app
        self.exporter = SheetExporter("mock_spreadsheet_id", app=self.app)

    def teardown_method(self):
        """Clean up after each test"""
        # Stop all patchers
        self.db_patcher.stop()

    @pytest.mark.asyncio
    @patch("app.export.logger")
    async def test_export_to_csv_empty(self, mock_logger):
        """Test export_to_csv with empty result"""
        # No setup needed - our collection is already mocked to return empty list

        # Call the method
        csv_content, message = await self.exporter.export_to_csv()

        # Verify the message
        assert message == "Нет пользователей для экспорта"
        assert csv_content is None
        mock_logger.info.assert_called_once_with("Нет пользователей для экспорта")

    @patch("app.export.gspread.authorize")
    @patch("app.export.Credentials.from_service_account_info")
    @patch("app.export.os.getenv")
    def test_get_client_base64_credentials(self, mock_getenv, mock_credentials, mock_authorize):
        """Test _get_client with base64 encoded credentials"""
        # Create a proper JSON object and encode it
        mock_creds_dict = {"type": "service_account", "project_id": "mock-project"}
        mock_creds_json = json.dumps(mock_creds_dict)
        mock_creds_base64 = base64.b64encode(mock_creds_json.encode("utf-8")).decode("utf-8")

        # Setup mocks
        mock_getenv.return_value = mock_creds_base64
        mock_credentials.return_value = "mock_credentials_obj"
        mock_authorize.return_value = "mock_client"

        # Call the method with mocked dependencies
        result = self.exporter._get_client()

        # Check that authorize was called with the correct credentials
        mock_authorize.assert_called_once_with("mock_credentials_obj")
        assert result == "mock_client"
