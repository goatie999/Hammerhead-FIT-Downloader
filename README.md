# Hammerhead FIT Downloader

Pulls activity FIT files out of a rider's Hammerhead (Karoo) account and drops
them into [Dreeve](https://dreeve.app)'s watch folder.

## Acknowledgments

This project is inspired by, and owes its whole approach to,
[**dreeve-garmin-connector**](https://github.com/dreeveapp/dreeve-garmin-connector)
and the Dreeve developers and contributors behind it. Their connector — the
watch-folder handoff, the careful separation of "list activities" from
"download activity", the whole shape of a small, focused sync daemon — is
the pattern this project follows, just pointed at a different data source.
Credit and thanks to them for the original design and for building Dreeve
itself. This project is named differently on purpose, to avoid any
confusion with their work rather than to distance itself from it.

## Why this differs from the Garmin connector

Garmin has no public developer API for activity export, so Garmin connectors
authenticate by replaying the Garmin Connect **web login** (username +
password, session cookies). Hammerhead, by contrast, publishes a real OAuth2
API (see `openapi.yml`), so this connector authenticates the supported way:

| | Garmin connector | This connector |
|---|---|---|
| Auth | Scraped web session (username/password) | OAuth2 authorization-code + refresh_token |
| List activities | Undocumented Connect endpoints | `GET /activities` (paginated, `startDate` filter) |
| Download activity | Undocumented "original file" download, usually a zip | `GET /activities/{id}/file` → raw FIT |
| Incremental sync | Track last-seen activity locally | Same: local `sync_state.json` cursor, plus the API's own `startDate` filter |

Everything downstream — writing files into Dreeve's watch folder so it can
ingest them — is unchanged.

## Persistent storage layout

On the host (wherever `docker-compose.yml` lives), the connector expects:

```
.
├── watch/                 # FIT files land here; point Dreeve at this folder
└── hammerhead/
    ├── state/
    │   └── sync_state.json   # which activities are already downloaded
    └── tokens/
        └── tokens.json       # OAuth access/refresh tokens
```

`watch/` is deliberately a sibling of `hammerhead/`, not nested inside it —
Dreeve only needs read access to activity files, never to your Hammerhead
credentials. `state/` and `tokens/` are split so you can back up or restrict
permissions on the tokens independently of the sync cursor.

These in-container paths are **fixed, not environment-configurable** —
`/data/dreeve/watch`, `/data/hammerhead/state`, `/data/hammerhead/tokens`.
To change where they live *on the host*, edit the `volumes:` section of
`docker-compose.yml`; the paths on the right-hand side (inside the
container) should stay as they are.

## How downloads avoid racing Dreeve's watch

Dreeve scans the watch folder on its own schedule and imports whatever it
finds there — it has no way to know a file is still being written. So each
activity is downloaded to `<name>.part` first; only once that write has
fully completed does it get renamed to `<name>.fit`. A rename is atomic on
the same filesystem, so Dreeve only ever sees either no file, or a complete
one — never a partial download mid-write.

## Building and publishing the image

`docker-compose.yml` pulls a pre-built image rather than building on the
host, so end users never need the source tree or a build toolchain. Build
and push it yourself once (and again after any code change):

```bash
docker build -t YOUR_DOCKERHUB_USERNAME/hammerhead-fit-downloader:latest .
docker login
docker push YOUR_DOCKERHUB_USERNAME/hammerhead-fit-downloader:latest
```

Then update the `image:` line in `docker-compose.yml` (and anywhere else you
deploy it) to match. If your Docker Hub repo is private, run `docker login`
on the deployment host too, before `docker compose pull`/`up`.

## One-time setup

1. Register an API client with Hammerhead to get a `client_id` / `client_secret`.
2. Copy `.env.example` to `.env` and fill in `HAMMERHEAD_CLIENT_ID` /
   `HAMMERHEAD_CLIENT_SECRET`.
3. Run the interactive authorization once:

   ```bash
   docker compose run --rm hammerhead-fit-downloader setup http://localhost:8080/callback
   ```

   This opens Hammerhead's consent screen, then exchanges the returned
   `code` for an access/refresh token pair, saved to
   `/data/hammerhead/tokens/tokens.json` in the container (i.e.
   `./hammerhead/tokens/tokens.json` on the host).

## Running

```bash
docker compose up -d
```

The connector polls `GET /activities` every `HAMMERHEAD_POLL_INTERVAL`
(default 1800s / 30 minutes, chosen to keep load on Hammerhead's API low),
starting from the date of the last activity it synced, downloads any FIT
files it hasn't already synced, and writes them into the watch folder
(`/data/dreeve/watch` in the container, `./watch` on the host).

## Tests

```bash
uv run pytest
```
