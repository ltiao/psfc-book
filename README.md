# psfc-book

> _"Be patient, wait for them to ripen. Be brave and try something new."_
> — laminated sign in the Park Slope Food Coop produce aisle, on the
> matter of fresh dates

Books a Park Slope Food Coop orientation slot on your behalf, at the
exact moment slots are released, with the technical urgency of a flash
sale and none of the dignity.

We have lived a short walk from the Coop for over a year. We have not
yet been to an orientation. The Coop releases a small batch of
appointments twice a week, on Mondays and Thursdays at 7 PM Eastern;
they last about two to three seconds. This repository is a Python CLI
that logs in, waits to the millisecond, and grabs the first open slot.
There is also a parallel forensics mode (`scout`), which records every
byte of every response, so that when the booking attempt fails — and
prior experience suggests it will — the next session can begin with
evidence rather than vibes.

## How it works

`ort.foodcoop.com` is a server-rendered Django app, in roughly the same
sense that your aunt's quilting blog is a server-rendered blog: a
session cookie, a CSRF token, a `<form>`, and not a byte of JSON in
sight. This is broadly in keeping with an institution whose internal
newsletter is called the _Linewaiters' Gazette_ and whose monthly
General Meeting still runs on Robert's Rules; only the orientation
intake, for some reason, is conducted at flash-sale speed.

Slots live behind `/calendar/<week>/<committee>/<time>/<anchor>/` and
render as `<div class="shift ...">` cells in a 7-column grid. Open
slots have no state class. Everything else has a class describing what
is wrong with it.

Booking is two HTTP requests: GET the calendar to find an open shift's
URL, then POST to that URL with the CSRF token to claim it. The script
collapses this into a tight loop on a pre-warmed session, fires at
exactly 19:00:00 ET, and writes everything down for posterity.

## Quick start — GitHub Actions

The cron in `.github/workflows/book.yml` fires every Monday and Thursday
at 22:30 UTC. The script's `--fire-at` flag busy-waits internally until
19:00:00 America/New_York, so GitHub Actions' famously imprecise
scheduling is a non-issue, provided the workflow has begun by 7 PM. So
far it has.

```bash
gh repo create psfc-book --private --source=. --push
gh secret set PSFC_USER --body 'your-coop-username'
gh secret set PSFC_PASS --body 'your-coop-password'
gh workflow run smoke.yml
```

After a run, download `psfc-dumps-<run_id>` from the Actions tab. It
contains some forty kilobytes of HTML and the exact reason you did or
did not get an orientation slot.

> **Daylight Saving caveat.** The cron is set for EDT. When DST ends in
> November, change `'30 22 * * 1,4'` to `'30 23 * * 1,4'`, or accept
> that you will be polling for slots an hour after they have all been
> claimed.

## Quick start — Local

```bash
pip install -r requirements.txt
export PSFC_USER='...'
export PSFC_PASS='...'

# Real booking, evening of:
python psfc_book.py book \
  --week 1 --target 5/20/2026 \
  --fire-at "2026-05-07 19:00:00" --tz America/New_York

# Recon — logs in, fetches the calendar, dumps it, claims nothing.
python psfc_book.py scout --week 0
```

## Commands

### `book`

Logs in, waits for `--fire-at`, polls the calendar at `--poll-ms`
intervals, claims the first open slot it finds, and exits.

| Flag | Default | Notes |
|---|---|---|
| `--week`, `-w` | required | `0` = current week, `1` = next, and so on. |
| `--target`, `-t` | none | Day-label substring, e.g. `5/20/2026`. Without it, takes the first open slot in the week. |
| `--anchor` | `2026-05-07` | The date the server templates into URLs. |
| `--fire-at` | none | Local datetime to wait for. |
| `--tz` | `America/New_York` | |
| `--lead-ms` | `200` | Begin polling N ms before `--fire-at`. |
| `--poll-ms` | `80` | Delay between calendar GETs. |
| `--max-attempts` | `60` | About five seconds at default `poll-ms`. |
| `--dry-run` / `--live` | `--live` | `--dry-run` parses but does not POST. |
| `--dump-dir` | `./psfc_dumps` | |
| `--user` / `--password` | env: `PSFC_USER`, `PSFC_PASS` | Prefer env. |

Exit codes: `0` you have an orientation; `1` your password is wrong;
`2` the booking page has no form, and refunds are not offered;
`3` you do not have an orientation.

### `scout`

```bash
python psfc_book.py scout --week 1 --target 5/20/2026
```

Logs in, fetches the calendar, dumps it, and pulls one slot detail page
if any are visible. Useful for confirming credentials, studying form
structure, and the quiet satisfaction of inspecting other people's
already-claimed slots after a release you slept through.

## What gets recorded

Every invocation writes to `./psfc_dumps/<UTC_timestamp>_<label>/`:

```
calendar_prewarm.html          the calendar GET before --fire-at
calendar_a001.html ...         every poll response, in order
calendar_postmortem.html       final fetch if booking missed
postmortem_shifts.json         parsed .shift list with diagnoses
slot_detail.html               the detail page, when seen
book_request.json              the direct POST payload
book_response_<status>.html    its response body
book_fallback_request.json     the form-replay POST, if used
book_fallback_response_*.html
meta.json                      args, timings, per-attempt latency, and
                               the precise number of milliseconds by
                               which you missed
```

Even on a miss, the post-mortem captures the slot URL pattern from
taken shifts. The form, the URL, and the timing are all recorded. Only
the slot is gone.

## Release timing

| Orientation day | Release window |
|---|---|
| Wednesday | Thursday 7 PM ET, 13 days prior |
| Sunday    | Monday 7 PM ET, 13 days prior   |

`--target` is always today plus 13 days. The workflow computes this:

```yaml
ANCHOR=$(TZ=America/New_York date +%Y-%m-%d)
TARGET=$(TZ=America/New_York date -d '+13 days' +'%-m/%-d/%Y')
```

## Reference

```
/calendar/{week_offset}/{committee_id}/{time_of_day}/{anchor_date}/
```

`week_offset = 0` is the 7-day window starting on `anchor_date`. The
`committee_id` and `time_of_day` filters take `0/0` to mean "all",
which is the only setting any user has ever needed.

| Shift class | Meaning |
|---|---|
| (none) | claimable |
| `my_shift` | already yours |
| `worker` | someone else's |
| `unavail` | locked, or in any case not for you |
| `cancelled` | admin-cancelled |
| `resolved`, `no_show` | concluded, in one direction or the other |

## Files

```
psfc_book.py                   Typer CLI: book + scout
requirements.txt               typer, requests, beautifulsoup4, lxml, rich
.github/workflows/book.yml     cron-driven booking
.github/workflows/smoke.yml    manual end-to-end credential check
```

## Caveats

- The Coop is a cooperative. This script is for booking _your own_
  orientation. Running parallel attempts to grab several slots would
  be, among other things, not in the spirit of coöperation.
- The orientation is the first step of a process involving a 2.75-hour
  work shift every four weeks, the household-membership rule, monthly
  General Meetings conducted under Robert's Rules, and the
  _Linewaiters' Gazette_. This script cannot help with any of them.
- GitHub Actions cron triggers can be delayed by 5 to 30 minutes during
  busy periods. We schedule 30 minutes early and busy-wait. Do not
  tighten this without first imagining the consequences vividly.
- The `book` workflow's cron will run every Monday and Thursday until
  disabled, including weeks when nothing is released. Each pointless
  run costs approximately one second of compute, which is to say
  nothing.
- This software exists. Whether it should is a separate question, and
  one which would, in an appropriate venue, take ninety minutes to
  resolve.
