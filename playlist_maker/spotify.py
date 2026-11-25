"""Minimal Spotify Web API client (Authorization Code flow with refresh tokens).

Uses the post-February-2026 endpoints: POST /me/playlists and /playlists/{id}/items.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"

_ARTIST_ID_RE = re.compile(r"artist[/:]([A-Za-z0-9]{22})$")


class SpotifyError(RuntimeError):
    pass


def parse_artist_id(text: str) -> str | None:
    """Extract an artist ID from a Spotify URL, URI, or bare ID. Returns None for plain names."""
    text = text.strip().split("?")[0].rstrip("/")
    if re.fullmatch(r"[A-Za-z0-9]{22}", text):
        return text
    if "spotify" in text:
        m = _ARTIST_ID_RE.search(text)
        return m.group(1) if m else None
    return None


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_path: Path | None = None,
        refresh_token: str | None = None,
        interactive: bool = True,
    ):
        if not client_id or not client_secret:
            raise SpotifyError(
                "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET. Put them in the .env file."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_path = token_path
        self.interactive = interactive
        self.session = requests.Session()
        self._token: dict | None = None
        self._me: dict | None = None

        if token_path and token_path.exists():
            self._token = json.loads(token_path.read_text())
        elif refresh_token:
            self._token = {"refresh_token": refresh_token, "expires_at": 0}

    # ---------- auth ----------

    def _save_token(self) -> None:
        if self.token_path and self._token:
            self.token_path.write_text(json.dumps(self._token, indent=2))

    def _token_request(self, data: dict) -> None:
        resp = requests.post(TOKEN_URL, data=data, auth=(self.client_id, self.client_secret), timeout=20)
        if resp.status_code != 200:
            raise SpotifyError(f"Token request failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        old_refresh = (self._token or {}).get("refresh_token")
        self._token = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", old_refresh),
            "expires_at": time.time() + payload.get("expires_in", 3600),
        }
        self._save_token()

    def login(self) -> None:
        """Open the browser for Spotify login and catch the redirect on a local server."""
        if not self.interactive:
            raise SpotifyError("Not logged in and interactive login is disabled (set SPOTIFY_REFRESH_TOKEN).")
        redirect = urlparse(self.redirect_uri)
        if redirect.hostname not in ("127.0.0.1", "localhost", "[::1]"):
            raise SpotifyError("Interactive login needs a loopback redirect URI like http://127.0.0.1:8888/callback")

        state = secrets.token_urlsafe(16)
        result: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != redirect.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                result.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
                ok = "code" in result and result.get("state") == state
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "Logged in. You can close this tab." if ok else "Login failed. Check the terminal."
                self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

            def log_message(self, *args):
                pass

        url = AUTH_URL + "?" + urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "state": state,
            }
        )
        server = HTTPServer((redirect.hostname.strip("[]"), redirect.port or 80), Handler)
        server.timeout = 1
        print("Opening Spotify login in your browser...")
        print(f"If it doesn't open, visit:\n  {url}\n")
        webbrowser.open(url)
        deadline = time.time() + 300
        try:
            while not result and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()

        if "error" in result:
            raise SpotifyError(f"Spotify login error: {result['error']}")
        if result.get("state") != state or "code" not in result:
            raise SpotifyError("Login timed out or returned an invalid response.")
        self._token_request(
            {"grant_type": "authorization_code", "code": result["code"], "redirect_uri": self.redirect_uri}
        )
        print("Spotify login saved.\n")

    def _access_token(self) -> str:
        if not self._token:
            self.login()
        if not self._token.get("access_token") or self._token["expires_at"] - 60 < time.time():
            self._token_request({"grant_type": "refresh_token", "refresh_token": self._token["refresh_token"]})
        return self._token["access_token"]

    @property
    def refresh_token(self) -> str | None:
        return (self._token or {}).get("refresh_token")

    # ---------- HTTP ----------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith("http") else API_BASE + path
        for attempt in range(4):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            resp = self.session.request(method, url, headers=headers, timeout=20, **kwargs)
            if resp.status_code == 401 and attempt == 0:
                self._token["expires_at"] = 0  # force refresh, retry once
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", "2")) + 1)
                continue
            if resp.status_code >= 400:
                raise SpotifyError(f"{method} {path} failed ({resp.status_code}): {resp.text}")
            return resp.json() if resp.content else {}
        raise SpotifyError(f"{method} {path} failed after retries.")

    # ---------- API ----------

    def me(self) -> dict:
        if self._me is None:
            self._me = self._request("GET", "/me")
        return self._me

    def get_artist(self, artist_id: str) -> dict:
        return self._request("GET", f"/artists/{artist_id}")

    def get_track(self, track_id: str) -> dict:
        return self._request("GET", f"/tracks/{track_id}")

    def search_tracks(self, query: str, limit: int = 10, offset: int = 0) -> list[dict]:
        data = self._request(
            "GET", "/search", params={"q": query, "type": "track", "limit": limit, "offset": offset}
        )
        return data.get("tracks", {}).get("items", [])

    def search_artists(self, query: str, limit: int = 5) -> list[dict]:
        data = self._request("GET", "/search", params={"q": query, "type": "artist", "limit": limit})
        return data.get("artists", {}).get("items", [])

    def resolve_artist(self, query: str) -> dict:
        """Accept a Spotify artist URL/URI/ID or a name. Returns {'id', 'name'}."""
        artist_id = parse_artist_id(query)
        if artist_id:
            a = self.get_artist(artist_id)
            return {"id": a["id"], "name": a["name"]}
        results = self.search_artists(query)
        if not results:
            raise SpotifyError(f"No Spotify artist found for '{query}'.")
        exact = [a for a in results if a["name"].casefold() == query.strip().casefold()]
        pick = exact[0] if exact else results[0]
        return {"id": pick["id"], "name": pick["name"]}

    def find_own_playlist(self, name: str) -> dict | None:
        my_id = self.me()["id"]
        url = "/me/playlists?limit=50"
        while url:
            page = self._request("GET", url)
            for pl in page.get("items", []):
                if pl and pl.get("name") == name and pl.get("owner", {}).get("id") == my_id:
                    return pl
            url = page.get("next")
        return None

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict:
        return self._request(
            "POST", "/me/playlists", json={"name": name, "description": description, "public": public}
        )

    def update_playlist_details(self, playlist_id: str, description: str) -> None:
        self._request("PUT", f"/playlists/{playlist_id}", json={"description": description})

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        """Replace all items in the playlist with `uris`, preserving order."""
        first, rest = uris[:100], uris[100:]
        self._request("PUT", f"/playlists/{playlist_id}/items", json={"uris": first})
        for i in range(0, len(rest), 100):
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": rest[i : i + 100]})
