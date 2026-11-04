#!/usr/bin/env python3
import argparse
import base64
import getpass
import http.server
import json
import os
import secrets
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "user-read-currently-playing user-read-playback-state user-modify-playback-state"


def exchange_code(client_id, client_secret, code, redirect_uri):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def write_env(path, client_id, client_secret, refresh_token):
    content = (
        f'SPOTIFY_CLIENT_ID="{client_id}"\n'
        f'SPOTIFY_CLIENT_SECRET="{client_secret}"\n'
        f'SPOTIFY_REFRESH_TOKEN="{refresh_token}"\n'
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


class Handler(http.server.BaseHTTPRequestHandler):
    # Results are stored on the class: a new handler instance serves each request.
    code = None
    error = None
    done = False
    expected_state = None
    callback_path = "/callback"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path != Handler.callback_path:
            # Ignore stray requests (favicon, prefetch) and keep waiting.
            self.send_error(404)
            return
        Handler.done = True
        if query.get("state", [None])[0] != Handler.expected_state:
            Handler.error = "OAuth state did not match."
        elif "error" in query:
            Handler.error = query["error"][0]
        else:
            Handler.code = query.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Spotify authorization received</h1><p>You can return to SSH.</p>")

    def log_message(self, *_):
        return


def main():
    parser = argparse.ArgumentParser(description="Generate and save a Spotify refresh token.")
    parser.add_argument("--env-file", default="/etc/spotify-now-playing.env")
    # Spotify no longer accepts "localhost" redirect URIs; use a loopback IP.
    parser.add_argument("--redirect-uri", default="http://127.0.0.1:8888/callback")
    args = parser.parse_args()

    redirect = urllib.parse.urlparse(args.redirect_uri)
    if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--redirect-uri must be an http:// loopback URI, e.g. http://127.0.0.1:8888/callback")
    port = redirect.port or 80
    Handler.callback_path = redirect.path or "/"

    client_id = input("Spotify Client ID: ").strip()
    client_secret = getpass.getpass("Spotify Client Secret: ").strip()
    state = secrets.token_urlsafe(24)
    Handler.expected_state = state

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": args.redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
    )
    print("\nOpen this URL in your browser:\n")
    print(f"{AUTH_URL}?{params}\n")
    print(f"Waiting on {args.redirect_uri} ...")

    with socketserver.TCPServer(("127.0.0.1", port), Handler) as server:
        while not Handler.done:
            server.handle_request()

    if Handler.error or not Handler.code:
        print(f"Authorization failed: {Handler.error or 'missing code'}", file=sys.stderr)
        return 1

    try:
        token_payload = exchange_code(client_id, client_secret, Handler.code, args.redirect_uri)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"Token exchange failed: HTTP {exc.code} {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Token exchange failed: {exc.reason}", file=sys.stderr)
        return 1
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token:
        print("Spotify did not return a refresh token.", file=sys.stderr)
        return 1

    write_env(args.env_file, client_id, client_secret, refresh_token)
    print(f"Saved credentials to {args.env_file} with mode 600.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
