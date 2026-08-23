from fastapi.testclient import TestClient

from motorcad_studio.main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["templates"] >= 30


def test_templates():
    response = client.get("/api/templates")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert "e14_eMobility_AFM" in ids
