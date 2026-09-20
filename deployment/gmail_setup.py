"""Authorize Gmail read-only access for job-alert import, locally, once.

Run from the project root with the server stopped or running (either is fine):

    .venv\\Scripts\\python deployment\\gmail_setup.py

Prerequisites (Google Cloud console, once):
  1. Create a project, enable the Gmail API.
  2. OAuth consent screen: External, add your own Google account as a test user.
  3. Credentials -> Create OAuth client ID -> Desktop app. Download the JSON.
  4. Put its client_id / client_secret in .env as GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET,
     or pass the JSON path as the first argument to this script.

The script opens your browser, receives the authorization code on a temporary
localhost port, exchanges it for a refresh token and writes GMAIL_REFRESH_TOKEN
to .env. Nothing is printed except progress. Restart the server afterwards.
"""

import json
import re
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def env_values():
    values = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def write_env(updates):
    text = ENV.read_text() if ENV.exists() else ""
    for key, value in updates.items():
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
    ENV.write_text(text)


def main():
    values = env_values()
    client_id, client_secret = values.get("GMAIL_CLIENT_ID", ""), values.get("GMAIL_CLIENT_SECRET", "")
    if len(sys.argv) > 1:
        data = json.loads(Path(sys.argv[1]).read_text())
        inner = data.get("installed") or data.get("web") or {}
        client_id, client_secret = inner.get("client_id", ""), inner.get("client_secret", "")
        if client_id and client_secret:
            write_env({"GMAIL_CLIENT_ID": client_id, "GMAIL_CLIENT_SECRET": client_secret})
    if not client_id or not client_secret:
        raise SystemExit(
            "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env, or pass the downloaded client JSON path."
        )

    result = {}
    state = secrets.token_urlsafe(16)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. Close this tab and run the script again.")
                return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Career Pilot: Gmail authorized.</h2><p>You can close this tab and return to the terminal.</p>"
                if result["code"]
                else b"<h2>Authorization was declined.</h2>"
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    redirect = f"http://127.0.0.1:{port}/"
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    print("Opening your browser to authorize read-only Gmail access…")
    print("If it does not open, paste this address into a browser:\n" + url + "\n")
    webbrowser.open(url)
    thread.join(timeout=600)
    if not result.get("code"):
        raise SystemExit("No authorization code was received within 10 minutes. Run the script again.")

    r = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit("Google rejected the code exchange: " + r.text[:300])
    token = r.json().get("refresh_token")
    if not token:
        raise SystemExit(
            "Google returned no refresh token. Remove the app under myaccount.google.com/permissions and run again."
        )
    write_env({"GMAIL_REFRESH_TOKEN": token})
    check = httpx.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": "Bearer " + r.json()["access_token"]},
        timeout=30,
    )
    who = check.json().get("emailAddress", "your account") if check.status_code == 200 else "your account"
    print(f"Gmail authorized for {who}. GMAIL_REFRESH_TOKEN saved to .env.")
    print("Create a Gmail label named CareerPilot and a filter that applies it to job-alert emails.")
    print("Restart the Career Pilot server, then add the Gmail source in Job sources.")


if __name__ == "__main__":
    main()
