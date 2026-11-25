"""Scrape an artist's all-time top songs (by Spotify streams) from kworb.net."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

KWORB_SONGS_URL = "https://kworb.net/spotify/artist/{artist_id}_songs.html"
USER_AGENT = "kworb-playlist-maker/1.0 (personal playlist tool)"
_TRACK_RE = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]{22})")


class KworbError(RuntimeError):
    pass


@dataclass
class KworbSong:
    title: str
    track_id: str
    streams: int
    daily: int | None
    is_feature: bool  # Kworb marks songs where the artist is only featured with "*"

    @property
    def uri(self) -> str:
        return f"spotify:track:{self.track_id}"


def _to_int(text: str) -> int | None:
    digits = text.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def fetch_songs(artist_id: str, session: requests.Session | None = None) -> tuple[str, list[KworbSong]]:
    """Return (artist name as shown on Kworb, songs sorted by total streams desc)."""
    http = session or requests
    url = KWORB_SONGS_URL.format(artist_id=artist_id)
    resp = http.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if resp.status_code == 404:
        raise KworbError(f"Kworb has no page for this artist yet ({url}).")
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    artist_name = title_tag.get_text().split(" - Spotify")[0].strip() if title_tag else artist_id

    table = soup.select_one("table.addpos")
    if table is None:
        raise KworbError(f"Couldn't find the songs table on {url} (page layout may have changed).")

    songs: list[KworbSong] = []
    seen: set[str] = set()
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a", href=_TRACK_RE)
        if link is None:
            continue
        track_id = _TRACK_RE.search(link["href"]).group(1)
        streams = _to_int(cells[1].get_text())
        if track_id in seen or streams is None:
            continue
        seen.add(track_id)
        songs.append(
            KworbSong(
                title=link.get_text(strip=True),
                track_id=track_id,
                streams=streams,
                daily=_to_int(cells[2].get_text()) if len(cells) > 2 else None,
                is_feature=cells[0].get_text(strip=True).startswith("*"),
            )
        )

    if not songs:
        raise KworbError(f"No songs found on {url}.")
    songs.sort(key=lambda s: s.streams, reverse=True)
    return artist_name, songs


def top_songs(
    artist_id: str, count: int | None = 30, include_features: bool = True
) -> tuple[str, list[KworbSong]]:
    """Top `count` songs by total streams (count=None returns all of them)."""
    artist_name, songs = fetch_songs(artist_id)
    if not include_features:
        songs = [s for s in songs if not s.is_feature]
    return artist_name, songs[:count]
