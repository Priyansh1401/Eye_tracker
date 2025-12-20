import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app, Base, get_db

# Test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "WaW Eye Tracker Backend"}

def test_register_user():
    user_data = {
        "email": "test@example.com",
        "full_name": "Test User",
        "password": "testpass123",
        "consent": True
    }
    response = client.post("/auth/register", json=user_data)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == user_data["email"]
    assert data["full_name"] == user_data["full_name"]
    assert "id" in data

def test_register_duplicate_email():
    user_data = {
        "email": "test@example.com",
        "full_name": "Test User 2",
        "password": "testpass123",
        "consent": True
    }
    response = client.post("/auth/register", json=user_data)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]

def test_login():
    login_data = {
        "username": "test@example.com",
        "password": "testpass123"
    }
    response = client.post("/auth/token", data=login_data)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Store token for authenticated tests
    global test_token
    test_token = data["access_token"]

def test_login_invalid():
    login_data = {
        "username": "test@example.com",
        "password": "wrongpass"
    }
    response = client.post("/auth/token", data=login_data)
    assert response.status_code == 401

def test_get_me():
    headers = {"Authorization": f"Bearer {test_token}"}
    response = client.get("/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"

def test_create_blink_session():
    headers = {"Authorization": f"Bearer {test_token}"}
    session_data = {
        "started_at": "2024-01-01T10:00:00",
        "ended_at": "2024-01-01T10:30:00",
        "blink_count": 150,
        "avg_cpu": 25.5,
        "avg_memory_mb": 512.0
    }
    response = client.post("/blink-sessions", json=session_data, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["blink_count"] == 150
    assert data["avg_cpu"] == 25.5

def test_get_blink_sessions():
    headers = {"Authorization": f"Bearer {test_token}"}
    response = client.get("/me/blink-sessions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["blink_count"] == 150

def test_unauthorized_access():
    response = client.get("/me")
    assert response.status_code == 401

    response = client.get("/me/blink-sessions")
    assert response.status_code == 401

    response = client.post("/blink-sessions", json={})
    assert response.status_code == 401