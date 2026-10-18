import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_venue_registration.db")
os.environ.setdefault("ADMIN_TOKEN", "test-token")

import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield

@pytest.fixture
def client():
    return TestClient(app)

