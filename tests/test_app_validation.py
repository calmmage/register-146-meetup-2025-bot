import pytest
from unittest.mock import patch, MagicMock

from app.app import App


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("PAYMENT_PHONE_NUMBER", "test_number")
    monkeypatch.setenv("PAYMENT_NAME", "test_name")


class TestAppValidation:
    """Tests for App validation methods"""

    def setup_method(self):
        """Set up test environment before each test"""
        # Mock database connection
        with patch("app.app.get_database"):
            self.app = App(
                telegram_bot_token="mock_token",
                payment_phone_number="1234567890",
                payment_name="Test User",
            )

    def test_validate_full_name_valid(self):
        """Test validate_full_name with valid input"""
        valid_names = ["Иванов Иван", "Петрова Мария Ивановна", "Сергеев-Иванов Петр"]

        for name in valid_names:
            is_valid, error = self.app.validate_full_name(name)
            assert is_valid is True
            assert error == ""

    def test_validate_full_name_invalid(self):
        """Test validate_full_name with invalid input"""
        test_cases = [
            # Single word
            ("Иванов", False, "Пожалуйста, укажите хотя бы имя и фамилию :)"),
            # Non-Russian letters
            ("Ivan Ivanov", False, "По-русски, пожалуйста :)"),
            # Mixed languages
            ("Иванов Ivan", False, "По-русски, пожалуйста :)"),
            # Numbers
            ("Иванов 123", False, "По-русски, пожалуйста :)"),
        ]

        for name, expected_valid, expected_error in test_cases:
            is_valid, error = self.app.validate_full_name(name)
            assert is_valid is expected_valid
            assert error == expected_error

    def test_validate_graduation_year_valid(self):
        """Test validate_graduation_year with valid input"""
        valid_years = [1996, 2000, 2010, 2020]

        for year in valid_years:
            is_valid, error = self.app.validate_graduation_year(year)
            assert is_valid is True
            assert error == ""

    @patch("app.app.datetime")
    def test_validate_graduation_year_invalid(self, mock_datetime):
        """Test validate_graduation_year with invalid input"""
        # Mock current year to be 2025 for consistent tests
        mock_now = MagicMock()
        mock_now.year = 2025
        mock_datetime.now.return_value = mock_now

        test_cases = [
            # Too early
            (1995, False, "Год выпуска должен быть не раньше 1996."),
            # Current year
            (2025, False, "Извините, регистрация только для выпускников. Приходите после выпуска!"),
            # Future year within acceptable range
            (2028, False, "Извините, регистрация только для выпускников. Приходите после выпуска!"),
            # Future year beyond acceptable range
            (2030, False, "Год выпуска не может быть позже 2029."),
        ]

        for year, expected_valid, expected_error in test_cases:
            is_valid, error = self.app.validate_graduation_year(year)
            assert is_valid is expected_valid
            assert error == expected_error

    def test_validate_class_letter_valid(self):
        """Test validate_class_letter with valid input"""
        valid_letters = ["А", "Б", "В", "а", "б", "в"]

        for letter in valid_letters:
            is_valid, error = self.app.validate_class_letter(letter)
            assert is_valid is True
            assert error == ""

    def test_validate_class_letter_invalid(self):
        """Test validate_class_letter with invalid input"""
        test_cases = [
            # Empty string
            ("", False, "Пожалуйста, укажите букву класса."),
            # Non-Russian letter
            ("A", False, "Буква класса должна быть на русском языке."),
            # Multiple letters
            ("АБ", False, "Буква класса должна быть только одним символом."),
            # Numbers
            ("1", False, "Буква класса должна быть на русском языке."),
        ]

        for letter, expected_valid, expected_error in test_cases:
            is_valid, error = self.app.validate_class_letter(letter)
            assert is_valid is expected_valid
            assert error == expected_error

    @patch("app.app.datetime")
    def test_parse_graduation_year_and_class_letter(self, mock_datetime):
        """Test parse_graduation_year_and_class_letter function"""
        # Mock current year to be 2025 for consistent tests
        mock_now = MagicMock()
        mock_now.year = 2025
        mock_datetime.now.return_value = mock_now

        test_cases = [
            # Case 0: Only year
            ("2010", 2010, "", "Пожалуйста, укажите также букву класса."),
            # Case 1: Year and space and letter
            ("2010 А", 2010, "А", None),
            # Case 2: Year followed by letter without space
            ("2010А", 2010, "А", None),
            # Invalid year
            ("1990А", None, None, "Год выпуска должен быть не раньше 1996."),
            # Invalid letter
            ("2010 A", None, None, "Буква класса должна быть на русском языке."),
            # Invalid format
            (
                "abc",
                None,
                None,
                "Неверный формат. Пожалуйста, введите год выпуска и букву класса (например, '2003 Б').",
            ),
        ]

        for input_str, expected_year, expected_letter, expected_error in test_cases:
            year, letter, error = self.app.parse_graduation_year_and_class_letter(input_str)
            assert year == expected_year
            assert letter == expected_letter
            assert error == expected_error
