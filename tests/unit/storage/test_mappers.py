"""Tests for safe run-history mapping."""

from retailflow.storage.mappers import sanitize_configuration


def test_configuration_snapshot_removes_nested_secrets_and_binary_content() -> None:
    snapshot = sanitize_configuration(
        {
            "currency": "EUR",
            "api_token": "do-not-store",
            "database_url": "postgresql://user:do-not-store@example.test/database",
            "nested": {
                "password": "do-not-store",
                "service_api_key": "do-not-store",
                "threshold": 7,
            },
            "logo": {"content": b"image bytes"},
        }
    )

    assert snapshot == {"currency": "EUR", "nested": {"threshold": 7}}
    assert "do-not-store" not in str(snapshot)
