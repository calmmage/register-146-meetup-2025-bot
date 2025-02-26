from pathlib import Path
import json
import gspread
import os
import base64
from google.oauth2.service_account import Credentials
from loguru import logger
from app.app import App, TargetCity

# Define the scopes for Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


class SheetExporter:
    def __init__(self, spreadsheet_id: str, app: App):
        """
        Initialize the exporter with spreadsheet ID.

        Args:
            spreadsheet_id: The ID of the Google Sheet to export to
        """
        self.spreadsheet_id = spreadsheet_id
        self.app = app

    def _get_client(self):
        """Create and return an authorized Google Sheets client using credentials from env var"""
        # First try to get base64 encoded credentials
        creds_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
        if creds_base64:
            # Decode base64 string to JSON string
            try:
                creds_json = base64.b64decode(creds_base64).decode("utf-8")
                creds_info = json.loads(creds_json)
                logger.info("Using base64 encoded credentials")
            except Exception as e:
                logger.error(f"Error decoding base64 credentials: {e}")
                raise ValueError("Invalid GOOGLE_CREDENTIALS_BASE64 format")
        else:
            # Fall back to regular JSON string if base64 not available
            creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
            if not creds_json:
                # Check if credentials file exists
                creds_file = os.getenv(
                    "GOOGLE_CREDENTIALS_FILE", "google-service-user-credentials.json"
                )
                if os.path.exists(creds_file):
                    logger.info(f"Using credentials file: {creds_file}")
                    credentials = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
                    return gspread.authorize(credentials)
                else:
                    raise ValueError(
                        "No Google credentials found. Set GOOGLE_CREDENTIALS_BASE64, GOOGLE_CREDENTIALS_JSON, or provide a credentials file."
                    )

            try:
                creds_info = json.loads(creds_json)
                logger.info("Using JSON string credentials")
            except json.JSONDecodeError:
                logger.error("Invalid JSON in GOOGLE_CREDENTIALS_JSON")
                raise ValueError("Invalid GOOGLE_CREDENTIALS_JSON format")

        # Create credentials object from the dictionary
        credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        return gspread.authorize(credentials)

    async def export_registered_users(self):
        """Export all registered users to the Google Sheet"""
        try:
            # Get all registered users from MongoDB
            cursor = self.app.collection.find({})
            users = await cursor.to_list(length=None)

            if not users:
                logger.info("No users to export")
                return "No users to export"

            # Connect to Google Sheets
            client = self._get_client()
            sheet = client.open_by_key(self.spreadsheet_id).sheet1

            # Prepare headers and data
            headers = ["Full Name", "Graduation Year", "Class", "City"]
            sheet.update("A1:D1", [headers])

            # Prepare user data
            rows = []
            for user in users:
                rows.append(
                    [
                        user["full_name"],
                        user["graduation_year"],
                        user["class_letter"],
                        user["target_city"],
                    ]
                )

            # Update the sheet with user data
            sheet.update(f"A2:D{len(rows)+1}", rows)

            message = f"Successfully exported  {len(rows)}  users to Google Sheets\n"
            message += "Available at: " + sheet.url
            logger.success(message)

            return message

        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            return f"Error exporting data: {e}"
