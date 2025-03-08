import pytest
import os
import json
import base64
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from io import StringIO

from app.app import App
from app.export import SheetExporter


class TestSheetExporter:
    """Tests for the SheetExporter class"""
    
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
        
        # Create exporter with the mocked app
        self.exporter = SheetExporter("mock_spreadsheet_id", app=self.app)
        
        # Sample user data
        self.sample_users = [
            {
                "full_name": "Иванов Иван",
                "graduation_year": 2010,
                "class_letter": "А",
                "target_city": "Москва",
                "user_id": 123456,
                "username": "ivan_ivanov",
                "graduate_type": "graduate",
                "payment_status": "confirmed",
                "payment_amount": 3000,
                "discounted_payment_amount": 3000,
                "regular_payment_amount": 4000,
                "formula_payment_amount": 4000,
                "payment_timestamp": "2025-02-01T12:00:00"
            },
            {
                "full_name": "Петров Петр",
                "graduation_year": 2005,
                "class_letter": "Б",
                "target_city": "Пермь",
                "user_id": 654321,
                "username": "petr_petrov",
                "graduate_type": "graduate",
                "payment_status": "pending",
                "payment_amount": 0,
                "discounted_payment_amount": 1500,
                "regular_payment_amount": 2000,
                "formula_payment_amount": 2500,
                "payment_timestamp": "2025-02-02T12:00:00"
            }
        ]
    
    def teardown_method(self):
        """Clean up after each test"""
        # Stop all patchers
        self.db_patcher.stop()

    @patch("app.export.gspread.authorize")
    @patch("app.export.Credentials.from_service_account_info")
    @patch("app.export.os.getenv")
    def test_get_client_base64_credentials(self, mock_getenv, mock_credentials, mock_authorize):
        """Test _get_client with base64 encoded credentials"""
        # Mock base64 credentials
        mock_creds_dict = {"type": "service_account", "project_id": "mock-project"}
        mock_creds_json = json.dumps(mock_creds_dict)
        mock_creds_base64 = base64.b64encode(mock_creds_json.encode('utf-8')).decode('utf-8')
        
        # Setup mocks
        mock_getenv.return_value = mock_creds_base64
        mock_credentials.return_value = "mock_credentials"
        mock_authorize.return_value = "mock_authorized_client"
        
        # Call the method
        client = self.exporter._get_client()
        
        # Verify the results
        mock_getenv.assert_called_with("GOOGLE_CREDENTIALS_BASE64")
        mock_credentials.assert_called_with(mock_creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        mock_authorize.assert_called_with("mock_credentials")
        assert client == "mock_authorized_client"

    @patch("app.export.gspread.authorize")
    @patch("app.export.Credentials.from_service_account_info")
    @patch("app.export.os.getenv")
    def test_get_client_json_credentials(self, mock_getenv, mock_credentials, mock_authorize):
        """Test _get_client with JSON string credentials"""
        # Mock JSON credentials
        mock_creds_dict = {"type": "service_account", "project_id": "mock-project"}
        mock_creds_json = json.dumps(mock_creds_dict)
        
        # Setup mocks
        mock_getenv.side_effect = [None, mock_creds_json]  # No BASE64, but JSON is available
        mock_credentials.return_value = "mock_credentials"
        mock_authorize.return_value = "mock_authorized_client"
        
        # Call the method
        client = self.exporter._get_client()
        
        # Verify the results
        assert mock_getenv.call_count == 2
        mock_getenv.assert_any_call("GOOGLE_CREDENTIALS_BASE64")
        mock_getenv.assert_any_call("GOOGLE_CREDENTIALS_JSON")
        mock_credentials.assert_called_with(mock_creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        mock_authorize.assert_called_with("mock_credentials")
        assert client == "mock_authorized_client"

    @patch("app.export.gspread.authorize")
    @patch("app.export.Credentials.from_service_account_file")
    @patch("app.export.os.path.exists")
    @patch("app.export.os.getenv")
    def test_get_client_credentials_file(self, mock_getenv, mock_path_exists, mock_credentials, mock_authorize):
        """Test _get_client with credentials file"""
        # Setup mocks
        mock_getenv.side_effect = [None, None, "credentials.json"]  # No BASE64 or JSON
        mock_path_exists.return_value = True
        mock_credentials.return_value = "mock_credentials"
        mock_authorize.return_value = "mock_authorized_client"
        
        # Call the method
        client = self.exporter._get_client()
        
        # Verify the results
        assert mock_getenv.call_count == 3
        mock_getenv.assert_any_call("GOOGLE_CREDENTIALS_BASE64")
        mock_getenv.assert_any_call("GOOGLE_CREDENTIALS_JSON")
        mock_getenv.assert_any_call("GOOGLE_CREDENTIALS_FILE", "google-service-user-credentials.json")
        mock_path_exists.assert_called_with("credentials.json")
        mock_credentials.assert_called_with("credentials.json", scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        mock_authorize.assert_called_with("mock_credentials")
        assert client == "mock_authorized_client"

    @patch("app.export.os.getenv")
    @patch("app.export.os.path.exists")
    def test_get_client_no_credentials(self, mock_path_exists, mock_getenv):
        """Test _get_client with no credentials available"""
        # Setup mocks
        mock_getenv.side_effect = [None, None, "credentials.json"]  # No BASE64 or JSON
        mock_path_exists.return_value = False  # No credentials file
        
        # Call the method and expect an error
        with pytest.raises(ValueError) as exc_info:
            self.exporter._get_client()
        
        # Verify the error message
        assert "No Google credentials found" in str(exc_info.value)

    @patch("app.export.SheetExporter._get_client")
    @patch("app.export.logger")
    async def test_export_registered_users_success(self, mock_logger, mock_get_client):
        """Test export_registered_users successfully exports data"""
        # Mock app collection to return sample users
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = self.sample_users
        self.mock_collection.find.return_value = mock_cursor
        
        # Mock Google Sheets client
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.url = "https://docs.google.com/spreadsheets/d/mock_id"
        mock_client.open_by_key.return_value.sheet1 = mock_sheet
        mock_get_client.return_value = mock_client
        
        # Call the method
        result = await self.exporter.export_registered_users()
        
        # Verify the results
        self.mock_collection.find.assert_called_once_with({})
        mock_get_client.assert_called_once()
        mock_client.open_by_key.assert_called_once_with("mock_spreadsheet_id")
        
        # Verify the sheet updates
        assert mock_sheet.update.call_count == 2
        
        # Verify the headers
        headers_call = mock_sheet.update.call_args_list[0]
        headers = headers_call[0][0][0]
        assert "ФИО" in headers
        assert "Год выпуска" in headers
        assert "Город участия во встрече" in headers
        
        # Verify the data
        data_call = mock_sheet.update.call_args_list[1]
        assert data_call[0][0] == "A2"
        rows = data_call[0][1]
        assert len(rows) == 2
        
        # Verify log message
        mock_logger.success.assert_called_once()
        
        # Verify returned message
        assert "Успешно экспортировано 2 пользователей" in result
        assert "https://docs.google.com/spreadsheets/d/mock_id" in result

    @patch("app.export.SheetExporter._get_client")
    @patch("app.export.logger")
    async def test_export_registered_users_no_users(self, mock_logger, mock_get_client):
        """Test export_registered_users with no users to export"""
        # Mock app collection with no users
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = []
        self.mock_collection.find.return_value = mock_cursor
        
        # Call the method
        result = await self.exporter.export_registered_users()
        
        # Verify the results
        self.mock_collection.find.assert_called_once_with({})
        mock_get_client.assert_not_called()
        
        # Verify log message
        mock_logger.info.assert_called_once_with("Нет пользователей для экспорта")
        
        # Verify returned message
        assert result == "Нет пользователей для экспорта"

    @patch("app.export.logger")
    async def test_export_registered_users_error(self, mock_logger):
        """Test export_registered_users handling errors"""
        # Mock app collection to raise an exception
        self.mock_collection.find.side_effect = Exception("Test error")
        
        # Call the method
        result = await self.exporter.export_registered_users()
        
        # Verify error handling
        mock_logger.error.assert_called_once()
        assert "Test error" in mock_logger.error.call_args[0][0]
        
        # Verify returned message
        assert "Ошибка при экспорте данных: Test error" == result

    @patch("app.export.csv.writer")
    @patch("app.export.StringIO")
    @patch("app.export.logger")
    async def test_export_to_csv_success(self, mock_logger, mock_stringio, mock_csv_writer):
        """Test export_to_csv successfully exports data"""
        # Mock app collection to return sample users
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = self.sample_users
        self.mock_collection.find.return_value = mock_cursor
        
        # Mock StringIO and CSV writer
        mock_output = MagicMock()
        mock_output.getvalue.return_value = "CSV content"
        mock_stringio.return_value = mock_output
        mock_writer = MagicMock()
        mock_csv_writer.return_value = mock_writer
        
        # Call the method
        csv_content, message = await self.exporter.export_to_csv()
        
        # Verify the results
        self.mock_collection.find.assert_called_once_with({})
        mock_stringio.assert_called_once()
        mock_csv_writer.assert_called_once()
        
        # Verify writer calls
        assert mock_writer.writerow.call_count >= 1  # Headers
        assert mock_writer.writerow.call_count >= 3  # Headers + 2 users
        
        # Verify output
        mock_output.getvalue.assert_called_once()
        mock_output.close.assert_called_once()
        
        # Verify log message
        mock_logger.success.assert_called_once_with("Успешно экспортировано 2 пользователей в CSV")
        
        # Verify returned values
        assert csv_content == "CSV content"
        assert "Успешно экспортировано 2 пользователей в CSV" == message

    @patch("app.export.logger")
    async def test_export_to_csv_no_users(self, mock_logger):
        """Test export_to_csv with no users to export"""
        # Mock app collection with no users
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = []
        self.mock_collection.find.return_value = mock_cursor
        
        # Call the method
        csv_content, message = await self.exporter.export_to_csv()
        
        # Verify the results
        self.mock_collection.find.assert_called_once_with({})
        
        # Verify log message
        mock_logger.info.assert_called_once_with("Нет пользователей для экспорта")
        
        # Verify returned values
        assert csv_content is None
        assert message == "Нет пользователей для экспорта"

    @patch("app.export.logger")
    async def test_export_to_csv_error(self, mock_logger):
        """Test export_to_csv handling errors"""
        # Mock app collection to raise an exception
        self.mock_collection.find.side_effect = Exception("Test error")
        
        # Call the method
        csv_content, message = await self.exporter.export_to_csv()
        
        # Verify error handling
        mock_logger.error.assert_called_once()
        assert "Test error" in mock_logger.error.call_args[0][0]
        
        # Verify returned values
        assert csv_content is None
        assert message == "Ошибка при экспорте данных в CSV: Test error"