# Getting Started — Hammerhead FIT Downloader

A from-scratch walkthrough, assuming you've never run a service like this
before. Every command below is meant to be copy-pasted exactly as written
into a terminal.

This project is inspired by, and thanks to,
[dreeve-garmin-connector](https://github.com/dreeveapp/dreeve-garmin-connector)
and its developers — see the Acknowledgments section in `README.md` for
more.

**Which terminal?**
- **macOS:** open the "Terminal" app (Cmd+Space, type "Terminal").
- **Windows:** install [WSL](https://learn.microsoft.com/windows/wsl/install) first (`wsl --install` in PowerShell as Administrator, then reboot), and do everything below inside the Ubuntu terminal it gives you. Docker on Windows works far more reliably through WSL than through raw PowerShell.
- **Linux / TrueNAS SCALE:** whatever shell you already use to run `docker compose`.

---

## 1. Install Docker

This project runs as a Docker container. You don't need Python or any other
dependency on the machine that runs it.

- **macOS / Windows:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/), open it once so it finishes starting up.
- **Linux:** follow [Docker's install guide](https://docs.docker.com/engine/install/) for your distro, then also install the Compose plugin (usually bundled, or `sudo apt install docker-compose-plugin` on Debian/Ubuntu).
- **TrueNAS SCALE:** Docker/Compose is built in; just work from wherever you already run `docker compose` commands.

Check it worked:

```bash
docker compose version
```

You should see a version number, not a "command not found" error.

---

## 2. Unpack the project

Move the zip file you downloaded (`hammerhead-fit-downloader.zip`)
somewhere sensible, e.g. your home folder, then:

```bash
cd ~/Downloads          # or wherever the zip actually is
unzip hammerhead-fit-downloader.zip
cd hammerhead-fit-downloader
```

Every command from here on assumes you're standing inside that
`hammerhead-fit-downloader` folder. If a command fails with something like
"no such file or directory", run `pwd` to check where you are.

---

## 3. Build and publish the image (once, or after any code change)

`docker-compose.yml` doesn't build the image itself — it pulls a pre-built
one from Docker Hub, from the `goatie999` account. If that's your account,
build and push it once (and again after any code change):

```bash
docker build -t goatie999/hammerhead-fit-downloader:latest .
docker login
docker push goatie999/hammerhead-fit-downloader:latest
```

If you've forked this project and want it under your own Docker Hub
namespace instead, replace `goatie999` with your own username in the
commands above **and** in the `image:` line of `docker-compose.yml`. If the
repository is private, also run `docker login` once on whichever machine
will actually run the service (e.g. your TrueNAS box), so it's allowed to
pull it.

You only need to repeat this step if you change the connector's code —
day-to-day, the deployment machine just pulls whatever tag was last pushed.

---

## 4. Get Hammerhead API credentials

You need a `client_id` and `client_secret`, issued by Hammerhead when you
register an API client (this is separate from your regular Hammerhead
account login). Hammerhead's own guide walks through the whole process:
[Creating a Developer Account](https://support.hammerhead.io/hc/en-us/articles/43558376710683-Creating-a-Developer-Account).
When it asks for a redirect URI, use `http://localhost:8080/callback` —
this is just a placeholder page on your own machine that catches the login
response; it doesn't need to actually be running anything.

You'll get back two values that look like random strings. Keep them
private — treat them like a password.

---

## 5. Configure your environment file

```bash
cp .env.example .env
```

Now open `.env` in a text editor (`nano .env`, or open the folder in
VS Code / TextEdit / Notepad — whatever you're comfortable with) and fill in
the two credential lines:

```
HAMMERHEAD_CLIENT_ID=the-client-id-you-were-given
HAMMERHEAD_CLIENT_SECRET=the-client-secret-you-were-given
```

Leave everything else as-is for now (the watch/state/token folder locations
are fixed inside the app on purpose — see step 7 for where they end up on
your machine). Save the file.

---

## 6. Authorize the connector with Hammerhead (one time only)

Pull the image, then run the one-time setup command:

```bash
docker compose pull
docker compose run --rm hammerhead-fit-downloader setup http://localhost:8080/callback
```

`docker compose pull` fetches the image you pushed in step 3 from Docker
Hub; `docker compose run` then starts a temporary container from it just
for this one command (`--rm` removes that container again once it exits —
the long-running service you start in step 7 is separate).

What happens:

1. The terminal prints a long `https://api.hammerhead.io/...` URL. Copy the
   **whole thing** and paste it into your regular web browser.
2. Log in to Hammerhead if asked, and approve access.
3. Hammerhead redirects your browser to
   `http://localhost:8080/callback?code=SOMETHING&state=...`. Nothing is
   actually listening on port 8080, so the page itself will fail to load —
   **that's expected**. What you need is in the address bar: copy just the
   value after `code=` and before the next `&`.
4. Back in the terminal, it's waiting with a prompt:
   `Paste the code query param from the redirect URL:` — paste that value
   and press Enter.

If it worked, you'll see `Saved tokens to /data/hammerhead/tokens/tokens.json`,
and a new `hammerhead/tokens/tokens.json` file will appear in your project
folder on disk. That file is your login for every future run — you won't
need to repeat this step unless you delete it or revoke access.

---

## 7. Start the connector

```bash
docker compose up -d
```

`-d` runs it in the background. It will now poll Hammerhead every 30 minutes
(configurable via `HAMMERHEAD_POLL_INTERVAL` in `.env`) and write any new
activity FIT files into the `watch/` folder that appears in your project
directory.

Three folders will exist alongside `docker-compose.yml` after this:

```
watch/                       <- new activity files land here
hammerhead/state/             <- sync cursor (which activities are done)
hammerhead/tokens/            <- OAuth tokens from step 6
```

---

## How downloads avoid racing Dreeve's watch

Worth understanding once things are running, not just for troubleshooting:
Dreeve scans the watch folder on its own schedule and imports whatever it
finds there — it has no way to know a file is still being written. So each
activity is downloaded to `<name>.part` first; only once that write has
fully completed does it get renamed to `<name>.fit`. A rename is atomic on
the same filesystem, so Dreeve only ever sees either no file, or a complete
one — never a partial download mid-write. If you happen to `ls watch/`
mid-download you may briefly see one of these `.part` files; that's normal,
and it'll rename itself the instant the download finishes. You never need
to do anything with a `.part` file yourself.

---

## 8. Check it's actually working

Watch the logs live:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop watching (this does **not** stop the service, just
the log view). You're looking for lines like:

```
Watching folder: /data/dreeve/watch
No new activities to sync
```

or, once you have new rides:

```
Downloading activity 1000.activity.abcd (My Epic Ride)
Wrote /data/dreeve/watch/2025-01-25_My-Epic-Ride_1000.activity.abcd.fit
```

Check the actual files on your machine:

```bash
ls watch/
```

---

## 9. Point Dreeve at the same folder

This connector's job ends once files land in `./watch`. For Dreeve to pick
them up, Dreeve's own container needs to watch that **same** folder. If
Dreeve also runs via `docker-compose.yml` on this machine, set its watch
volume to the absolute path of this project's `watch/` directory, e.g.:

```yaml
# in Dreeve's own docker-compose.yml
volumes:
  - /home/you/hammerhead-fit-downloader/watch:/watch
```

(Run `pwd` inside this project folder to get the exact absolute path to use.)

If you'd rather run this connector as *part of* Dreeve's own
`docker-compose.yml` stack instead of a separate one, see "Running as part
of Dreeve's own docker-compose.yml" in `README.md`.

---

## Everyday commands, once it's set up

| What you want | Command |
|---|---|
| Pull the latest image that was pushed | `docker compose pull` |
| Start it | `docker compose up -d` |
| Stop it | `docker compose down` |
| See live logs | `docker compose logs -f` |
| Restart after editing `.env` or pulling a new image | `docker compose up -d --force-recreate` |
| Check it's running | `docker compose ps` |

## If something goes wrong

- **`docker compose run ... setup` hangs or errors immediately:** double
  check `HAMMERHEAD_CLIENT_ID` / `HAMMERHEAD_CLIENT_SECRET` in `.env` have
  no extra spaces or quotes around them.
- **"pull access denied" / "repository does not exist":** the `image:` line
  in `docker-compose.yml` points at a Docker Hub namespace/repo that either
  doesn't exist yet (step 3 wasn't completed) or is private and you haven't
  run `docker login` on this machine.
- **"No stored Hammerhead tokens found" when running `up`:** step 6 wasn't
  completed successfully, or `hammerhead/tokens/tokens.json` got deleted.
  Re-run step 6.
- **Nothing downloads even though you have new rides:** check
  `docker compose logs -f` for errors; if the access token expired and
  Hammerhead rejected the refresh too, delete `hammerhead/tokens/tokens.json`
  and repeat step 6.
- **Changed `.env` and it's not taking effect:** `docker compose up -d --force-recreate`
  — a plain restart keeps the old environment variables.
