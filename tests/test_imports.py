import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("PAYMENT_PHONE_NUMBER", "test_number")
    monkeypatch.setenv("PAYMENT_NAME", "test_name")


def test_imports():
    from app.bot import main, dp

    assert main
    assert dp
