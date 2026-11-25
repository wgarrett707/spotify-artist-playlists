# Spotify Artist Playlists

Give it an artist. It builds a Spotify playlist of that artist's **top 30 songs by all-time Spotify streams**, using the rankings on [kworb.net](https://kworb.net/spotify/artists.html), in order.

## One-time setup

1. **Install the dependencies**
   ```
   pip install -r requirements.txt
   ```
2. **Add your API keys.** Open `.env` and paste in your app's **Client ID** and **Client Secret**. You'll find them at https://developer.spotify.com/dashboard → your app → Settings.
3. **Register the redirect URI.** In that same Settings page, add this under *Redirect URIs* and save:
   ```
   http://127.0.0.1:8888/callback
   ```
4. **Log in once:**
   ```
   python make_playlist.py --login
   ```
   A browser tab opens. Approve the request, and the login is saved to `.spotify_token.json`, which refreshes itself from then on.

> **Spotify's Development Mode rules (since Feb 2026):** the app owner needs Spotify Premium, and only users you add under *User Management* in the dashboard (5 max) can log in. Neither matters if the app is just for you.

## Usage

```
python make_playlist.py Taylor Swift
python make_playlist.py https://open.spotify.com/artist/06HL4z0CvFAxyc27GXpf02
python make_playlist.py Drake -n 50 --no-features
python make_playlist.py Kendrick Lamar --dry-run      # preview only, nothing is created
python make_playlist.py --file artists.txt             # batch: one artist per line
```

On Windows you can use the launcher instead: `playlist Taylor Swift`

| Flag | What it does |
|---|---|
| `-n 50` | Number of songs (default 30) |
| `--no-features` | Skip songs where the artist is only featured (marked `*` on Kworb) |
| `--public` | Make new playlists public (default: private) |
| `--new` | Always create a new playlist. By default, running the same artist again **refreshes** the existing "Artist: Top 30 (Kworb)" playlist in place |
| `--dry-run` | Print the list without changing anything. Works with no API keys if you pass an artist URL or ID |

**Picked the wrong artist?** A name search takes the exact-name match, or failing that the top result. If that's the wrong artist, paste the artist's Spotify link instead.

## How it works

```
artist name / link ──► Spotify search (artist ID) ──► kworb.net/spotify/artist/<id>_songs.html
                                                         │  scrape + sort by total streams, take top N
                                                         ▼
                                      swap each track to its original release (see below)
                                                         ▼
                                      POST /me/playlists  ──►  PUT /playlists/{id}/items (in order)
```

**Original versions.** Spotify gives every copy of a recording the same play count, so kworb's link sometimes points at a compilation or reissue copy, like "Sorry" on *Playlist for Gamers*. For each song, the tool looks up the recording's ISRC, searches for other copies of that exact recording, and picks the best release using this order of preference: not a compilation, credited to the playlist's artist, album over single, not an alternate edition ("Edited Version", "Live", etc.), then earliest. Each swap is printed. A `--dry-run` by artist name shows the swaps too.

| File | Role |
|---|---|
| `playlist_maker/kworb.py` | Fetches and parses the Kworb songs table |
| `playlist_maker/spotify.py` | Small Spotify client: OAuth login and token refresh, search, playlist create and replace |
| `playlist_maker/core.py` | `build_playlist()`: the whole workflow, with no CLI code, so a web app can reuse it |
| `playlist_maker/config.py` | Reads `.env` and environment variables |
| `make_playlist.py` | Command-line entry point |

## Hosting later (use from anywhere)

The code is already set up for this:
- `build_playlist()` in `core.py` is independent of the CLI, so a small web app (Flask or FastAPI) can call it from a form.
- On a server there's no browser to log in with, so set the `SPOTIFY_REFRESH_TOKEN` env var instead. Get your token with `python make_playlist.py --show-refresh-token`. The client then uses it to stay logged in as you.
- Settings come from env vars first, so Render, Railway, or Fly.io secrets work with no code changes.
