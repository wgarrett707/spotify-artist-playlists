"""Make a Spotify playlist of an artist's top songs (all-time streams, per kworb.net).

Examples:
  python make_playlist.py Taylor Swift
  python make_playlist.py "https://open.spotify.com/artist/06HL4z0CvFAxyc27GXpf02"
  python make_playlist.py Drake -n 50 --no-features  python make_playlist.py --file artists.txt
  python make_playlist.py Kendrick Lamar --dry-run
"""

from __future__ import annotations

import argparse
import sys

from playlist_maker.config import TOKEN_FILE, get_settings
from playlist_maker.core import build_playlist
from playlist_maker.kworb import KworbError
from playlist_maker.spotify import SpotifyClient, SpotifyError, parse_artist_id


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    p = argparse.ArgumentParser(description="Artist -> Spotify playlist of their Kworb top songs.")
    p.add_argument("artist", nargs="*", help="Artist name, or Spotify artist URL/URI/ID")
    p.add_argument("-n", "--count", type=int, default=30, help="Number of songs (default 30)")
    p.add_argument("--no-features", action="store_true", help="Skip songs where the artist is only featured")
    p.add_argument("--public", action="store_true", help="Make new playlists public (default private)")
    p.add_argument("--new", action="store_true", help="Always create a new playlist instead of refreshing an existing one")
    p.add_argument("--dry-run", action="store_true", help="Show the song list without touching Spotify playlists")
    p.add_argument("-f", "--file", help="Text file with one artist per line (batch mode)")
    p.add_argument("--login", action="store_true", help="(Re)log in to Spotify and exit")
    p.add_argument("--show-refresh-token", action="store_true", help="Print your refresh token (for hosting later)")
    args = p.parse_args()

    artists: list[str] = []
    if args.artist:
        artists.append(" ".join(args.artist))
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            artists += [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]

    settings = get_settings()
    needs_spotify = args.login or args.show_refresh_token or not (
        args.dry_run and artists and all(parse_artist_id(a) for a in artists)
    )
    client = None
    if needs_spotify:
        try:
            client = SpotifyClient(
                settings["client_id"],
                settings["client_secret"],
                settings["redirect_uri"],
                token_path=TOKEN_FILE,
                refresh_token=settings["refresh_token"],
            )
        except SpotifyError as e:
            print(f"Error: {e}")
            return 1

    if args.login:
        client.login()
        print(f"Logged in as {client.me().get('display_name') or client.me()['id']}.")
        return 0
    if args.show_refresh_token:
        client.me()  # make sure we're logged in
        print(client.refresh_token)
        return 0
    if not artists:
        p.print_help()
        return 1

    failures = 0
    for query in artists:
        print(f"\n=== {query} ===")
        try:
            result = build_playlist(
                client,
                query,
                count=args.count,
                include_features=not args.no_features,
                public=args.public,
                reuse_existing=not args.new,
                dry_run=args.dry_run,
            )
        except (SpotifyError, KworbError) as e:
            print(f"Error: {e}")
            failures += 1
            continue

        for i, s in enumerate(result.songs, 1):
            feat = "  (feat.)" if s.is_feature else ""
            print(f"{i:>3}. {s.title}{feat}  -  {s.streams:,}")
        if args.dry_run:
            print(f"\n[dry run] Would create/refresh: {result.playlist_name}")
        else:
            verb = "Created" if result.created else "Refreshed"
            print(f"\n{verb}: {result.playlist_name}\n  {result.playlist_url}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
