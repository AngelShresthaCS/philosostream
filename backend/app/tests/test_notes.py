import os
from dotenv import load_dotenv

import pytest 
from fastapi.testclient import TestClient

load_dotenv()
def test_root():
    res = client.get("/")
    get = res.json().get("message")
    assert res.status_code == 200
    assert get == "FastAPI + AsyncMongoClient is running. Try GET /ping-db"