"""Tests for user_interactions module."""

import asyncio



from app.user_interactions import (
    PendingRequest,
    UserInputManager,
    _build_keyboard,
)


class TestPendingRequest:
    def test_create(self):
        req = PendingRequest(question="test?", handler_id="h1")
        assert req.question == "test?"
        assert req.handler_id == "h1"
        assert req.response is None
        assert req.event is not None
        assert isinstance(req.event, asyncio.Event)
        assert req.choice_keys == []
        assert req.choices_dict == {}

    def test_create_with_choices(self):
        req = PendingRequest(
            question="pick",
            handler_id="h2",
            choice_keys=["a", "b"],
            choices_dict={"a": "Option A", "b": "Option B"},
        )
        assert req.choice_keys == ["a", "b"]
        assert req.choices_dict["a"] == "Option A"


class TestUserInputManager:
    def test_add_request(self):
        mgr = UserInputManager()
        req = mgr.add_request(123, "h1", "question?")
        assert req.question == "question?"
        assert req.handler_id == "h1"

    def test_get_request_by_handler_id(self):
        mgr = UserInputManager()
        mgr.add_request(123, "h1", "q1")
        mgr.add_request(123, "h2", "q2")
        req = mgr.get_request(123, handler_id="h2")
        assert req.question == "q2"

    def test_get_request_by_message_id(self):
        mgr = UserInputManager()
        req = mgr.add_request(123, "h1", "q1")
        req.sent_message_id = 999
        found = mgr.get_request(123, message_id=999)
        assert found is req

    def test_get_request_latest(self):
        mgr = UserInputManager()
        mgr.add_request(123, "h1", "old")
        req2 = mgr.add_request(123, "h2", "new")
        found = mgr.get_request(123)
        assert found is req2

    def test_get_request_missing(self):
        mgr = UserInputManager()
        assert mgr.get_request(999) is None

    def test_remove_request(self):
        mgr = UserInputManager()
        mgr.add_request(123, "h1", "q")
        mgr.remove_request(123, "h1")
        assert mgr.get_request(123) is None

    def test_remove_nonexistent(self):
        mgr = UserInputManager()
        mgr.remove_request(123, "h1")  # should not raise

    def test_add_request_with_choices(self):
        mgr = UserInputManager()
        req = mgr.add_request(
            123,
            "h1",
            "pick one",
            choice_keys=["a"],
            choices_dict={"a": "A"},
        )
        assert req.choice_keys == ["a"]


class TestBuildKeyboard:
    def test_single_column(self):
        choices = {"yes": "Yes", "no": "No"}
        kb = _build_keyboard(choices, None, False, 1)
        assert len(kb.inline_keyboard) == 2
        assert kb.inline_keyboard[0][0].text == "Yes"
        assert kb.inline_keyboard[0][0].callback_data == "choice_yes"

    def test_two_columns(self):
        choices = {"a": "A", "b": "B", "c": "C"}
        kb = _build_keyboard(choices, None, False, 2)
        assert len(kb.inline_keyboard) == 2  # [A,B] and [C]
        assert len(kb.inline_keyboard[0]) == 2
        assert len(kb.inline_keyboard[1]) == 1

    def test_highlight_default(self):
        choices = {"yes": "Yes", "no": "No"}
        kb = _build_keyboard(choices, "yes", True, 1)
        assert kb.inline_keyboard[0][0].text.startswith("⭐")

    def test_no_highlight(self):
        choices = {"yes": "Yes", "no": "No"}
        kb = _build_keyboard(choices, "yes", False, 1)
        assert kb.inline_keyboard[0][0].text == "Yes"
