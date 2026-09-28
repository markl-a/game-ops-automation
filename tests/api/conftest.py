import os
import uuid

import httpx
import pytest


@pytest.fixture(scope="session")
def api():
    """In-process mock by default; set API_BASE_URL to run the same contract against staging."""
    base = os.environ.get("API_BASE_URL")
    if base:
        with httpx.Client(base_url=base, timeout=10) as c:
            yield c
    else:
        from fastapi.testclient import TestClient
        from opsauto.mock_api import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def key():
    return "it-" + uuid.uuid4().hex


@pytest.fixture
def order():
    return "TEST-" + uuid.uuid4().hex[:16]
