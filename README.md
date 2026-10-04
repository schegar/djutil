# DJUtil

A self-hosted, single-user Rekordbox 6/7 companion. A small agent on your DJ
machine (Windows or macOS) syncs your Rekordbox library and play history to a
server on your VPS and streams now-playing events — which drive set recording,
a live view with next-track suggestions, and track/transition analytics.

## Architecture

```
 Rekordbox (master.db)                Your VPS
 ┌──────────────────┐         ┌────────────────────────────┐
 │ djutil-agent     │  HTTPS  │ Caddy ──▶ app (FastAPI)    │
 │  read-only sync  ├────────▶│          SQLite (WAL)      │
 │  + live play WS  │◀─ ack ──│          + built PWA       │
 └──────────────────┘         └───────────▲────────────────┘
                                         │ session cookie
                                    Browser / PWA
```

- **Agent** — reads `master.db` strictly read-only (`PRAGMA query_only`),
  watches it with a filesystem watcher plus a fallback poll, uploads deltas and
  artwork, and forwards new history rows as live `play` events over a
  websocket (with a persistent outbox and a REST fallback). Runs as a CLI or a
  system-tray app that can start at login.
- **Server** — FastAPI + SQLite (WAL, alembic migrations), single container
  behind Caddy. Serves the built PWA, the sync API (agent token), and the live
  API (cookie session).
- **Web** — React PWA: Library, Live, Sets, History. Works on desktop and
  mobile; installable.

## Features

- **Library**: full-text search, filters for BPM/Camelot/genre/My Tags/
  playlists/rating/date added/play count/source, virtualized tables,
  shareable filter URLs and local saved presets.
- **Live**: agent connection status, now-playing card, session history,
  one-tap set recording (or automatic), top-20 compatible-track suggestions
  with reason badges.
- **Sets**: auto or manual recording, Rekordbox history import (bulk or per
  session, idempotent), timeline with transitions, per-transition favourite /
  1–5 rating / comments, entry deletion with re-bridging.
- **Analytics**: per-track transition stats in/out, app play counts, set
  membership, compatible-track lists.

## Server setup (VPS)

Requirements: a Linux VPS, Docker + Docker Compose, a DNS A record pointing
your domain at the VPS.

```bash
# 1. Clone (or pull just the deploy/ directory) and configure
git clone <repo> djutil && cd djutil/deploy
cp .env.example .env

# 2. Generate the admin password hash (runs inside the image)
docker compose run --rm app python -m djutil_server hash-password

# 3. Generate the agent token and session secret
openssl rand -hex 32   # DJUTIL_AGENT_TOKEN
openssl rand -hex 32   # DJUTIL_SESSION_SECRET

# 4. Fill in .env: DJUTIL_DOMAIN, DJUTIL_ADMIN_PASSWORD_HASH,
#    DJUTIL_AGENT_TOKEN, DJUTIL_SESSION_SECRET, DJUTIL_TZ
#    (e.g. Europe/Berlin — used for auto-generated set names).

# 5. Start
docker compose up -d
```

Caddy obtains and renews the HTTPS certificate automatically for
`DJUTIL_DOMAIN`. Open `https://<domain>` and log in.

To run a published image instead of building locally, keep the default
`image:` in `docker-compose.yml` (set `DJUTIL_IMAGE` to override) and just
`docker compose pull && docker compose up -d`. To build locally instead, use
`docker compose up -d --build`.

> **Quoting the password hash:** the argon2 hash contains `$`, which Compose
> interpolates in `env_file`/`.env`. Always paste it **single-quoted**:
> `DJUTIL_ADMIN_PASSWORD_HASH='$argon2id$v=19$...'`.

## Deploy behind an existing Traefik

If the VPS already runs Traefik, use `deploy/docker-compose.traefik.yml`
instead — it labels the app for Traefik (`websecure` entrypoint,
`myresolver` certresolver) and joins the external `traefik-net`. No Caddy is
deployed; WebSockets (`/api/live/ws`, `/api/agent/ws`) work through Traefik
with no extra configuration.

```bash
# 1. Get the code on the VPS
git clone <repo> djutil && cd djutil/deploy
#    (alternative: build locally and ship the image:
#     docker build -f deploy/Dockerfile -t djutil:local . &&
#     docker save djutil:local | ssh vps docker load)

# 2. Configure
cp .env.example .env
openssl rand -hex 32   # -> DJUTIL_AGENT_TOKEN
openssl rand -hex 32   # -> DJUTIL_SESSION_SECRET
#    set DJUTIL_DOMAIN (e.g. djutil.example.com) and DJUTIL_TZ

# 3. Admin password hash — wrap it in SINGLE quotes in .env
docker compose -f docker-compose.traefik.yml run --rm djutil \
  python -m djutil_server hash-password

# 4. The container runs as uid 10001 — prepare bind mounts
mkdir -p data backups && sudo chown -R 10001:10001 data backups
#    (if /data isn't writable, the app exits with a clear error naming this fix)

# 5. Build + start
docker compose -f docker-compose.traefik.yml up -d --build

# 6. Verify
curl https://<domain>/api/health
```

Then point the agent at it:

```bash
djutil-agent configure --server https://<domain> --token <DJUTIL_AGENT_TOKEN>
djutil-agent sync --full
djutil-agent tray    # or enable autostart
```

## Agent setup (DJ machine)

Download the release zip for your OS from **Releases**
(`djutil-agent-gui-*.zip` for the tray app, `djutil-agent-*.zip` for the CLI).

- **Windows**: the binary is unsigned — SmartScreen shows a warning; click
  **More info → Run anyway**.
- **macOS**: the app is unsigned — right-click → **Open** the first time.

Then:

```bash
djutil-agent configure --server https://djutil.example.com --token <DJUTIL_AGENT_TOKEN>
djutil-agent check        # verifies the Rekordbox DB can be opened
djutil-agent sync         # first one-shot library sync
```

Run the tray app (`DJUtil Agent` / `djutil-agent tray`) for continuous
operation: it watches the database, forwards plays, and exposes Sync now /
Full sync / Start–Stop recording / Open DJUtil / Start at login / logs &
config shortcuts from the menu. `djutil-agent autostart enable` registers it
at login (`autostart status` / `disable` to manage).

The agent log is a rotating file at
`<agent data dir>/logs/agent.log` (5 × 1 MB). Data dir:
`%LOCALAPPDATA%\DJUtil` on Windows, `~/Library/Application Support/DJUtil` on
macOS; override with `DJUTIL_AGENT_DATA_DIR`.

## Using it

- **Live** shows what Rekordbox reports while you play; with auto-record on
  (default) every contiguous session becomes a set named
  `Set YYYY-MM-DD HH:mm` in your `DJUTIL_TZ`.
- **Sets** lists recordings and imported Rekordbox history; **Import Rekordbox
  history** backfills everything (safe to repeat — already-imported and
  already-live-recorded sessions are skipped).
- **Suggestions** rank candidates by Camelot neighbourhood, BPM (incl.
  half/double-time), past transitions, genre and rating, and penalise
  recently played tracks.

## Backups

The `backup` compose service writes an online SQLite copy every 24 h into
`./backups` and keeps the newest 14 (`djutil-YYYYmmdd-HHMMSS.db`, each
verified with `PRAGMA integrity_check`). Manual run:

```bash
docker compose run --rm backup python -m djutil_server backup --dir /backups --keep 14
```

**Artwork is not part of the DB backup.** After a restore, the agent
re-uploads artwork automatically on the next sync (hashes are compared per
track). To restore: stop the app, replace `/data/djutil.db` with a backup
copy, start again.

## Troubleshooting

- **`RekordboxKeyError` / database key errors**: the agent derives the
  SQLCipher key via pyrekordbox. If a Rekordbox update breaks it, pass
  `--key` / `DJUTIL_RB_KEY`, or `--db-path` / `DJUTIL_RB_DB` for a non-default
  library location.
- **History rows appear late**: Rekordbox writes history rows to
  `master.db` in batches (typically when a track is unloaded, not when it
  starts playing). That latency is Rekordbox's, not the agent's.
- **Stale `options.json`**: if Rekordbox settings (e.g. the DB location)
  seem wrong, quit Rekordbox so it flushes `options.json`, then restart the
  agent.
- **Agent can't connect**: check `DJUTIL_SERVER`/token in `config.json`,
  look at `logs/agent.log`, and confirm the server is reachable
  (`curl https://<domain>/api/health`).

## Development

Monorepo, uv workspace + pnpm. Requires Python 3.12, uv, Node, pnpm.

```bash
uv sync --all-packages            # install the workspace

uv run ruff check .               # lint
uv run mypy shared agent server   # typecheck
uv run pytest -q                  # all Python tests

cd web
pnpm install
pnpm dev                          # dev server, proxies /api -> :8000
pnpm lint && pnpm typecheck
pnpm test                         # vitest
pnpm build                        # -> dist/
pnpm e2e                          # playwright (needs a built dist/)
pnpm gen:api                      # regenerate OpenAPI types
```

Server one-offs:

```bash
uv run python -m djutil_server hash-password
DJUTIL_DATA_DIR=./data DJUTIL_AGENT_TOKEN=... DJUTIL_ADMIN_PASSWORD_HASH=... \
  DJUTIL_SESSION_SECRET=... uv run python -m djutil_server serve --port 8000
uv run python -m djutil_server seed-demo --tracks 500
uv run python -m djutil_server backup --dir ./backups --keep 14
```

Agent packaging:

```bash
cd agent
uv run pyinstaller djutil-agent.spec --noconfirm --clean       # console CLI
uv run pyinstaller djutil-agent-gui.spec --noconfirm --clean   # windowed tray
```

Releases: tag `v*` → CI builds both binaries on Windows + macOS (arm64 &
x86_64), attaches zips to a GitHub Release, and pushes the Docker image to
GHCR.
