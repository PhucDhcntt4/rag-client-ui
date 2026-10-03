from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_is_served_by_fastapi():
    with TestClient(app) as client:
        page = client.get("/")
        module = client.get("/js/app.js")
        stylesheet = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "RAG Client" in page.text
    assert module.status_code == 200
    assert stylesheet.status_code == 200


def test_rag_asset_proxy_returns_image_without_exposing_key():
    class FakeRagClient:
        async def get_asset(self, asset_id: int):
            assert asset_id == 8
            return b"\x89PNG\r\n\x1a\nimage-data", "image/png"

    with TestClient(app) as client:
        client.app.state.rag_client = FakeRagClient()
        response = client.get("/api/rag-assets/8")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"\x89PNG")
