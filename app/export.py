import base64
import json
import os

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from app.app import App, GRADUATE_TYPE_MAP, PAYMENT_STATUS_MAP
from botspot import get_database

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
        # Get spreadsheet
        spreadsheet = client.open_by_key(self.spreadsheet_id)

        # Ensure we have worksheets for each category
        worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]

        # Main sheet
        if "Все города" not in worksheet_titles:
            spreadsheet.add_worksheet(title="Все города", rows=1000, cols=20)
        main_sheet = spreadsheet.worksheet("Все города")
        main_sheet.clear()

        # City-specific sheets
        city_sheets = {}
        for city in ["Москва", "Санкт-Петербург", "Пермь", "Белград"]:
            if city not in worksheet_titles:
                spreadsheet.add_worksheet(title=city, rows=1000, cols=20)
            city_sheets[city] = spreadsheet.worksheet(city)
            city_sheets[city].clear()

        # Graduate type sheets
        type_sheets = {}
        for graduate_type in ["Выпускники", "Учителя", "Друзья", "Организаторы"]:
            if graduate_type not in worksheet_titles:
                spreadsheet.add_worksheet(title=graduate_type, rows=1000, cols=20)
            type_sheets[graduate_type] = spreadsheet.worksheet(graduate_type)
            type_sheets[graduate_type].clear()

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
            "Дата оплаты",
        ]

        # Update all sheets with headers
        main_sheet.update([headers])
        for sheet in city_sheets.values():
            sheet.update([headers])
        for sheet in type_sheets.values():
            sheet.update([headers])

        # Prepare user data for each sheet
        main_rows = []
        city_rows = {city: [] for city in city_sheets.keys()}
        type_rows = {graduate_type: [] for graduate_type in type_sheets.keys()}
        for user in users:
            # Get payment status and all payment amounts
            raw_status = user.get("payment_status", None)
            payment_status = PAYMENT_STATUS_MAP.get(raw_status, PAYMENT_STATUS_MAP[None])
            payment_amount = user.get("payment_amount", 0)  # Actual payment amount
            discounted_amount = user.get("discounted_payment_amount", 0)  # Min amount with discount
            regular_amount = user.get(
                "regular_payment_amount", 0
            )  # Regular amount without discount
            formula_amount = user.get("formula_payment_amount", 0)  # Amount from formula
            payment_timestamp = user.get("payment_timestamp", "")

            # Get graduate type and convert to human-readable format
            graduate_type = user.get("graduate_type", "GRADUATE")
            graduate_type_display = GRADUATE_TYPE_MAP.get(
                graduate_type, "Выпускник"
            )  # Default to "Выпускник" if type is unknown

            # Create a row of user data
            user_row = [
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
                payment_timestamp,
            ]

            # Add to main sheet
            main_rows.append(user_row)

            # Add to city sheet
            city = user["target_city"]
            if city in city_rows:
                city_rows[city].append(user_row)

            # Add to graduate type sheet
            if graduate_type_display == "Выпускник":
                type_rows["Выпускники"].append(user_row)
            elif graduate_type_display == "Учитель":
                type_rows["Учителя"].append(user_row)
            elif graduate_type_display == "Друг":
                type_rows["Друзья"].append(user_row)
            elif graduate_type_display == "Организатор":
                type_rows["Организаторы"].append(user_row)

        # Update all sheets with user data
        if main_rows:
            main_sheet.update("A2", main_rows)

        # Update city sheets
        for city, rows in city_rows.items():
            if rows:
                city_sheets[city].update("A2", rows)

        # Update graduate type sheets
        for graduate_type, rows in type_rows.items():
            if rows:
                type_sheets[graduate_type].update("A2", rows)

        message = f"Успешно экспортировано {len(main_rows)} пользователей в Google Таблицы\n"
        message += "Доступно по ссылке: " + main_sheet.url
        logger.success(message)

        if not silent:
            return message
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
                "Дата оплаты",
            ]
            writer.writerow(headers)

            # Write user data
            for user in users:
                # Get payment status and all payment amounts
                raw_status = user.get("payment_status", None)
                payment_status = PAYMENT_STATUS_MAP.get(raw_status, PAYMENT_STATUS_MAP[None])
                payment_amount = user.get("payment_amount", 0)  # Actual payment amount
                discounted_amount = user.get(
                    "discounted_payment_amount", 0
                )  # Min amount with discount
                regular_amount = user.get(
                    "regular_payment_amount", 0
                )  # Regular amount without discount
                formula_amount = user.get("formula_payment_amount", 0)  # Amount from formula
                payment_timestamp = user.get("payment_timestamp", "")

                # Get graduate type and convert to human-readable format
                graduate_type = user.get("graduate_type", "GRADUATE")
                graduate_type_display = GRADUATE_TYPE_MAP.get(
                    graduate_type, "Выпускник"
                )  # Default to "Выпускник" if type is unknown

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
                        payment_timestamp,
                    ]
                )

            csv_content = output.getvalue()
            output.close()

            logger.success(f"Успешно экспортировано {len(users)} пользователей в CSV")
            return csv_content, f"Успешно экспортировано {len(users)} пользователей в CSV"

        except Exception as e:
            logger.error(f"Ошибка при экспорте данных в CSV: {e}")
            return None, f"Ошибка при экспорте данных в CSV: {e}"

    async def export_deleted_users_to_csv(self):
        """Export all deleted users to a CSV file"""
        # Get all deleted users from MongoDB
        cursor = self.app.deleted_users.find({})
        users = await cursor.to_list(length=None)

        if not users:
            logger.info("Нет удаленных пользователей для экспорта")
            return None, "Нет удаленных пользователей для экспорта"

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
            "Дата удаления",
            "Причина удаления",
        ]
        writer.writerow(headers)

        # Write user data
        for user in users:
            # Get payment status and amount
            raw_status = user.get("payment_status", None)
            payment_status = PAYMENT_STATUS_MAP.get(raw_status, PAYMENT_STATUS_MAP[None])
            payment_amount = user.get("payment_amount", 0)  # Actual payment amount

            # Get graduate type and convert to human-readable format
            graduate_type = user.get("graduate_type", "GRADUATE")
            graduate_type_display = GRADUATE_TYPE_MAP.get(
                graduate_type, "Выпускник"
            )  # Default to "Выпускник" if type is unknown

            # Get deletion info
            deletion_timestamp = user.get("deletion_timestamp", "")
            deletion_reason = user.get("deletion_reason", "")

            writer.writerow(
                [
                    user["full_name"],
                    user["graduation_year"],
                    user["class_letter"],
                    user["target_city"],
                    graduate_type_display,
                    user.get("username", ""),
                    payment_status,
                    payment_amount,
                    deletion_timestamp,
                    deletion_reason,
                ]
            )

        csv_content = output.getvalue()
        output.close()

        logger.success(f"Успешно экспортировано {len(users)} удаленных пользователей в CSV")
        return csv_content, f"Успешно экспортировано {len(users)} удаленных пользователей в CSV"

    async def export_feedback_to_sheets(self, silent=False):
        """Export all feedback to a dedicated sheet in the Google Spreadsheet

        Args:
            silent: If True, suppresses any return messages for background operation
        """
        # Create feedback collection if it doesn't exist
        if not hasattr(self.app, "_feedback_collection"):
            self.app._feedback_collection = get_database().get_collection("feedback")

        # Get all feedback from MongoDB
        cursor = self.app._feedback_collection.find({})
        feedback_items = await cursor.to_list(length=None)

        if not feedback_items:
            logger.info("Нет отзывов для экспорта")
            if not silent:
                return "Нет отзывов для экспорта"
            return None

        # Connect to Google Sheets
        client = self._get_client()

        # Get spreadsheet
        spreadsheet = client.open_by_key(self.spreadsheet_id)

        # Ensure we have a worksheet for feedback
        worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]

        if "Отзывы" not in worksheet_titles:
            spreadsheet.add_worksheet(title="Отзывы", rows=1000, cols=20)
        feedback_sheet = spreadsheet.worksheet("Отзывы")
        feedback_sheet.clear()

        # Prepare headers
        headers = [
            "Имя",
            "Username",
            "ID пользователя",
            "Был на встрече",
            "Город",
            "Рекомендация (1-5)",
            "Площадка (1-5)",
            "Еда (1-5)",
            "Развлечения (1-5)",
            "Будет помогать",
            "Комментарии",
            "Дата отзыва",
        ]

        # Update sheet with headers
        feedback_sheet.update([headers])

        # Prepare feedback data rows
        feedback_rows = []

        for item in feedback_items:
            # Format attended status
            attended = "Да" if item.get("attended") else "Нет"

            # Format help interest
            help_interest = item.get("help_interest", "")
            if help_interest == "yes":
                help_interest = "Да"
            elif help_interest == "no":
                help_interest = "Нет"
            elif help_interest == "maybe":
                help_interest = "Возможно"

            # Create a row of feedback data
            feedback_row = [
                item.get("full_name", ""),
                item.get("username", ""),
                item.get("user_id", ""),
                attended,
                item.get("city", ""),
                item.get("recommendation_level", ""),
                item.get("venue_rating", ""),
                item.get("food_rating", ""),
                item.get("entertainment_rating", ""),
                help_interest,
                item.get("comments", ""),
                item.get("timestamp", ""),
            ]

            feedback_rows.append(feedback_row)

        # Update sheet with feedback data
        if feedback_rows:
            feedback_sheet.update("A2", feedback_rows)

        message = f"Успешно экспортировано {len(feedback_rows)} отзывов в Google Таблицы\n"
        message += "Доступно по ссылке: " + feedback_sheet.url
        logger.success(message)

        if not silent:
            return message
        return None

    async def export_feedback_to_csv(self):
        """Export all feedback to a CSV file"""
        try:
            # Create feedback collection if it doesn't exist
            if not hasattr(self.app, "_feedback_collection"):
                self.app._feedback_collection = get_database().get_collection("feedback")

            # Get all feedback from MongoDB
            cursor = self.app._feedback_collection.find({})
            feedback_items = await cursor.to_list(length=None)

            if not feedback_items:
                logger.info("Нет отзывов для экспорта")
                return None, "Нет отзывов для экспорта"

            # Create CSV content
            import csv
            from io import StringIO

            output = StringIO()
            writer = csv.writer(output)

            # Write headers
            headers = [
                "Имя",
                "Username",
                "ID пользователя",
                "Был на встрече",
                "Город",
                "Рекомендация (1-5)",
                "Площадка (1-5)",
                "Еда (1-5)",
                "Развлечения (1-5)",
                "Будет помогать",
                "Комментарии",
                "Дата отзыва",
            ]
            writer.writerow(headers)

            # Write feedback data
            for item in feedback_items:
                # Format attended status
                attended = "Да" if item.get("attended") else "Нет"

                # Format help interest
                help_interest = item.get("help_interest", "")
                if help_interest == "yes":
                    help_interest = "Да"
                elif help_interest == "no":
                    help_interest = "Нет"
                elif help_interest == "maybe":
                    help_interest = "Возможно"

                writer.writerow(
                    [
                        item.get("full_name", ""),
                        item.get("username", ""),
                        item.get("user_id", ""),
                        attended,
                        item.get("city", ""),
                        item.get("recommendation_level", ""),
                        item.get("venue_rating", ""),
                        item.get("food_rating", ""),
                        item.get("entertainment_rating", ""),
                        help_interest,
                        item.get("comments", ""),
                        item.get("timestamp", ""),
                    ]
                )

            csv_content = output.getvalue()
            output.close()

            logger.success(f"Успешно экспортировано {len(feedback_items)} отзывов в CSV")
            return csv_content, f"Успешно экспортировано {len(feedback_items)} отзывов в CSV"

        except Exception as e:
            logger.error(f"Ошибка при экспорте отзывов в CSV: {e}")
            return None, f"Ошибка при экспорте отзывов в CSV: {e}"
