import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

from app.app import App, TargetCity, GraduateType


class TestAppPayment:
    """Tests for App payment calculation methods"""

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

    def teardown_method(self):
        """Clean up after each test"""
        # Stop all patchers
        self.db_patcher.stop()

    def test_calculate_payment_amount_teacher(self):
        """Test payment calculation for teachers (should be free)"""
        city = TargetCity.MOSCOW.value
        graduation_year = 2010
        graduate_type = GraduateType.TEACHER.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        assert regular == 0
        assert discount == 0
        assert discounted == 0
        assert formula == 0

    def test_calculate_payment_amount_saint_petersburg(self):
        """Test payment calculation for Saint Petersburg (should be free)"""
        city = TargetCity.SAINT_PETERSBURG.value
        graduation_year = 2010
        graduate_type = GraduateType.GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        assert regular == 0
        assert discount == 0
        assert discounted == 0
        assert formula == 0

    def test_calculate_payment_amount_non_graduate_moscow(self):
        """Test payment calculation for non-graduates in Moscow"""
        city = TargetCity.MOSCOW.value
        graduation_year = 2010
        graduate_type = GraduateType.NON_GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        assert regular == 4000
        assert discount == 1000
        assert discounted == 3000
        assert formula == 4000

    def test_calculate_payment_amount_non_graduate_perm(self):
        """Test payment calculation for non-graduates in Perm"""
        city = TargetCity.PERM.value
        graduation_year = 2010
        graduate_type = GraduateType.NON_GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        assert regular == 2000
        assert discount == 500
        assert discounted == 1500
        assert formula == 2000

    def test_calculate_payment_amount_recent_graduate_moscow(self):
        """Test payment calculation for recent graduates in Moscow"""
        city = TargetCity.MOSCOW.value
        graduation_year = 2020  # 5 years since graduation (in 2025)
        graduate_type = GraduateType.GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        # Formula: 1000 + (200 * 5) = 2000
        assert formula == 2000
        assert regular == 2000
        assert discount == 1000
        assert discounted == 1000

    def test_calculate_payment_amount_recent_graduate_perm(self):
        """Test payment calculation for recent graduates in Perm"""
        city = TargetCity.PERM.value
        graduation_year = 2020  # 5 years since graduation (in 2025)
        graduate_type = GraduateType.GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        # Formula: 500 + (100 * 5) = 1000
        assert formula == 1000
        assert regular == 1000
        assert discount == 500
        assert discounted == 500

    def test_calculate_payment_amount_old_graduate_moscow(self):
        """Test payment calculation for older graduates in Moscow (>15 years)"""
        city = TargetCity.MOSCOW.value
        graduation_year = 2005  # 20 years since graduation (in 2025)
        graduate_type = GraduateType.GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        # Formula: 1000 + (200 * 20) = 5000, but capped at 4000
        assert formula == 5000
        assert regular == 4000
        assert discount == 1000
        assert discounted == 3000

    def test_calculate_payment_amount_old_graduate_perm(self):
        """Test payment calculation for older graduates in Perm (>15 years)"""
        city = TargetCity.PERM.value
        graduation_year = 2005  # 20 years since graduation (in 2025)
        graduate_type = GraduateType.GRADUATE.value

        regular, discount, discounted, formula = self.app.calculate_payment_amount(
            city, graduation_year, graduate_type
        )

        # Formula: 500 + (100 * 20) = 2500, but capped at 2000
        assert formula == 2500
        assert regular == 2000
        assert discount == 500
        assert discounted == 1500

    @pytest.mark.asyncio
    @patch("app.app.datetime")
    async def test_save_payment_info(self, mock_datetime):
        """Test saving payment information"""
        # Mock datetime
        mock_now = datetime(2025, 3, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now

        user_id = 123456
        city = TargetCity.MOSCOW.value
        discounted_amount = 3000
        regular_amount = 4000
        screenshot_id = 7890
        formula_amount = 4000

        # Call the method
        await self.app.save_payment_info(
            user_id, city, discounted_amount, regular_amount, screenshot_id, formula_amount
        )

        # Check that update_one was called with correct parameters
        self.mock_collection.update_one.assert_called_once()
        call_args = self.mock_collection.update_one.call_args[0]

        # Check filter criteria
        assert call_args[0] == {"user_id": user_id, "target_city": city}

        # Check update data
        update_data = call_args[1]["$set"]
        assert update_data["discounted_payment_amount"] == discounted_amount
        assert update_data["regular_payment_amount"] == regular_amount
        assert update_data["payment_screenshot_id"] == screenshot_id
        assert update_data["formula_payment_amount"] == formula_amount
        assert update_data["payment_status"] == "pending"
        assert update_data["payment_timestamp"] == mock_now.isoformat()

    @pytest.mark.asyncio
    @patch("app.app.datetime")
    async def test_update_payment_status_first_payment(self, mock_datetime):
        """Test updating payment status with first payment"""
        # Mock datetime
        mock_now = datetime(2025, 3, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now

        # Mock find_one to return None (no previous payment)
        self.mock_collection.find_one.return_value = None

        user_id = 123456
        city = TargetCity.MOSCOW.value
        status = "confirmed"
        admin_comment = "Payment received"
        payment_amount = 3000

        # Call the method
        await self.app.update_payment_status(user_id, city, status, admin_comment, payment_amount)

        # Check that update_one was called with correct parameters
        self.mock_collection.update_one.assert_called_once()
        call_args = self.mock_collection.update_one.call_args[0]

        # Check filter criteria
        assert call_args[0] == {"user_id": user_id, "target_city": city}

        # Check update data
        update_data = call_args[1]["$set"]
        assert update_data["payment_status"] == status
        assert update_data["admin_comment"] == admin_comment
        assert update_data["payment_amount"] == payment_amount
        assert update_data["payment_verified_at"] == mock_now.isoformat()

        # Check payment history
        assert len(update_data["payment_history"]) == 1
        payment_record = update_data["payment_history"][0]
        assert payment_record["amount"] == payment_amount
        assert payment_record["total_after"] == payment_amount
        assert payment_record["timestamp"] == mock_now.isoformat()

    @pytest.mark.asyncio
    @patch("app.app.datetime")
    async def test_update_payment_status_additional_payment(self, mock_datetime):
        """Test updating payment status with additional payment"""
        # Mock datetime
        mock_now = datetime(2025, 3, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now

        # Mock collection with existing payment
        existing_payment = {
            "payment_amount": 2000,
            "payment_history": [
                {"amount": 2000, "timestamp": "2025-02-01T12:00:00", "total_after": 2000}
            ],
        }
        self.mock_collection.find_one.return_value = existing_payment

        user_id = 123456
        city = TargetCity.MOSCOW.value
        status = "confirmed"
        admin_comment = "Additional payment received"
        payment_amount = 1000  # Additional payment

        # Call the method
        await self.app.update_payment_status(user_id, city, status, admin_comment, payment_amount)

        # Check that update_one was called with correct parameters
        self.mock_collection.update_one.assert_called_once()
        call_args = self.mock_collection.update_one.call_args[0]

        # Check filter criteria
        assert call_args[0] == {"user_id": user_id, "target_city": city}

        # Check update data
        update_data = call_args[1]["$set"]
        assert update_data["payment_status"] == status
        assert update_data["admin_comment"] == admin_comment
        assert update_data["payment_amount"] == 3000  # 2000 + 1000
        assert update_data["payment_verified_at"] == mock_now.isoformat()

        # Check payment history
        assert len(update_data["payment_history"]) == 2
        payment_record = update_data["payment_history"][1]  # New record
        assert payment_record["amount"] == payment_amount
        assert payment_record["total_after"] == 3000
        assert payment_record["timestamp"] == mock_now.isoformat()

    @pytest.mark.asyncio
    @patch("app.app.datetime")
    async def test_update_payment_status_without_payment(self, mock_datetime):
        """Test updating payment status without payment amount"""
        # Mock datetime
        mock_now = datetime(2025, 3, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now

        user_id = 123456
        city = TargetCity.MOSCOW.value
        status = "declined"
        admin_comment = "Invalid payment screenshot"

        # Call the method
        await self.app.update_payment_status(user_id, city, status, admin_comment)

        # Check that update_one was called with correct parameters
        self.mock_collection.update_one.assert_called_once()
        call_args = self.mock_collection.update_one.call_args[0]

        # Check filter criteria
        assert call_args[0] == {"user_id": user_id, "target_city": city}

        # Check update data
        update_data = call_args[1]["$set"]
        assert update_data["payment_status"] == status
        assert update_data["admin_comment"] == admin_comment
        assert update_data["payment_verified_at"] == mock_now.isoformat()

        # Payment amount and history should not be present
        assert "payment_amount" not in update_data
        assert "payment_history" not in update_data
