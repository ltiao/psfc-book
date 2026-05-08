# psfc-book

[![watcher](https://github.com/ltiao/psfc-book/actions/workflows/watcher.yml/badge.svg)](https://github.com/ltiao/psfc-book/actions/workflows/watcher.yml)
[![book](https://github.com/ltiao/psfc-book/actions/workflows/book.yml/badge.svg)](https://github.com/ltiao/psfc-book/actions/workflows/book.yml)
[![smoke](https://github.com/ltiao/psfc-book/actions/workflows/smoke.yml/badge.svg)](https://github.com/ltiao/psfc-book/actions/workflows/smoke.yml)

> _"Be patient, wait for them to ripen. Be brave and try something new."_
> — laminated sign in the Park Slope Food Coop produce aisle, on the
> matter of fresh dates

Books a Park Slope Food Coop orientation slot on your behalf, at the
exact moment slots are released, with the technical urgency of a flash
sale and none of the dignity.

We have lived a short walk from the Coop for over a year. We are not
members. Membership requires, in order: reading the online orientation
materials; attending an in-person enrollment appointment; presenting
two forms of ID; paying a joining fee and a refundable equity
investment; posing for a membership-card photograph; signing two
policy agreements; and scheduling a first work shift. Of these, only
the appointment must be scheduled in advance, and only on this
website. The Coop releases a tiny batch — about ten appointments —
sporadically, often two or three months apart, occasionally in
clusters of two or three releases over a fortnight. Each release
happens at 7 PM Eastern and lasts about two to three seconds. This
repository is a Python CLI that logs in, waits to the
millisecond, and grabs the first open slot. There is also a parallel
forensics mode (`scout`), which records every byte of every response,
so that when the booking attempt fails — and prior experience suggests
it will — the next session can begin with evidence rather than vibes.

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

There are three workflows.

- **`watcher.yml`** runs daily at 22:23 UTC. It logs in, reads the home
  page's "Upcoming Orientations" listing, and dispatches `book.yml` if
  anything announced for the next forty minutes calls for action. Most
  days nothing does, and it exits in three seconds.
- **`book.yml`** is the booking job. The watcher invokes it on demand;
  it also retains an independent cron on Mondays and Thursdays at 22:17
  UTC, on the principle that two triggers are harder to forget than
  one.
- **`smoke.yml`** is a manual sanity check. It logs in, fetches the
  calendar, fetches the home page, and asserts that we still recognize
  what comes back. Run it after touching the parser, or for the
  reassurance of seeing all three steps go green.

The off-the-hour minutes are deliberate — GitHub's scheduler is least
reliable at `:00` and `:30`, when everyone else's crons are also trying
to fire. And `--fire-at` busy-waits internally to the millisecond, so
GitHub Actions' famously imprecise scheduling is a non-issue, provided
the workflow has begun by 7 PM ET. So far it has.

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
> November, change `'17 22 * * 1,4'` to `'17 23 * * 1,4'`, or accept
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

### `home`

```bash
python psfc_book.py home
```

Logs in, fetches `/home/`, and parses any "Upcoming Orientations"
entries into a structured table. Mostly run to confirm that the
announcement format hasn't shifted under us; occasionally run because
it is genuinely the easiest way to find out when the next release is.

### `watch`

```bash
python psfc_book.py watch
```

The watcher's loop. Logs in, fetches `/home/`, decides whether anything
announced for today calls for action, and writes the verdict to
`$GITHUB_OUTPUT` for the workflow to read. The verdict is usually no.

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

Releases are not on a public schedule, and the Coop has not committed
to one. Announcements appear under "Upcoming Orientations" on the home
page some days or weeks ahead, naming the orientation date, the
appointment count, and the precise minute slots will become claimable.
The watcher reads this list once a day and acts on it.

At the time of writing the home page says appointments are "available
2 weeks in advance, at 7pm," and lists two upcoming releases — each
thirteen days before its orientation, fifteen appointments apiece, both
firing at 7 PM Eastern. Whether every release follows that pattern,
nobody has told us. We have watched five releases come and go in
roughly three seconds apiece, and have, at the time of writing, booked
precisely none of them.

If the home page ever vanishes, mutates, or simply lies, the
Monday-and-Thursday cron in `book.yml` continues to fire on its own.
Both runs upload artifacts. Forensics survive either way.

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
psfc_book.py                       Typer CLI: book, scout, home, watch
requirements.txt                   typer, requests, beautifulsoup4, lxml, rich
.github/workflows/watcher.yml      daily home-page check; dispatches book.yml
.github/workflows/book.yml         the booking job — dispatched and on cron
.github/workflows/smoke.yml        manual end-to-end credential and parser check
```

## Further reading

- _The New Yorker_, ["The Grocery Store Where Produce Meets Politics"][nyer]. Recommended in the spirit, contradicted in the letter, by this software.
- [Park Slope Food Coop manual][manual]. The full procedure, of which this software automates only the prefatory step.

[nyer]: https://www.newyorker.com/magazine/2019/11/25/the-grocery-store-where-produce-meets-politics
[manual]: https://www.foodcoop.com/manual/

## Caveats

- The Coop is a cooperative. This script is for booking _your own_
  orientation. Running parallel attempts to grab several slots would
  be, among other things, not in the spirit of coöperation.
- The appointment is the gate. On the far side of it is a process
  involving two forms of ID, a $25 joining fee, a $100 refundable
  member-owner equity investment, a photograph, two signed policy
  agreements, the household-membership rule, a recurring 2-hour-45-minute
  work shift, monthly General Meetings conducted under Robert's Rules,
  and the _Linewaiters' Gazette_. This script cannot help with any of
  them.
- GitHub Actions cron triggers can be delayed by 5 to 30 minutes during
  busy periods. We schedule 30 minutes early and busy-wait. Do not
  tighten this without first imagining the consequences vividly.
- The `book.yml` cron continues to fire every Monday and Thursday as a
  backstop, regardless of whether the watcher had anything to dispatch.
  Most weeks find nothing released and the run exits cleanly. Each idle
  firing costs about a second of compute, which is to say nothing.
- This software exists. Whether it should is a separate question, and
  one which would, in an appropriate venue, take ninety minutes to
  resolve.
