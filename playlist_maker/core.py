"""The main workflow: artist -> Kworb top N -> Spotify playlist (in order).

Kept separate from the CLI so a future web app can call build_playlist() directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable

from . import kworb
from .spotify import SpotifyClient, SpotifyError, parse_artist_id


@dataclass
class PlaylistResult:
    artist_name: str
    playlist_name: str
    playlist_url: str | None
    created: bool  # False = existing playlist was refreshed
    songs: list[kworb.KworbSong] = field(default_factory=list)


def playlist_name_for(artist_name: str, count: int) -> str:
    return f"{artist_name}: Top {count} (Kworb)"


_ALT_EDITION_RE = re.compile(r"\b(version|live|karaoke|instrumental|sped up|slowed|acoustic)\b", re.I)


def _release_rank(track: dict, artist_id: str) -> tuple:
    """Sort key (lower is better): not a compilation, released under the playlist's artist,
    album before single, not an alternate edition, then earliest (originals beat reissues)."""
    album = track.get("album", {})
    album_artists = album.get("artists", [])
    various = any(a.get("name") == "Various Artists" for a in album_artists)
    is_comp = album.get("album_type") == "compilation" or various
    not_theirs = all(a.get("id") != artist_id for a in album_artists)
    type_rank = {"album": 0, "single": 1}.get(album.get("album_type"), 2)
    alt_edition = bool(_ALT_EDITION_RE.search(album.get("name", "")))
    return (is_comp, not_theirs, type_rank, alt_edition, album.get("release_date") or "9999")


def _original_version(
    client: SpotifyClient, song: kworb.KworbSong, artist_id: str
) -> tuple[kworb.KworbSong, dict, dict]:
    """Kworb sometimes links a compilation/reissue copy of a recording. Spotify shares play counts
    across every copy with the same ISRC, so find the original release of that exact recording.
    Returns (song with the chosen track_id, kworb's track, chosen track)."""
    linked = client.get_track(song.track_id)
    isrc = linked.get("external_ids", {}).get("isrc")
    if not isrc:
        return song, linked, linked

    title = re.split(r" \(| - ", linked["name"])[0].replace('"', "")
    query = f'track:"{title}" artist:"{linked["artists"][0]["name"]}"'
    rank = lambda t: _release_rank(t, artist_id)  # noqa: E731
    candidates = [linked]
    for offset in (0, 10):  # hits sit on dozens of compilations; the original may be on page 2
        results = client.search_tracks(query, limit=10, offset=offset)
        candidates += [t for t in results if t.get("external_ids", {}).get("isrc") == isrc]
        if not rank(min(candidates, key=rank))[0] or len(results) < 10:
            break
    best = min(candidates, key=rank)
    return replace(song, track_id=best["id"]), linked, best


def _use_original_versions(
    client: SpotifyClient,
    songs: list[kworb.KworbSong],
    artist_id: str,
    count: int,
    log: Callable[[str], None],
) -> list[kworb.KworbSong]:
    """Swap each song to its original release, dropping repeats of a recording already picked
    (Kworb sometimes lists two copies of one recording), until `count` songs are collected."""
    out: list[kworb.KworbSong] = []
    seen: dict[str, int] = {}  # ISRC (or track ID) -> position in `out`
    for song in songs:
        if len(out) >= count:
            break
        try:
            fixed, linked, best = _original_version(client, song, artist_id)
        except SpotifyError as e:
            log(f"  (couldn't check versions of '{song.title}': {e})")
            fixed, key = song, song.track_id
        else:
            key = best.get("external_ids", {}).get("isrc") or best["id"]
            if key in seen:
                log(f"  Skipped '{song.title}': same recording as #{seen[key] + 1}")
                continue
            if best["id"] != linked["id"]:
                log(f"  Swapped '{song.title}': {linked['album']['name']} -> {best['album']['name']}")
        seen[key] = len(out)
        out.append(fixed)
    return out


def build_playlist(
    client: SpotifyClient | None,
    artist_query: str,
    count: int = 30,
    include_features: bool = True,
    public: bool = False,
    reuse_existing: bool = True,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> PlaylistResult:
    direct_id = parse_artist_id(artist_query)
    if client is None and dry_run and direct_id:
        # Preview without Spotify credentials: Kworb only needs the artist ID.
        kworb_name, songs = kworb.top_songs(direct_id, count=None, include_features=include_features)
        artist = {"id": direct_id, "name": kworb_name}
    else:
        if client is None:
            raise ValueError("A Spotify client is required unless previewing (--dry-run) by artist URL/ID.")
        artist = client.resolve_artist(artist_query)
        _, songs = kworb.top_songs(artist["id"], count=None, include_features=include_features)
    log(f"Artist: {artist['name']}  (https://open.spotify.com/artist/{artist['id']})")

    name = playlist_name_for(artist["name"], count)
    if client is not None:
        log("Checking for original versions...")
        songs = _use_original_versions(client, songs, artist["id"], count, log)
    else:
        songs = songs[:count]
    if len(songs) < count:
        log(f"Note: only {len(songs)} songs available for this artist.")

    if dry_run:
        return PlaylistResult(artist["name"], name, None, created=False, songs=songs)

    description = (
        f"{artist['name']}'s top {len(songs)} songs by all-time Spotify streams, "
        f"ranked by kworb.net. Updated {date.today().isoformat()}."
    )

    existing = client.find_own_playlist(name) if reuse_existing else None
    if existing:
        playlist = existing
        client.update_playlist_details(playlist["id"], description)
        created = False
    else:
        playlist = client.create_playlist(name, description, public=public)
        created = True

    client.replace_items(playlist["id"], [s.uri for s in songs])
    return PlaylistResult(
        artist_name=artist["name"],
        playlist_name=name,
        playlist_url=playlist.get("external_urls", {}).get("spotify"),
        created=created,
        songs=songs,
    )
