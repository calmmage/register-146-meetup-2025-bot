import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.app import (
    App,
    TargetCity,
    GraduateType,
    GuestInfo,
    PlusOnePricingStrategy,
    RegisteredUser,
)


class TestGuestModels:
    """Tests for GuestInfo and PlusOnePricingStrategy models"""

    def test_guest_info_creation(self):
        """Test creating a GuestInfo instance"""
        guest = GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500)
        assert guest.full_name == "Иванова Анна"
        assert guest.relationship == "Супруг(а)"
        assert guest.payment_amount == 1500

    def test_guest_info_default_payment(self):
        """Test GuestInfo default payment amount is 0"""
        guest = GuestInfo(full_name="Петров Петр", relationship="Друг/Подруга")
        assert guest.payment_amount == 0

    def test_guest_info_serialization(self):
        """Test GuestInfo serialization to dict"""
        guest = GuestInfo(full_name="Иванова Анна", relationship="Коллега", payment_amount=1800)
        data = guest.model_dump()
        assert data == {
            "full_name": "Иванова Анна",
            "relationship": "Коллега",
            "payment_amount": 1800,
        }

    def test_registered_user_with_guests(self):
        """Test RegisteredUser with guests list"""
        guests = [
            GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500),
            GuestInfo(full_name="Петров Петр", relationship="Друг/Подруга", payment_amount=1500),
        ]
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.PERM_SUMMER_2025,
            guests=guests,
        )
        assert len(user.guests) == 2
        assert user.guests[0].full_name == "Иванова Анна"
        assert user.guests[1].payment_amount == 1500

    def test_registered_user_empty_guests(self):
        """Test RegisteredUser with no guests defaults to empty list"""
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.MOSCOW,
        )
        assert user.guests == []

    def test_pricing_strategy_enum(self):
        """Test PlusOnePricingStrategy enum values"""
        assert PlusOnePricingStrategy.SAME_AS_REGISTRANT == "same_as_registrant"
        assert PlusOnePricingStrategy.SAME_WITH_MINIMUM == "same_with_minimum"


class TestGuestPricing:
    """Tests for guest price calculation"""

    def setup_method(self):
        """Set up test environment before each test"""
        mock_db = MagicMock()
        mock_db.get_collection.return_value = AsyncMock()
        self.db_patcher = patch("app.app.get_database", return_value=mock_db)
        self.db_patcher.start()

        self.app = App(
            telegram_bot_token="mock_token",
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

    def teardown_method(self):
        self.db_patcher.stop()

    def test_guest_price_same_as_registrant(self):
        """Test SAME_AS_REGISTRANT strategy returns registrant price"""
        # Override config for test
        self.app.PLUS_ONE_CONFIG = {
            "TestCity": {
                "enabled": True,
                "max_guests": 2,
                "pricing_strategy": PlusOnePricingStrategy.SAME_AS_REGISTRANT,
            },
        }
        price = self.app.calculate_guest_price("TestCity", 1800)
        assert price == 1800

    def test_guest_price_same_with_minimum_above(self):
        """Test SAME_WITH_MINIMUM when registrant price > minimum"""
        self.app.PLUS_ONE_CONFIG = {
            "TestCity": {
                "enabled": True,
                "max_guests": 2,
                "pricing_strategy": PlusOnePricingStrategy.SAME_WITH_MINIMUM,
                "min_guest_price": 1500,
            },
        }
        price = self.app.calculate_guest_price("TestCity", 1800)
        assert price == 1800

    def test_guest_price_same_with_minimum_below(self):
        """Test SAME_WITH_MINIMUM when registrant price < minimum (floor applies)"""
        self.app.PLUS_ONE_CONFIG = {
            "TestCity": {
                "enabled": True,
                "max_guests": 2,
                "pricing_strategy": PlusOnePricingStrategy.SAME_WITH_MINIMUM,
                "min_guest_price": 1500,
            },
        }
        price = self.app.calculate_guest_price("TestCity", 1300)
        assert price == 1500

    def test_guest_price_same_with_minimum_equal(self):
        """Test SAME_WITH_MINIMUM when registrant price == minimum"""
        self.app.PLUS_ONE_CONFIG = {
            "TestCity": {
                "enabled": True,
                "max_guests": 2,
                "pricing_strategy": PlusOnePricingStrategy.SAME_WITH_MINIMUM,
                "min_guest_price": 1500,
            },
        }
        price = self.app.calculate_guest_price("TestCity", 1500)
        assert price == 1500

    def test_guest_price_unconfigured_city(self):
        """Test guest price for city without plus-one config"""
        price = self.app.calculate_guest_price("NonexistentCity", 2000)
        assert price == 2000

    def test_guest_price_perm_summer_2025(self):
        """Test guest price with actual PERM_SUMMER_2025 config"""
        # Uses the default PLUS_ONE_CONFIG
        price = self.app.calculate_guest_price(
            TargetCity.PERM_SUMMER_2025.value, 1300
        )
        # min_guest_price is 1500, registrant pays 1300 -> guest pays 1500
        assert price == 1500

    def test_guest_price_perm_summer_2025_expensive(self):
        """Test guest price when registrant price exceeds minimum"""
        price = self.app.calculate_guest_price(
            TargetCity.PERM_SUMMER_2025.value, 2200
        )
        # min_guest_price is 1500, registrant pays 2200 -> guest pays 2200
        assert price == 2200


class TestPlusOneConfig:
    """Tests for plus-one configuration"""

    def setup_method(self):
        mock_db = MagicMock()
        mock_db.get_collection.return_value = AsyncMock()
        self.db_patcher = patch("app.app.get_database", return_value=mock_db)
        self.db_patcher.start()

        self.app = App(
            telegram_bot_token="mock_token",
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

    def teardown_method(self):
        self.db_patcher.stop()

    def test_get_plus_one_config_enabled_city(self):
        """Test getting config for enabled city"""
        config = self.app.get_plus_one_config(TargetCity.PERM_SUMMER_2025.value)
        assert config["enabled"] is True
        assert config["max_guests"] == 2
        assert config["pricing_strategy"] == PlusOnePricingStrategy.SAME_WITH_MINIMUM
        assert config["min_guest_price"] == 1500

    def test_get_plus_one_config_unconfigured_city(self):
        """Test getting config for unconfigured city returns empty dict"""
        config = self.app.get_plus_one_config(TargetCity.MOSCOW.value)
        assert config == {}

    def test_get_plus_one_config_disabled_check(self):
        """Test that unconfigured cities have plus-one disabled"""
        config = self.app.get_plus_one_config(TargetCity.MOSCOW.value)
        assert config.get("enabled", False) is False


class TestSaveGuests:
    """Tests for saving guests to database"""

    def setup_method(self):
        self.mock_collection = AsyncMock()
        self.mock_event_logs = AsyncMock()

        mock_db = MagicMock()
        mock_db.get_collection = MagicMock()
        mock_db.get_collection.side_effect = lambda name: {
            "registered_users": self.mock_collection,
            "event_logs": self.mock_event_logs,
            "deleted_users": AsyncMock(),
        }.get(name, AsyncMock())

        self.db_patcher = patch("app.app.get_database", return_value=mock_db)
        self.db_patcher.start()

        self.app = App(
            telegram_bot_token="mock_token",
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

    def teardown_method(self):
        self.db_patcher.stop()

    @pytest.mark.asyncio
    async def test_save_guests(self):
        """Test saving guests to database"""
        guests = [
            GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500),
        ]

        await self.app.save_guests(123456, TargetCity.PERM_SUMMER_2025.value, guests)

        # Verify update_one was called with correct filter and data
        self.mock_collection.update_one.assert_called_once()
        call_args = self.mock_collection.update_one.call_args
        filter_arg = call_args[0][0]
        update_arg = call_args[0][1]

        assert filter_arg["user_id"] == 123456
        assert filter_arg["target_city"] == TargetCity.PERM_SUMMER_2025.value
        assert "$set" in update_arg
        assert len(update_arg["$set"]["guests"]) == 1
        assert update_arg["$set"]["guests"][0]["full_name"] == "Иванова Анна"

    @pytest.mark.asyncio
    async def test_save_multiple_guests(self):
        """Test saving multiple guests"""
        guests = [
            GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500),
            GuestInfo(full_name="Петров Петр", relationship="Друг/Подруга", payment_amount=1800),
        ]

        await self.app.save_guests(123456, TargetCity.PERM_SUMMER_2025.value, guests)

        call_args = self.mock_collection.update_one.call_args
        update_arg = call_args[0][1]
        assert len(update_arg["$set"]["guests"]) == 2

    @pytest.mark.asyncio
    async def test_save_guests_logs_event(self):
        """Test that saving guests creates an event log"""
        guests = [
            GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500),
        ]

        await self.app.save_guests(123456, TargetCity.PERM_SUMMER_2025.value, guests)

        # Verify event log was created
        self.mock_event_logs.insert_one.assert_called_once()
        log_entry = self.mock_event_logs.insert_one.call_args[0][0]
        assert log_entry["event_type"] == "guests_added"
        assert log_entry["data"]["guest_count"] == 1


class TestSaveRegisteredUserWithGuests:
    """Tests for saving registered user with guests"""

    def setup_method(self):
        self.mock_collection = AsyncMock()
        self.mock_event_logs = AsyncMock()

        mock_db = MagicMock()
        mock_db.get_collection = MagicMock()
        mock_db.get_collection.side_effect = lambda name: {
            "registered_users": self.mock_collection,
            "event_logs": self.mock_event_logs,
            "deleted_users": AsyncMock(),
        }.get(name, AsyncMock())

        self.db_patcher = patch("app.app.get_database", return_value=mock_db)
        self.db_patcher.start()

        self.app = App(
            telegram_bot_token="mock_token",
            payment_phone_number="1234567890",
            payment_name="Test User",
        )

    def teardown_method(self):
        self.db_patcher.stop()

    @pytest.mark.asyncio
    async def test_save_user_with_guests(self):
        """Test saving a user with guests persists the guests list"""
        guests = [
            GuestInfo(full_name="Иванова Анна", relationship="Супруг(а)", payment_amount=1500),
        ]
        user = RegisteredUser(
            full_name="Иванов Иван",
            graduation_year=2010,
            class_letter="А",
            target_city=TargetCity.PERM_SUMMER_2025,
            guests=guests,
        )

        # No existing registration
        self.mock_collection.find_one.return_value = None

        await self.app.save_registered_user(user, user_id=123456, username="test_user")

        # Verify insert_one was called
        self.mock_collection.insert_one.assert_called_once()
        inserted_data = self.mock_collection.insert_one.call_args[0][0]

        assert "guests" in inserted_data
        assert len(inserted_data["guests"]) == 1
        assert inserted_data["guests"][0]["full_name"] == "Иванова Анна"
        assert inserted_data["guests"][0]["payment_amount"] == 1500
