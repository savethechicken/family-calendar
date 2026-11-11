from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

CONFIG = """
display:
  title: "Test Family"
  timezone: UTC
  week_starts_on: monday
  refresh_seconds: 30
calendars:
  - id: family
    name: Family
    color: "#5b8cff"
    source:
      type: demo
"""

START = "2025-11-10T00:00:00Z"
END = "2025-11-17T00:00:00Z"


def make_client(tmp_path: Path) -> TestClient:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return TestClient(create_app(path))


def test_health(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["calendars"] == ["family"]


def test_public_config_hides_source_details(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        payload = client.get("/api/config").json()

    assert payload["display"]["title"] == "Test Family"
    assert payload["display"]["theme"] == "auto"
    assert payload["calendars"] == [
        {"id": "family", "name": "Family", "color": "#5b8cff"}
    ]
    assert "source" not in payload["calendars"][0]


def test_events_endpoint_returns_demo_events(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/events", params={"start": START, "end": END})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["events"]) > 0
    assert payload["errors"] == {}

    first = payload["events"][0]
    for key in ("id", "calendarId", "title", "start", "end", "allDay", "color"):
        assert key in first

    titles = {event["title"] for event in payload["events"]}
    assert "Work" in titles
    assert "Trash day" in titles


def test_events_endpoint_validates_range(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/events", params={"start": END, "end": START})
    assert response.status_code == 400


def test_events_endpoint_rejects_huge_range(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get(
            "/api/events",
            params={"start": "2025-01-01T00:00:00Z", "end": "2025-06-01T00:00:00Z"},
        )
    assert response.status_code == 400


def test_weather_disabled_by_default(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        payload = client.get("/api/weather").json()
    assert payload == {"enabled": False}
