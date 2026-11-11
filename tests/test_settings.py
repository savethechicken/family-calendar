import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

CONFIG = """
server:
  host: 0.0.0.0
  port: 8080
display:
  title: "Test Family"
  timezone: UTC
  week_starts_on: monday
  refresh_seconds: 30
weather:
  enabled: false
calendars:
  - id: family
    name: Family
    color: "#5b8cff"
    source:
      type: demo
  - id: gcal
    name: Google
    color: "#33b679"
    source:
      type: google
      calendar_id: primary
      client_id: cid
      client_secret: secret
      refresh_token: refresh
"""

ICS_BODY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Family Calendar//Test//EN
BEGIN:VEVENT
UID:abc@example.com
DTSTART:{start}
DTEND:{end}
SUMMARY:Lunch with Sam
END:VEVENT
END:VCALENDAR
"""


def write_config(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def make_client(tmp_path: Path, text: str = CONFIG) -> TestClient:
    return TestClient(create_app(write_config(tmp_path, text)))


def test_settings_get_shape(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert payload["display"]["title"] == "Test Family"
    assert payload["display"]["timezone"] == "UTC"
    assert {calendar["id"] for calendar in payload["calendars"]} == {"family", "gcal"}
    google = next(calendar for calendar in payload["calendars"] if calendar["id"] == "gcal")
    assert google["editable"] is False
    assert "url" not in google["source"]
    assert "client_secret" not in google["source"]
    assert payload["server"]["admin_token_set"] is False
    assert "America/New_York" in payload["timezones"]


def test_settings_partial_update(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/settings", json={"display": {"title": "Renamed"}})
        assert response.status_code == 200
        assert response.json()["display"]["title"] == "Renamed"

        public = client.get("/api/config").json()
        assert public["display"]["title"] == "Renamed"


def test_settings_preserves_google_calendars(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        payload = {
            "calendars": [
                {
                    "name": "Added ICS",
                    "color": "#039be5",
                    "source": {
                        "type": "ics",
                        "url": "https://example.com/cal.ics",
                        "cache_ttl_seconds": 120,
                    },
                }
            ]
        }
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 200

        ids = {calendar["id"] for calendar in response.json()["calendars"]}
        assert "gcal" in ids
        assert any(calendar["name"] == "Added ICS" for calendar in response.json()["calendars"])

    raw = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "client_secret: secret" in raw
    assert "refresh_token: refresh" in raw


def test_settings_rejects_bad_color(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    original = path.read_text(encoding="utf-8")
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/settings",
            json={
                "calendars": [
                    {
                        "name": "Bad",
                        "color": "nope",
                        "source": {"type": "ics", "url": "https://example.com/x.ics"},
                    }
                ]
            },
        )
    assert response.status_code == 400
    assert path.read_text(encoding="utf-8") == original


def test_settings_rejects_bad_url(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/settings",
            json={
                "calendars": [
                    {
                        "name": "Bad",
                        "color": "#039be5",
                        "source": {"type": "ics", "url": "file:///etc/passwd"},
                    }
                ]
            },
        )
    assert response.status_code == 400
    assert "Calendar URL" in response.json()["detail"]


def test_settings_requires_admin_token(tmp_path: Path) -> None:
    token_config = CONFIG.replace("port: 8080", "port: 8080\n  admin_token: s3cret")
    with make_client(tmp_path, token_config) as client:
        assert client.get("/api/settings").status_code == 401
        assert client.get("/api/settings", headers={"X-Admin-Token": "wrong"}).status_code == 401

        ok = client.get("/api/settings", headers={"X-Admin-Token": "s3cret"})
        assert ok.status_code == 200

        assert client.put("/api/settings", json={"display": {"title": "X"}}).status_code == 401
        saved = client.put(
            "/api/settings",
            json={"display": {"title": "X"}},
            headers={"X-Admin-Token": "s3cret"},
        )
        assert saved.status_code == 200


def test_settings_rejects_cross_origin(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/settings",
            json={"display": {"title": "X"}},
            headers={"Origin": "http://evil.example"},
        )
    assert response.status_code == 403


def test_settings_backup_created(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/settings", json={"display": {"title": "Backed up"}})
    assert response.status_code == 200
    assert (tmp_path / "config.yaml.bak").exists()


def test_test_feed_local_server(tmp_path: Path) -> None:
    start = datetime.now(UTC) + timedelta(hours=2)
    end = start + timedelta(hours=1)
    ics = ICS_BODY.format(
        start=start.strftime("%Y%m%dT%H%M%SZ"),
        end=end.strftime("%Y%m%dT%H%M%SZ"),
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = ics.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cal.ics"
        with make_client(tmp_path) as client:
            response = client.post("/api/settings/test-feed", json={"url": url})
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["samples"][0]["title"] == "Lunch with Sam"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_test_feed_rejects_non_http(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/settings/test-feed", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400
    assert "Calendar URL" in response.json()["detail"]
