import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'hub-page-item-test.db'}"
    return TestClient(create_app(database_url=database_url))


def test_manifest_pages_are_exposed_for_configuration(client: TestClient) -> None:
    response = client.get("/api/v1/page-config/lyra-narrative/pages")
    assert response.status_code == 200
    pages = response.json()
    assert [item["page_id"] for item in pages] == [
        "writing",
        "characters",
        "world",
        "reader",
    ]
    assert pages[0]["path"] == "/writing"


def test_page_item_configuration_is_persistent_and_audited(client: TestClient) -> None:
    update = client.patch(
        "/api/v1/page-config/lyra-narrative/pages/reader",
        json={
            "title": "Reader 审核",
            "navigation_order": 5,
            "hidden": True,
            "visible_roles": ["writer", "editor"],
        },
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["title"] == "Reader 审核"
    assert payload["hidden"] is True
    assert payload["visible_roles"] == ["editor", "writer"]

    pages = client.get("/api/v1/page-config/lyra-narrative/pages").json()
    reader = next(item for item in pages if item["page_id"] == "reader")
    assert reader["navigation_order"] == 5
    assert reader["hidden"] is True

    audit = client.get("/api/v1/audit/events").json()
    assert audit[0]["action"] == "page-item-config.updated"
    assert audit[0]["target_id"] == "lyra-narrative:reader"


def test_unknown_page_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/page-config/lyra-narrative/pages/missing",
        json={"hidden": True},
    )
    assert response.status_code == 404
