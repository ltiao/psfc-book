# psfc-book

Auto-books a Park Slope Food Coop orientation slot at the 7 PM ET release.

## Local

```bash
pip install typer requests beautifulsoup4 lxml rich
export PSFC_USER='your_username_or_email'
export PSFC_PASS='your_password'

# fire tonight at 7:00 PM ET
python psfc_book.py book \
  --week 1 --target 5/20/2026 \
  --fire-at "2026-05-07 19:00:00" --tz America/New_York

# recon-only (no booking)
python psfc_book.py scout --week 1
```

Every run dumps to `./psfc_dumps/<timestamp>_<label>/`: every calendar
response, the booking POST payload + response, a post-mortem fetch if we
miss, and a `meta.json` of timings. Share that folder if a run fails.

## GitHub Actions

The `.github/workflows/book.yml` cron fires Mon and Thu at 22:30 UTC
(6:30 PM EDT). The script's `--fire-at` busy-waits to the millisecond, so
GH's scheduling jitter doesn't matter — only that we start before 7 PM ET.

**Setup:**

1. Push this repo to GitHub (private recommended).
2. Repo → Settings → Secrets and variables → Actions → add:
   - `PSFC_USER`
   - `PSFC_PASS`
3. The cron will fire automatically. To trigger manually any time, use the
   "Run workflow" button on the Actions tab.
4. Workflow artifacts (dumps) are downloadable for 30 days from each run.

When DST ends in November, change the cron from `'30 22 * * 1,4'` to
`'30 23 * * 1,4'`.

## Slot CSS / URL pattern (for reference)

- Calendar URL: `/calendar/{week_offset}/{committee_id}/{time_of_day}/{anchor_date}/`
  - `week_offset = 0` is the week starting on `anchor_date`
  - `0/0` for committee/time = no filter
- Each appointment is a `.shift` element. Class modifiers: `worker` (taken),
  `unavail` (locked), `cancelled`, `my_shift`, `resolved`, `no_show`. Open
  slots have none of those.
- Releases are 14 days before the orientation, at 7 PM ET (Mon for Sun
  orientations, Thu for Wed orientations).
