# noris — clinic slot monitor

Watches the **Noris Psychotherapie** ADHS online booking page on Terminland and
sends a **Telegram** message the moment appointment slots open up. The clinic
runs no waitlist and slots get snapped up fast, so this checks for you every
**15 minutes between 08:00 and 21:00** (Europe/Berlin).

Booking page: <https://www.terminland.de/noris-psychotherapie/online/ADHS_new/>

## How it works

Terminland is a JavaScript-driven ASP.NET wizard, so a headless browser
(Playwright/Chromium) drives the flow:

1. **Fragen** — selects the *ADHS-Abklärung* service, clicks *Weiter*.
2. **Terminauswahl** — classifies the schedule:

   | State | Trigger | Action |
   |---|---|---|
   | `available` | concrete `HH:MM` times found (wins over everything) | 🟢 alert with the times |
   | `none` | no times **and** a positive "no free slots" notice | stay silent |
   | `queue` | the high-demand waiting room didn't clear in time | ⏳ "queue active — check now" |
   | `unknown` | no times and *not* confirmed-empty | 🟡 "possible opening — check now" |
   | `error` | the page failed to load twice in a row | 🛠️ "couldn't load — check manually" |

   Under high load Terminland shows a **virtual waiting room** ("*erhöhtes
   Buchungsaufkommen … Wartezeit*") with a countdown before the booking opens.
   The checker detects it and **waits it out** (up to `QUEUE_MAX_WAIT_S`) before
   reading the schedule; only a queue that never clears falls through to the
   `queue` alert. Note this is distinct from the *no-slots* hint, which says
   "*hohen Buchungsaufkommens*" — so an empty page is never mistaken for a queue.

   **Insurance split.** The clinic exposes two deeplinks: `…/online/ADHS_new/`
   (*gesetzlich* / statutory — the default here, very limited slots) and
   `…/online/ADHS_Privat/` (*Selbstzahler* / self-pay — less restricted). Point
   `CLINIC_URL` at whichever you need.

   **Bias: a false positive beats a false negative.** Opening the page to find
   nothing is fine; *missing* a slot is not. So the only silent outcome is a
   page we've positively confirmed empty. Parsed times always win (even if a
   stale "no slots" banner is also present), anything ambiguous pings you, and
   a scraper that breaks alerts rather than going quiet.

Whenever a check is **not** `none`, the page HTML + a full-page screenshot are
saved under `captures/` (and uploaded as a GitHub Actions artifact), so the
first real opening is captured as ground truth to verify and refine against.

A small `state.json` remembers what it already told you about, so you get
**one** alert per opening — not a ping every 15 minutes while a slot lingers.
If a slot disappears and later returns, it alerts again.

> **Validated on real availability.** The clinic's page is usually empty, but
> the detector has been run against live Terminland practices that *did* have
> open slots (same software, v21.15) — it correctly reported `available` and
> parsed the real times. That case is frozen as a regression fixture in
> `tests/`.

```
src/clinic_monitor/
  checker.py    # ← the only Terminland-specific file (browser flow + parsing)
  monitor.py    # check → diff against memory → notify → persist
  telegram.py   # Telegram Bot API
  state.py      # on-disk dedup memory
  config.py     # env / .env loading
  cli.py        # check | loop | test-telegram
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium      # one-time browser download
cp .env.example .env             # then fill in TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
```

### Telegram (required, one-time)

1. In Telegram, message **@BotFather** → `/newbot` → copy the **token**.
2. **Open your bot and press _Start_** (or send it any message). A bot cannot
   message you until you've messaged it first — skipping this gives
   `Bad Request: chat not found`.
3. Get your numeric chat id from **@userinfobot**, put it in `.env`.
4. Verify:

   ```bash
   clinic-monitor test-telegram
   ```

## Running

```bash
clinic-monitor check                 # one check (respects the 08–21 window)
clinic-monitor check --ignore-window # check right now, regardless of time
clinic-monitor check --dry-run       # check + log, but don't send Telegram
clinic-monitor loop                  # run forever, every INTERVAL_MINUTES
```

`loop` is the always-on mode; `check` is the one-shot used by cron / CI.

## Deploy (always-on)

### Option A — Docker (recommended for true 24/7)

Runs the loop on any always-on host (a VPS, or a free tier like Fly.io /
Railway). State survives restarts via the `./data` volume.

```bash
docker compose up -d --build
docker compose logs -f
```

### Option B — GitHub Actions (zero server, free)

`.github/workflows/monitor.yml` runs `check` on a cron. No machine of your own
required.

1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions**:
   - Secrets: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
   - (optional) Variables: `CLINIC_URL`, `MONITOR_TZ`, `WINDOW_START`, `WINDOW_END`
3. Enable Actions; trigger once via **Run workflow** to confirm.

Caveats:
- **Use a public repo** (or accept Actions-minutes usage): this runs Chromium
  ~56×/day, which can exceed the 2,000 free minutes/month on a *private* repo.
  Public repos get unlimited Actions minutes. `.env` is git-ignored, and all
  secrets live in encrypted Actions secrets — nothing sensitive is committed.
- GitHub disables scheduled workflows after 60 days of repo inactivity, and
  cron firing can be delayed under load.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | — | Your numeric chat id |
| `CLINIC_URL` | the ADHS_new deeplink | Booking start URL |
| `NO_SLOTS_TEXT` | `keine freien Termine` | "nothing available" marker |
| `QUEUE_TEXT` | `erhöhtes Buchungsaufkommen` | waiting-room marker |
| `QUEUE_MAX_WAIT_S` | `180` | how long to wait out the queue before alerting |
| `WINDOW_START` / `WINDOW_END` | `08:00` / `21:00` | Daily check window |
| `INTERVAL_MINUTES` | `5` | Base loop interval |
| `JITTER_SECONDS` | `120` | Random ± offset on the interval (natural cadence) |
| `BROWSER_LOCALE` / `BROWSER_TIMEZONE` | `de-DE` / `Europe/Berlin` | Browser profile presented to the site |
| `MONITOR_TZ` | host local | IANA tz for the window (`Europe/Berlin`) |
| `HEADLESS` | `true` | Set `false` to watch the browser locally |
| `STATE_PATH` | `state.json` | Dedup memory location |
| `CAPTURE_DIR` | `captures` | Where HTML/screenshots of non-empty checks are saved |

## Tests

```bash
pip install -e .[dev]
pytest          # detection, dedup state, and window logic (no network)
```

## Maintenance note

If the clinic switches booking systems, or Terminland changes its markup, the
only file to adjust is `src/clinic_monitor/checker.py`. To debug the flow
visually, set `HEADLESS=false` and run `clinic-monitor check --ignore-window`.
