import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")

from app.main import app

client = TestClient(app)


def test_root():
    res = client.get("/")
    message = res.json().get("message")
    print("passed")
    assert res.status_code == 200
    assert message == "FastAPI + AsyncMongoClient is running. Try GET /ping-db"