import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.main import app
from app.backend.database.connection import get_db
from app.backend.database.models import Base


# Create an in-memory SQLite database that persists across sessions during a test
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def prepare_database():
    """Ensure a clean database for every test."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_create_and_fetch_borsdata_api_key(client: TestClient):
    payload = {
        "provider": "BORSDATA_API_KEY",
        "key_value": "demo-key",
        "description": "Primary Börsdata credential",
        "is_active": True,
    }

    create_response = client.post("/api-keys", json=payload)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["provider"] == payload["provider"]
    assert created["key_value"] == payload["key_value"]
    assert created["is_active"] is True

    fetch_response = client.get(f"/api-keys/{payload['provider']}")
    assert fetch_response.status_code == 200
    fetched = fetch_response.json()
    assert fetched["provider"] == payload["provider"]
    assert fetched["key_value"] == payload["key_value"]


def test_list_api_keys_without_trailing_slash(client: TestClient):
    client.post(
        "/api-keys",
        json={
            "provider": "BORSDATA_API_KEY",
            "key_value": "demo-key",
            "is_active": True,
        },
    )

    list_response = client.get("/api-keys")
    assert list_response.status_code == 200
    data = list_response.json()
    assert len(data) == 1
    assert data[0]["provider"] == "BORSDATA_API_KEY"


def test_delete_api_key(client: TestClient):
    provider = "BORSDATA_API_KEY"
    client.post(
        "/api-keys",
        json={
            "provider": provider,
            "key_value": "demo-key",
            "is_active": True,
        },
    )

    delete_response = client.delete(f"/api-keys/{provider}")
    assert delete_response.status_code in {200, 204}

    # Verify key no longer exists
    list_response = client.get("/api-keys")
    assert list_response.status_code == 200
    assert list_response.json() == []

    get_response = client.get(f"/api-keys/{provider}")
    assert get_response.status_code == 404
