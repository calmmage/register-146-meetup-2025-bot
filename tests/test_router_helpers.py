"""Tests for router helper functions."""

from app.app import GraduateType
from app.router import get_event_date_display, get_event_city, is_event_free


class TestGetEventDateDisplay:
    def test_with_date(self):
        event = {"date_display": "21 Марта, Сб"}
        assert get_event_date_display(event) == "21 Марта, Сб"

    def test_without_date(self):
        event = {}
        assert get_event_date_display(event) == "дата неизвестна"

    def test_none_event(self):
        assert get_event_date_display(None) == "дата неизвестна"


class TestGetEventCity:
    def test_with_city(self):
        event = {"city": "Москва"}
        assert get_event_city(event) == "Москва"

    def test_without_city(self):
        assert get_event_city({}) == ""

    def test_none_event(self):
        assert get_event_city(None) == ""


class TestIsEventFree:
    def test_free_pricing(self):
        event = {"pricing_type": "free"}
        assert is_event_free(event) is True

    def test_formula_not_free(self):
        event = {"pricing_type": "formula"}
        assert is_event_free(event) is False

    def test_free_for_teacher(self):
        event = {"pricing_type": "formula", "free_for_types": ["TEACHER"]}
        assert is_event_free(event, "TEACHER") is True

    def test_not_free_for_graduate(self):
        event = {"pricing_type": "formula", "free_for_types": ["TEACHER"]}
        assert is_event_free(event, GraduateType.GRADUATE.value) is False

    def test_none_event(self):
        assert is_event_free(None) is False
