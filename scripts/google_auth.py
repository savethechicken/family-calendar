#!/usr/bin/env python3
"""One-time helper: turn a Google Cloud OAuth client into a refresh token.

Usage:
    python scripts/google_auth.py path/to/client_secret.json

Create the client in Google Cloud Console:
  1. Create (or pick) a project.
  2. Enable the "Google Calendar API".
  3. OAuth consent screen -> External -> add yourself as a test user.
  4. Credentials -> Create credentials -> OAuth client ID -> Desktop app.
  5. Download the JSON and pass it to this script.

The script prints a refresh token; paste it into config.yaml (or .env).
It only ever asks for read-only calendar access.
"""

from __future__ import annotations

import argparse
import html
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _load_client(path: str) -> tuple[str, str]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    block = data.get("installed") or data.get("web") or data
    try:
        return block["client_id"], block["client_secret"]
    except KeyError as exc:
        raise SystemExit(
            "client_secret.json is missing client_id/client_secret. "
            "Download it from Google Cloud Console -> Credentials."
        ) from exc


def _exchange(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_secret", help="Path to client_secret.json")
    args = parser.parse_args()

    client_id, client_secret = _load_client(args.client_secret)
    state = secrets.token_urlsafe(24)
    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            if params.get("state", [""])[0] != state:
                self.send_error(400, "State mismatch")
                return
            if "error" in params:
                captured["error"] = params["error"][0]
            elif "code" in params:
                captured["code"] = params["code"][0]

            message = (
                "Google authorization failed: " + html.escape(captured.get("error", ""))
                if "error" in captured
                else "Calendar access granted. You can close this tab and return to the terminal."
            )
            body = f"<html><body style='font-family:sans-serif;padding:2rem'><h2>{message}</h2></body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:  # silence request logs
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    auth_query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{auth_query}"

    print("\nOpen this URL if your browser does not open automatically:\n")
    print(url)
    print()
    webbrowser.open(url)
    server.handle_request()

    if "code" not in captured:
        raise SystemExit(f"Authorization failed: {captured.get('error', 'no code returned')}")

    tokens = _exchange(captured["code"], client_id, client_secret, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Remove the app's access at "
            "https://myaccount.google.com/permissions and run this script again."
        )

    print("\nSuccess. Add these to config.yaml (or your .env):\n")
    print("GOOGLE_CLIENT_ID=" + client_id)
    print("GOOGLE_CLIENT_SECRET=" + client_secret)
    print("GOOGLE_REFRESH_TOKEN=" + refresh_token)
    print("\nSee config.example.yaml for the matching `type: google` block.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
