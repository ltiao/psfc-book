# psfc-book

Auto-books a Park Slope Food Coop orientation slot at the 7 PM ET release.

The Coop releases a small batch of orientation appointments twice a week
(Mondays and Thursdays at 7:00 PM Eastern). They typically fill in 2–3
seconds. This is a thin Python CLI that logs in, waits to the millisecond,
and grabs the first open slot — plus a parallel forensics mode (`scout`)
that records everything for post-mortem if a run misses.

## How it works

The site (`https://ort.foodcoop.com`) is a server-rendered Django app:
session cookie + CSRF token, no JSON API, no SPA. Slots live behind
`/calendar/<week>/<committee>/<time>/<anchor>/` and are rendered as
`<div class="shift ...">` cells inside a 7-column grid. Open slots have no
state class; taken ones get `worker`, locked ones get `unavail`, etc.

The booking path is two server requests: GET the calendar to find an open
shift's URL, then POST to that URL with the CSRF token to claim it. The
script collapses this into a tight loop with pre-warmed session, fires at
exactly 19:00:00 ET, and records every byte of every response.

## Quick start — GitHub Actions (zero-touch)

The `.github/workflows/book.yml` cron fires every Monday and Thursday at
22:30 UTC (6:30 PM EDT) and busy-waits internally to 7:00:00 ET, so
GitHub's scheduling jitter is irrelevant — what matters is that we start
before 7 PM. Setup:

```bash
gh repo create psfc-book --private --source=. --push
gh secret set PSFC_USER --body 'your-coop-username'
gh secret set PSFC_PASS --body 'your-coop-password'
gh workflow run smoke.yml   # one-shot end-to-end check
```

After tonight's run completes, download `psfc-dumps-<run_id>` from the
Actions UI for the full forensics package.

> **Daylight Saving caveat.** The cron is set for EDT. When DST ends in
> November, change `'30 22 * * 1,4'` to `'30 23 * * 1,4'` in
> `.github/workflows/book.yml`.

## Quick start — Local

```bash
pip install -r requirements.txt
export PSFC_USER='...'
export PSFC_PASS='...'

# tonight, real booking
python psfc_book.py book \
  --week 1 --target 5/20/2026 \
  --fire-at "2026-05-07 19:00:00" --tz America/New_York

# safe recon — log in, fetch the calendar, dump it. No booking.
python psfc_book.py scout --week 0
```

## Commands

### `book` — wait for release, claim a slot

| Flag | Default | Notes |
|---|---|---|
| `--week`, `-w` | required | `0` = current week, `1` = next, etc. The week _starts_ on `--anchor`. |
| `--target`, `-t` | none | Day-label substring, e.g. `5/20/2026`. Without it, grabs the first open slot in the week. |
| `--anchor` | `2026-05-07` | The date the server templates into URLs. Easiest to set this to "today". |
| `--fire-at` | none | Local datetime to wait for, e.g. `2026-05-07 19:00:00`. |
| `--tz` | `America/New_York` | Timezone for `--fire-at`. |
| `--lead-ms` | `200` | Begin polling N ms before `--fire-at`. |
| `--poll-ms` | `80` | Delay between calendar GETs in the hot loop. |
| `--max-attempts` | `60` | Total polls before giving up (~5s at default poll-ms). |
| `--dry-run` / `--live` | `--live` | `--dry-run` parses but does not POST. |
| `--dump-dir` | `./psfc_dumps` | Where to write forensics. |
| `--user` / `--password` | env: `PSFC_USER`, `PSFC_PASS` | Credentials. Prefer env. |

Exit codes: `0` success, `1` login failure, `2` form discovery failed, `3`
gave up (no open slots in window).

### `scout` — recon, no booking

```bash
python psfc_book.py scout --week 1 --target 5/20/2026
```

Logs in, fetches the calendar, dumps it, and (if any shift is visible)
fetches one detail page so you can see the booking form. Useful any time
to confirm credentials work, or after a release you missed — taken
`.shift.worker` cells still expose the URL pattern.

## What gets recorded

Every invocation writes to `./psfc_dumps/<UTC_timestamp>_<label>/`:

```
calendar_prewarm.html        first calendar GET (before --fire-at)
calendar_a001.html ...       every poll response, in order
calendar_postmortem.html     final fetch if booking missed
postmortem_shifts.json       parsed .shift list with classes + hrefs
slot_detail.html             detail page (when fallback path or scout runs)
book_request.json            payload of the direct booking POST
book_response_<status>.html  body of that POST's response
book_fallback_request.json   payload of the form-replay POST (if used)
book_fallback_response_*.html
meta.json                    args, timings, per-attempt latency, slot URL,
                             booked status, fallback flag
```

Even on a miss, the post-mortem captures the slot URL pattern from taken
shifts, which lets you finalize the booking POST shape for the next batch.

## Release timing

| Orientation day | Release window |
|---|---|
| Wednesday | Thursday 7 PM ET, 13 days prior |
| Sunday | Monday 7 PM ET, 13 days prior |

The `--target` is always today + 13 days. The `book.yml` workflow computes
this dynamically:

```yaml
ANCHOR=$(TZ=America/New_York date +%Y-%m-%d)
TARGET=$(TZ=America/New_York date -d '+13 days' +'%-m/%-d/%Y')
```

## Reference: URL pattern + slot states

```
/calendar/{week_offset}/{committee_id}/{time_of_day}/{anchor_date}/
```

- `week_offset` — `0` = the 7-day window starting on `anchor_date`,
  `1` = the next 7 days, etc.
- `committee_id`, `time_of_day` — filter selects; `0/0` means no filter
- `anchor_date` — `YYYY-MM-DD`

Each `.shift` element's class set tells you its state:

| Class | Meaning |
|---|---|
| (none of the below) | open — claimable |
| `my_shift` | already yours |
| `worker` | taken by someone |
| `unavail` | locked / not yet released |
| `cancelled` | admin-cancelled |
| `resolved`, `no_show` | post-event states |

## Files

```
psfc_book.py              Typer CLI: book + scout commands
requirements.txt          typer, requests, beautifulsoup4, lxml, rich
.github/workflows/book.yml    cron-driven booking
.github/workflows/smoke.yml   manual end-to-end credential / setup check
```

## Caveats

- The Coop is a cooperative; this script is intended for booking _your
  own_ orientation. Don't run multiple parallel attempts trying to grab
  several slots — that would be hostile to other members and to the
  organization that runs the site.
- GitHub Actions cron triggers can be delayed by 5–30 minutes during
  load. We schedule 30 minutes early and busy-wait, so this is fine — but
  don't tighten the cron without thinking about it.
- The `book` workflow's cron will run every Monday and Thursday until
  disabled. It's a no-op if nothing is released or if all slots are taken
  — but you'll still burn a tiny amount of Actions minutes per run.
