#!/usr/bin/env python3
"""
Hammerhead FIT Downloader

Two subcommands:

  auth   Interactive one-time authorization. Opens a browser, catches the
         OAuth redirect, and saves a refresh token to --token-cache.
         Run this LOCALLY (not in the container) since it needs a browser.

  run    Headless daemon. Designed to run forever inside the Docker
         container:

         1. FIRST RUN (no state file yet): backfills your entire activity
            history in batches, pausing BATCH_INTERVAL_MINUTES between
            each batch, so the API isn't hit all at once.
         2. STEADY STATE (backfill complete): every BATCH_INTERVAL_MINUTES,
            fetches only activities newer than the last one it recorded
            (by that activity's createdAt date) and downloads their FIT
            files.

         Batch size and interval are configurable via environment
         variables (see below), and the run state (last recorded activity
         date, backfill progress) is persisted to --state-file so a
         container restart resumes where it left off instead of starting
         over.

Environment variables:
    HAMMERHEAD_CLIENT_ID          (required)
    HAMMERHEAD_CLIENT_SECRET      (required)
    HAMMERHEAD_BATCH_SIZE         activities fetched per batch (default 50)
    HAMMERHEAD_INTERVAL_MINUTES   minutes between batches, both during
                                   backfill and steady-state (default 30)

Typical flow:
    # once, on your laptop:
    python hammerhead_fit_downloader.py auth --token-cache ./data/token.json

    # copy ./data/token.json into the volume the container will use, then:
    python hammerhead_fit_downloader.py run \
        --token-cache /data/token.json \
        --state-file /data/state.json \
        --out /data/fit_files
"""

import argparse
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests

AUTH_BASE = "https://api.hammerhead.io/v1/auth"
API_BASE = "https://api.hammerhead.io/v1/api"
AUTHORIZE_URL = f"{AUTH_BASE}/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"

DEFAULT_REDIRECT_URI = "http://localhost:8420/callback"
DEFAULT_SCOPE = "activity:read"

DEFAULT_BATCH_SIZE = 50
DEFAULT_INTERVAL_MINUTES = 30


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result["code"] = params.get("code", [None])[0]
        _CallbackHandler.result["state"] = params.get("state", [None])[0]
        _CallbackHandler.result["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = b"<h1>Authorization denied.</h1>" if _CallbackHandler.result["error"] \
            else b"<h1>Authorized. You can close this tab.</h1>"
        self.wfile.write(msg)

    def log_message(self, format, *args):
        pass


def _wait_for_authorization_code(redirect_uri: str, expected_state: str, timeout: int = 300) -> str:
    port = urllib.parse.urlparse(redirect_uri).port or 80
    _CallbackHandler.result = {}
    server = http.server.HTTPServer(("localhost", port), _CallbackHandler)
    t = threading.Thread(target=server.handle_request)
    t.start()
    t.join(timeout=timeout)

    if not _CallbackHandler.result:
        raise TimeoutError("Timed out waiting for the OAuth redirect callback.")
    if _CallbackHandler.result.get("error"):
        raise RuntimeError(f"Authorization denied: {_CallbackHandler.result['error']}")
    if _CallbackHandler.result.get("state") != expected_state:
        raise RuntimeError("State mismatch on OAuth callback -- possible CSRF, aborting.")
    code = _CallbackHandler.result.get("code")
    if not code:
        raise RuntimeError("No authorization code received in callback.")
    return code


class TokenManager:
    def __init__(self, client_id: str, client_secret: str, token_cache: Path,
                 redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.token_cache = token_cache

        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: float = 0.0

    def _post_token_request(self, payload: dict) -> dict:
        resp = requests.post(
            TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()

    def _store(self, data: dict):
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.expires_at = time.time() + data.get("expires_in", 0) - 30
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache.write_text(json.dumps({"refresh_token": self.refresh_token}))
        try:
            self.token_cache.chmod(0o600)
        except OSError:
            pass

    def interactive_authorize(self):
        """Run once, locally, where a browser is available."""
        state = os.urandom(16).hex()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "state": state,
        }
        url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
        print("Opening browser to authorize this app with your Hammerhead account...")
        print(f"If it doesn't open automatically, visit:\n  {url}\n")
        webbrowser.open(url)

        code = _wait_for_authorization_code(self.redirect_uri, state)
        data = self._post_token_request({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        })
        self._store(data)
        print(f"Authorized. Refresh token saved to {self.token_cache}")

    def ensure_token_headless(self):
        """For use in the container: only ever refreshes a cached token.
        Never opens a browser. Fails loudly if there's nothing to refresh."""
        if self.access_token and time.time() < self.expires_at:
            return

        if not self.token_cache.exists():
            raise RuntimeError(
                f"No token cache found at {self.token_cache}. Run the interactive "
                "'auth' subcommand locally first (it needs a browser), then copy "
                "the resulting file into the volume this container reads from."
            )

        cached_refresh = json.loads(self.token_cache.read_text()).get("refresh_token")
        if not cached_refresh:
            raise RuntimeError(f"Token cache at {self.token_cache} has no refresh_token. Re-run 'auth'.")

        data = self._post_token_request({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": cached_refresh,
        })
        self._store(data)

    def get_valid_token(self) -> str:
        if self.access_token is None or time.time() >= self.expires_at:
            self.ensure_token_headless()
        return self.access_token


def get_session(token_manager: TokenManager) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    def _auth_hook(request, **kwargs):
        request.headers["Authorization"] = f"Bearer {token_manager.get_valid_token()}"
        return request

    session.auth = lambda r: _auth_hook(r)
    return session


# --------------------------------------------------------------------------
# Activities + FIT download
# --------------------------------------------------------------------------

def fetch_activity_page(session: requests.Session, page: int, per_page: int,
                         start_date: str | None = None) -> dict:
    params = {"page": page, "perPage": per_page}
    if start_date:
        params["startDate"] = start_date
    resp = session.get(f"{API_BASE}/activities", params=params)
    resp.raise_for_status()
    return resp.json()


def download_fit(session: requests.Session, activity_id: str, dest: Path) -> bool:
    resp = session.get(
        f"{API_BASE}/activities/{activity_id}/file",
        headers={"Accept": "application/vnd.ant.fit"},
        stream=True,
    )
    if resp.status_code == 404:
        return False
    resp.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return True


def download_batch(session: requests.Session, activities: list, out_dir: Path) -> int:
    count = 0
    for activity in activities:
        activity_id = activity["id"]
        name = activity.get("name", activity_id)
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(activity_id))
        dest = out_dir / f"{safe_name}.fit"

        print(f"  {name} ({activity_id}) ...", end=" ")
        try:
            ok = download_fit(session, activity_id, dest)
            print(f"saved to {dest}" if ok else "no FIT file (404)")
        except requests.HTTPError as e:
            print(f"error: {e}")
        count += 1
    return count


# --------------------------------------------------------------------------
# Run-state
#
# State tracks:
#   last_activity_date   -- the createdAt (date, YYYY-MM-DD) of the most
#                            recent activity we've downloaded. Used as the
#                            `startDate` filter for the NEXT run, so we
#                            only ask the API for activities on/after that
#                            date (a 1-day overlap by design -- harmless,
#                            since files are named by activity id and
#                            re-downloads just overwrite).
#   backfill_complete     -- whether the initial full-history backfill has
#                             finished.
#   backfill_next_page    -- resume cursor for the backfill, in case the
#                             container restarts mid-backfill.
# --------------------------------------------------------------------------

def load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_state(state_file: Path, state: dict):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))


def _activity_date(activity: dict) -> str | None:
    created = activity.get("createdAt")
    return created[:10] if created else None  # YYYY-MM-DD prefix


def _max_date(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


# --------------------------------------------------------------------------
# Backfill (first run) and incremental sync (steady state)
# --------------------------------------------------------------------------

def run_backfill(session: requests.Session, out_dir: Path, state: dict,
                  state_file: Path, batch_size: int, interval_seconds: int):
    page = state.get("backfill_next_page", 1)
    print(f"Starting/resuming full-history backfill at page {page} (batch size {batch_size}).")

    while True:
        body = fetch_activity_page(session, page, batch_size)
        activities = body.get("data", [])
        total_pages = body.get("totalPages", page)

        if page == 1 and activities:
            # Newest-first page 1 tells us the most recent activity date
            # right away -- this seeds last_activity_date for steady state.
            newest = max((_activity_date(a) for a in activities if _activity_date(a)), default=None)
            state["last_activity_date"] = _max_date(state.get("last_activity_date"), newest)

        if not activities:
            print("No activities returned; backfill complete.")
            state["backfill_complete"] = True
            save_state(state_file, state)
            return

        print(f"Batch (page {page}/{total_pages}): {len(activities)} activities")
        download_batch(session, activities, out_dir)

        page += 1
        state["backfill_next_page"] = page
        save_state(state_file, state)

        if page > total_pages:
            print("Backfill complete: reached the last page.")
            state["backfill_complete"] = True
            save_state(state_file, state)
            return

        print(f"Pausing {interval_seconds}s before next backfill batch...")
        time.sleep(interval_seconds)


def run_incremental(session: requests.Session, out_dir: Path, state: dict,
                     state_file: Path, batch_size: int):
    start_date = state.get("last_activity_date")
    print(f"Incremental sync (start_date={start_date or 'none'}).")

    page = 1
    max_seen = start_date
    total_downloaded = 0

    while True:
        body = fetch_activity_page(session, page, batch_size, start_date=start_date)
        activities = body.get("data", [])
        if not activities:
            break

        for a in activities:
            max_seen = _max_date(max_seen, _activity_date(a))

        total_downloaded += download_batch(session, activities, out_dir)

        total_pages = body.get("totalPages", page)
        if page >= total_pages:
            break
        page += 1

    if max_seen and max_seen != start_date:
        state["last_activity_date"] = max_seen
        save_state(state_file, state)

    print(f"Incremental sync done: {total_downloaded} activities processed. "
          f"Next start_date: {state.get('last_activity_date')}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_auth(args):
    client_id = args.client_id or os.environ.get("HAMMERHEAD_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("HAMMERHEAD_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Error: set HAMMERHEAD_CLIENT_ID / HAMMERHEAD_CLIENT_SECRET.", file=sys.stderr)
        sys.exit(1)

    tm = TokenManager(client_id, client_secret, Path(args.token_cache), args.redirect_uri, args.scope)
    tm.interactive_authorize()


def cmd_run(args):
    client_id = args.client_id or os.environ.get("HAMMERHEAD_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("HAMMERHEAD_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Error: set HAMMERHEAD_CLIENT_ID / HAMMERHEAD_CLIENT_SECRET.", file=sys.stderr)
        sys.exit(1)

    batch_size = int(os.environ.get("HAMMERHEAD_BATCH_SIZE", DEFAULT_BATCH_SIZE))
    interval_minutes = int(os.environ.get("HAMMERHEAD_INTERVAL_MINUTES", DEFAULT_INTERVAL_MINUTES))
    interval_seconds = interval_minutes * 60

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_file = Path(args.state_file)
    state = load_state(state_file)

    tm = TokenManager(client_id, client_secret, Path(args.token_cache), args.redirect_uri, args.scope)
    try:
        tm.ensure_token_headless()
    except Exception as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)

    session = get_session(tm)

    print(f"Hammerhead FIT Downloader starting. batch_size={batch_size} "
          f"interval={interval_minutes}m out={out_dir} state={state_file}")

    if not state.get("backfill_complete"):
        run_backfill(session, out_dir, state, state_file, batch_size, interval_seconds)

    if args.once:
        run_incremental(session, out_dir, state, state_file, batch_size)
        return

    while True:
        try:
            run_incremental(session, out_dir, state, state_file, batch_size)
        except requests.HTTPError as e:
            print(f"Incremental sync failed, will retry next interval: {e}", file=sys.stderr)
        print(f"Sleeping {interval_seconds}s until next sync...")
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Hammerhead FIT Downloader")
    parser.add_argument("--client-id", type=str, default=None)
    parser.add_argument("--client-secret", type=str, default=None)
    parser.add_argument("--redirect-uri", type=str, default=DEFAULT_REDIRECT_URI)
    parser.add_argument("--scope", type=str, default=DEFAULT_SCOPE)
    parser.add_argument("--token-cache", type=str, default="./data/token.json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth", help="Interactive one-time authorization (run locally)")
    auth_parser.set_defaults(func=cmd_auth)

    run_parser = subparsers.add_parser("run", help="Headless daemon: backfill then poll (for Docker)")
    run_parser.add_argument("--out", type=str, default="./fit_files")
    run_parser.add_argument("--state-file", type=str, default="./data/state.json")
    run_parser.add_argument("--once", action="store_true",
                             help="Run backfill (if needed) plus a single incremental sync, then exit")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
