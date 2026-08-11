<p align="center">
  <img src="assets/logo.svg" width="256" alt="Logo">
</p>

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

**NOTE:** this repository is entirely created by Anthropic's **Claude** and prompts to the **Sonnet 5** model

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

## About `docker-compose.yml`

```yaml
services:
  hammerhead-fit-downloader:
    image: goatie999/hammerhead-fit-downloader:latest
    container_name: hammerhead-fit-downloader
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./watch:/data/dreeve/watch
      - ./hammerhead/state:/data/hammerhead/state
      - ./hammerhead/tokens:/data/hammerhead/tokens
```

- **`image`** — pulls the pre-built image from `goatie999`'s Docker Hub
  account rather than building on your machine, so running this doesn't
  require the source tree, Python, or a build toolchain — just Docker.
- **`container_name`** — a fixed, predictable name for `docker logs`,
  `docker exec`, etc., instead of Compose's auto-generated one.
- **`restart: unless-stopped`** — the connector comes back up after a reboot
  or a crash, but stays down if you deliberately `docker compose down` it.
- **`env_file: .env`** — loads your Hammerhead credentials and poll interval
  from `.env` (copied from `.env.example`); see "One-time setup" below.
- **`volumes`** — three bind mounts from host folders onto fixed paths
  inside the container (see "Persistent storage layout" above). Editing the
  left-hand side of each line is how you change *where on the host* these
  live; the right-hand (in-container) side should stay as-is.

## One-time setup

1. Register a Hammerhead API client to get a `client_id` / `client_secret`.
   Hammerhead's own guide walks through this:
   [Creating a Developer Account](https://support.hammerhead.io/hc/en-us/articles/43558376710683-Creating-a-Developer-Account).
   When asked for a redirect URI, use `http://localhost:8080/callback` — a
   placeholder page on your own machine that doesn't need to actually be
   running anything.
2. Copy `.env.example` to `.env` and fill in `HAMMERHEAD_CLIENT_ID` /
   `HAMMERHEAD_CLIENT_SECRET`.
3. Pull the image and run the interactive authorization once:

   ```bash
   docker compose pull
   docker compose run --rm hammerhead-fit-downloader setup http://localhost:8080/callback
   ```

   What happens:

   1. The terminal prints a long `https://api.hammerhead.io/...` URL. Copy
      the **whole thing** into your regular web browser.
   2. Log in to Hammerhead if asked, and approve access.
   3. Hammerhead redirects your browser to
      `http://localhost:8080/callback?code=SOMETHING&state=...`. Nothing is
      actually listening on port 8080, so the page itself will fail to load
      — that's expected. What you need is in the address bar: copy just the
      value after `code=` and before the next `&`.
   4. Back in the terminal, it's waiting with a prompt:
      `Paste the code query param from the redirect URL:` — paste that
      value and press Enter.

   This exchanges the code for an access/refresh token pair, saved to
   `/data/hammerhead/tokens/tokens.json` in the container (i.e.
   `./hammerhead/tokens/tokens.json` on the host). That file is your login
   for every future run — you won't need to repeat this step unless you
   delete it or revoke access.

## Running

```bash
docker compose up -d
```

The connector polls `GET /activities` every `HAMMERHEAD_POLL_INTERVAL`
(default 1800s / 30 minutes, chosen to keep load on Hammerhead's API low),
starting from the date of the last activity it synced, downloads any FIT
files it hasn't already synced, and writes them into the watch folder
(`/data/dreeve/watch` in the container, `./watch` on the host).

### Running as part of Dreeve's own `docker-compose.yml`

By default this ships as its own standalone stack. If instead you want it
managed alongside Dreeve itself — one `docker compose up` for the whole
system — add it as a service inside Dreeve's master `docker-compose.yml`
and join it to Dreeve's `dreeve-network`:

```yaml
services:
  hammerhead-fit-downloader:
    image: goatie999/hammerhead-fit-downloader:latest
    container_name: dreeve-hammerhead-connector
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./watch:/data/dreeve/watch
      - ./hammerhead/state:/data/hammerhead/state
      - ./hammerhead/tokens:/data/hammerhead/tokens
    networks:
      - dreeve-network
```

Point the `./watch` mount at whatever host path Dreeve's own service already
uses for its watch folder, so both containers see the same directory.

If as part of the one-time setup your token.json is in a different folder, establish the directory structure "<dreeve folder>/hammerhead/tokens" and copy the token.json to to here.

Add the 3 environment variables for the Hammerhead-FIT-Downloader into the Dreeve App's .env file

If the Dreeve App has already been running and you're adding Hammerhead Connector functionality to the Dreeve app, we need to '--force-recreate' the docker compose command for the new environment variables to be included 

```bash
docker compose up -d --force-recreate
```

Note that joining `dreeve-network` is about convenience (co-located
lifecycle, consistent DNS/service discovery with the rest of the stack), not
a functional requirement — this connector never talks to Dreeve directly,
only to the shared `watch/` folder, so it works identically whether it's on
that network or entirely standalone.

## Tests

```bash
uv run pytest
```
