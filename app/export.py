import base64
import gspread
import json
import os
from google.oauth2.service_account import Credentials
from loguru import logger

from app.app import App, GRADUATE_TYPE_MAP, PAYMENT_STATUS_MAP

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

    async def export_registered_users(self, silent=False):
        """Export all registered users to the Google Sheet
        
        Args:
            silent: If True, suppresses any return messages for background operation
        """
        try:
            # Get all registered users from MongoDB
            cursor = self.app.collection.find({})
            users = await cursor.to_list(length=None)

            if not users:
                logger.info("Нет пользователей для экспорта")
                if not silent:
                    return "Нет пользователей для экспорта"
                return None

            # Connect to Google Sheets
            client = self._get_client()
            sheet = client.open_by_key(self.spreadsheet_id).sheet1

            # Prepare headers and data
            headers = [
                "ФИО", 
                "Год выпуска", 
                "Класс", 
                "Город участия во встрече",
                "Статус участника",  # graduate_type
                "Telegram Username", 
                "Статус оплаты", 
                "Сумма оплаты (факт)", 
                "Мин. сумма со скидкой",
                "Регулярная сумма",
                "Формула",
                "Дата оплаты"
            ]
            sheet.update([headers])

            # Prepare user data
            rows = []
            for user in users:
                # Get payment status and all payment amounts
                raw_status = user.get("payment_status", None)
                payment_status = PAYMENT_STATUS_MAP.get(raw_status, PAYMENT_STATUS_MAP[None])
                payment_amount = user.get("payment_amount", 0)  # Actual payment amount
                discounted_amount = user.get("discounted_payment_amount", 0)  # Min amount with discount
                regular_amount = user.get("regular_payment_amount", 0)  # Regular amount without discount
                formula_amount = user.get("formula_payment_amount", 0)  # Amount from formula
                payment_timestamp = user.get("payment_timestamp", "")
                
                # Get graduate type and convert to human-readable format
                graduate_type = user.get("graduate_type", "GRADUATE")
                graduate_type_display = GRADUATE_TYPE_MAP.get(graduate_type, "Выпускник")  # Default to "Выпускник" if type is unknown
                
                rows.append(
                    [
                        user["full_name"],
                        user["graduation_year"],
                        user["class_letter"],
                        user["target_city"],
                        graduate_type_display,  # Add graduate type
                        user.get("username", ""),
                        payment_status,
                        payment_amount,
                        discounted_amount,
                        regular_amount,
                        formula_amount,
                        payment_timestamp
                    ]
                )

            # Update the sheet with user data
            if rows:
                sheet.update("A2", rows)

            message = f"Успешно экспортировано {len(rows)} пользователей в Google Таблицы\n"
            message += "Доступно по ссылке: " + sheet.url
            logger.success(message)

            if not silent:
                return message
            return None

        except Exception as e:
            logger.error(f"Ошибка при экспорте данных: {e}")
            if not silent:
                return f"Ошибка при экспорте данных: {e}"
            return None

    async def export_to_csv(self):
        """Export all registered users to a CSV file"""
        try:
            # Get all registered users from MongoDB
            cursor = self.app.collection.find({})
            users = await cursor.to_list(length=None)

            if not users:
                logger.info("Нет пользователей для экспорта")
                return None, "Нет пользователей для экспорта"

            # Create CSV content
            import csv
            from io import StringIO

            output = StringIO()
            writer = csv.writer(output)

            # Write headers
            headers = [
                "ФИО", 
                "Год выпуска", 
                "Класс", 
                "Город участия во встрече",
                "Статус участника",  # graduate_type
                "Telegram Username", 
                "Статус оплаты", 
                "Сумма оплаты (факт)", 
                "Мин. сумма со скидкой",
                "Регулярная сумма",
                "Формула",
                "Дата оплаты"
            ]
            writer.writerow(headers)

            # Write user data
            for user in users:
                # Get payment status and all payment amounts
                raw_status = user.get("payment_status", None)
                payment_status = PAYMENT_STATUS_MAP.get(raw_status, PAYMENT_STATUS_MAP[None])
                payment_amount = user.get("payment_amount", 0)  # Actual payment amount
                discounted_amount = user.get("discounted_payment_amount", 0)  # Min amount with discount
                regular_amount = user.get("regular_payment_amount", 0)  # Regular amount without discount
                formula_amount = user.get("formula_payment_amount", 0)  # Amount from formula
                payment_timestamp = user.get("payment_timestamp", "")
                
                # Get graduate type and convert to human-readable format
                graduate_type = user.get("graduate_type", "GRADUATE")
                graduate_type_display = GRADUATE_TYPE_MAP.get(graduate_type, "Выпускник")  # Default to "Выпускник" if type is unknown
                
                writer.writerow(
                    [
                        user["full_name"],
                        user["graduation_year"],
                        user["class_letter"],
                        user["target_city"],
                        graduate_type_display,  # Add graduate type
                        user.get("username", ""),
                        payment_status,
                        payment_amount,
                        discounted_amount,
                        regular_amount,
                        formula_amount,
                        payment_timestamp
                    ]
                )

            csv_content = output.getvalue()
            output.close()

            logger.success(f"Успешно экспортировано {len(users)} пользователей в CSV")
            return csv_content, f"Успешно экспортировано {len(users)} пользователей в CSV"

        except Exception as e:
            logger.error(f"Ошибка при экспорте данных в CSV: {e}")
            return None, f"Ошибка при экспорте данных в CSV: {e}"
