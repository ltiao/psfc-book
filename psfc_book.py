#!/usr/bin/env python3
"""psfc_book.py — Auto-book a Park Slope Food Coop orientation slot."""
from __future__ import annotations
import json, time, logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
import typer
from bs4 import BeautifulSoup
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

BASE = "https://ort.foodcoop.com"
SKIP = {"worker", "unavail", "cancelled", "my_shift", "resolved", "no_show"}
SHIFT_STATES = ("worker", "unavail", "cancelled", "my_shift", "resolved", "no_show")

console = Console()
logging.basicConfig(
    level=logging.INFO, format="%(message)s", datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True,
                          show_path=False, markup=True)],
)
log = logging.getLogger("psfc")

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Auto-book a PSFC orientation slot (or scout it).")


# ───────────────────── helpers ─────────────────────

def csrf_from(html: str) -> Optional[str]:
    el = BeautifulSoup(html, "lxml").select_one("input[name=csrfmiddlewaretoken]")
    return el["value"] if el else None


def login(s: requests.Session, user: str, pw: str) -> None:
    r = s.get(f"{BASE}/login/", timeout=10); r.raise_for_status()
    r = s.post(
        f"{BASE}/login/",
        data={"csrfmiddlewaretoken": csrf_from(r.text),
              "username": user, "password": pw, "next": ""},
        headers={"Referer": f"{BASE}/login/"}, timeout=10,
    )
    r.raise_for_status()
    if not s.cookies.get("sessionid"):
        log.error("[red]login failed[/]"); raise typer.Exit(1)


def harvest_shifts(html: str, target: Optional[str] = None):
    """Return a list of dicts describing every .shift element on the calendar
    page — open or taken. Used for booking AND for forensics."""
    soup = BeautifulSoup(html, "lxml")
    found = []
    for col in soup.select("div.grid-container > div.col"):
        day = col.find("p").get_text(" ", strip=True) if col.find("p") else ""
        if target and target not in day:
            continue
        for el in col.select(".shift"):
            classes = list(el.get("class", []))
            states = [c for c in classes if c in SHIFT_STATES]
            a = el if el.name == "a" else (el.find("a") or el.find_parent("a"))
            href = a["href"] if (a and a.get("href")) else None
            found.append({
                "day": day,
                "classes": classes,
                "states": states,
                "open": not (set(classes) & SKIP),
                "href": urljoin(BASE, href) if href else None,
                "text": el.get_text(" ", strip=True),
            })
    return found


def find_open_slot(html: str, target: Optional[str]):
    for sh in harvest_shifts(html, target):
        if sh["open"] and sh["href"]:
            return sh["href"], sh["day"]
    return None, None


# ───────────────────── recorder ─────────────────────

@dataclass
class Attempt:
    n: int
    t_unix: float
    status: int
    latency_ms: float
    open_slots: int
    total_shifts: int

@dataclass
class RunMeta:
    args: dict
    started_at: str
    finished_at: Optional[str] = None
    primed_csrf_tail: Optional[str] = None
    primed_session_tail: Optional[str] = None
    attempts: list[Attempt] = field(default_factory=list)
    found_slot_url: Optional[str] = None
    found_day: Optional[str] = None
    booked_status: Optional[Any] = None
    booked_message: Optional[str] = None
    fallback_used: bool = False


class Recorder:
    """Writes everything we observe to a timestamped directory."""

    def __init__(self, root: Path, label: str, args: dict):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = root / f"{ts}_{label}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = RunMeta(args=args, started_at=datetime.now().isoformat())
        log.info(f"recording to [cyan]{self.dir}[/]")

    def write(self, name: str, content: str | bytes) -> Path:
        p = self.dir / name
        if isinstance(content, str):
            p.write_text(content)
        else:
            p.write_bytes(content)
        return p

    def attempt(self, n: int, r: requests.Response, slots_summary: tuple[int, int]):
        self.write(f"calendar_a{n:03d}.html", r.text)
        self.meta.attempts.append(Attempt(
            n=n, t_unix=time.time(),
            status=r.status_code,
            latency_ms=r.elapsed.total_seconds() * 1000,
            open_slots=slots_summary[0],
            total_shifts=slots_summary[1],
        ))

    def book_request(self, kind: str, url: str, payload: dict, r: requests.Response):
        prefix = "book" if kind == "direct" else "book_fallback"
        self.write(f"{prefix}_request.json",
                   json.dumps({"url": url, "payload": payload}, indent=2))
        self.write(f"{prefix}_response_{r.status_code}.html", r.text)

    def finalize(self):
        self.meta.finished_at = datetime.now().isoformat()
        d = asdict(self.meta)
        # convert Attempt list (already dicts via asdict)
        self.write("meta.json", json.dumps(d, indent=2, default=str))
        log.info(f"meta + dumps in [cyan]{self.dir}[/]")


# ───────────────────── booking actions ─────────────────────

def try_book(s, slot_url, csrf, referer, rec: Optional[Recorder]):
    payload = {"csrfmiddlewaretoken": csrf, "confirm": "1"}
    r = s.post(slot_url, data=payload,
               headers={"Referer": referer}, timeout=10, allow_redirects=True)
    log.info(f"[bold]POST[/] {slot_url} → [cyan]{r.status_code}[/]")
    if rec: rec.book_request("direct", slot_url, payload, r)
    return r


def fallback_book(s, slot_url, referer, rec: Optional[Recorder]):
    r = s.get(slot_url, timeout=10); r.raise_for_status()
    if rec: rec.write("slot_detail.html", r.text)
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form")
    if not form:
        log.error("no form on detail page"); raise typer.Exit(2)
    action = urljoin(slot_url, form.get("action") or slot_url)
    data = {i["name"]: i.get("value", "")
            for i in form.select("input[name],select[name],textarea[name]")}
    fresh = csrf_from(r.text)
    if fresh: data["csrfmiddlewaretoken"] = fresh
    rr = s.post(action, data=data, headers={"Referer": slot_url}, timeout=10)
    log.info(f"[bold]FALLBACK POST[/] {action} → [cyan]{rr.status_code}[/]")
    if rec: rec.book_request("fallback", action, data, rr)
    return rr


def countdown_to(when_dt: datetime, lead_ms: int) -> None:
    target_ts = when_dt.timestamp() - lead_ms / 1000
    total = target_ts - time.time()
    if total <= 0:
        return
    with Progress(
        TextColumn("[bold]Holding fire until {task.description}"),
        BarColumn(), TimeRemainingColumn(), console=console, transient=True,
    ) as p:
        t = p.add_task(f"T-{lead_ms}ms before {when_dt:%H:%M:%S %Z}", total=total)
        while True:
            rem = target_ts - time.time()
            if rem <= 0: break
            p.update(t, completed=total - rem)
            time.sleep(min(0.1, rem))


# ───────────────────── commands ─────────────────────

@app.command()
def book(
    week: int = typer.Option(..., "--week", "-w", help="0=this week, 1=next, …"),
    target: Optional[str] = typer.Option(
        None, "--target", "-t",
        help="Day-label substring to match, e.g. '5/20/2026'."),
    anchor: str = typer.Option(
        "2026-05-07", "--anchor",
        help="Anchor date the server templates into URLs (YYYY-MM-DD)."),
    fire_at: Optional[str] = typer.Option(
        None, "--fire-at",
        help="Local datetime to fire at, e.g. '2026-05-07 19:00:00'."),
    tz: str = typer.Option("America/New_York", "--tz"),
    lead_ms: int = typer.Option(200, "--lead-ms"),
    poll_ms: int = typer.Option(80, "--poll-ms"),
    max_attempts: int = typer.Option(60, "--max-attempts"),
    dry_run: bool = typer.Option(False, "--dry-run/--live"),
    dump_dir: Path = typer.Option(Path("./psfc_dumps"), "--dump-dir",
                                  help="Where to record HTML/payloads."),
    user: str = typer.Option(..., envvar="PSFC_USER"),
    password: str = typer.Option(..., envvar="PSFC_PASS",
                                 hide_input=True, prompt=False),
):
    """Log in, wait for release, grab the first open slot."""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"

    cal_url = f"{BASE}/calendar/{week}/0/0/{anchor}/"
    label = f"book_w{week}_{(target or 'any').replace('/', '-')}"
    rec = Recorder(dump_dir, label, {
        "command": "book", "week": week, "target": target, "anchor": anchor,
        "fire_at": fire_at, "tz": tz, "lead_ms": lead_ms, "poll_ms": poll_ms,
        "max_attempts": max_attempts, "dry_run": dry_run,
    })

    pre = Table.grid(padding=(0, 1))
    pre.add_column(style="bold"); pre.add_column()
    pre.add_row("user",     user)
    pre.add_row("calendar", cal_url)
    pre.add_row("target",   target or "[dim]any open slot[/]")
    pre.add_row("fire-at",  f"{fire_at} {tz}" if fire_at else "[dim]immediately[/]")
    pre.add_row("dump dir", str(rec.dir))
    pre.add_row("mode",     "[yellow]DRY RUN[/]" if dry_run else "[red]LIVE[/]")
    console.print(Panel(pre, title="[bold]PSFC orientation auto-booker",
                        border_style="cyan"))

    with console.status("[bold green]logging in…"):
        login(s, user, password)
    with console.status("[bold green]priming session…"):
        r = s.get(cal_url, timeout=10); r.raise_for_status()
    rec.write("calendar_prewarm.html", r.text)
    csrf = csrf_from(r.text) or s.cookies.get("csrftoken")
    rec.meta.primed_csrf_tail = csrf[-6:] if csrf else None
    rec.meta.primed_session_tail = s.cookies.get("sessionid", "")[-6:]
    log.info(f"primed; csrf …{rec.meta.primed_csrf_tail}, "
             f"sessionid …{rec.meta.primed_session_tail}")

    if fire_at:
        when = datetime.strptime(fire_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(tz))
        countdown_to(when, lead_ms)

    log.info(f"[bold]polling[/] every {poll_ms}ms (max {max_attempts})")
    booked: Optional[tuple] = None
    try:
        for attempt in range(1, max_attempts + 1):
            t0 = time.time()
            try:
                r = s.get(cal_url, timeout=5)
                shifts = harvest_shifts(r.text, target)
            except Exception as e:
                log.warning(f"[{attempt}] [red]err[/] {e}"); continue
            opens = [sh for sh in shifts if sh["open"] and sh["href"]]
            rec.attempt(attempt, r, (len(opens), len(shifts)))
            dt = (time.time() - t0) * 1000

            if opens:
                slot_url, day = opens[0]["href"], opens[0]["day"]
                rec.meta.found_slot_url = slot_url
                rec.meta.found_day = day
                log.info(f"[{attempt}] [bold green]FOUND[/] {day} → {slot_url} ({dt:.0f}ms)")
                if dry_run:
                    booked = ("dry-run", slot_url, day, None); break
                resp = try_book(s, slot_url, csrf, cal_url, rec)
                ok = resp.status_code in (200, 302) and "error" not in resp.text.lower()
                if not ok:
                    log.warning("direct POST didn't take — falling back")
                    rec.meta.fallback_used = True
                    resp = fallback_book(s, slot_url, cal_url, rec)
                soup = BeautifulSoup(resp.text, "lxml")
                msg_el = soup.select_one("ul.messages") or soup.find(["h2", "h3"])
                msg = msg_el.get_text(" ", strip=True) if msg_el else "(no message found)"
                booked = (resp.status_code, slot_url, day, msg); break

            log.info(f"[{attempt}] no slots ({dt:.0f}ms)")
            time.sleep(poll_ms / 1000)

        # post-mortem: if we never found an open slot but slots ARE there
        # (i.e. all taken), harvest the URL pattern from .worker shifts
        if booked is None:
            try:
                r = s.get(cal_url, timeout=5)
                rec.write("calendar_postmortem.html", r.text)
                shifts = harvest_shifts(r.text, target)
                rec.write("postmortem_shifts.json",
                          json.dumps(shifts, indent=2, default=str))
                workers = [sh for sh in shifts if "worker" in sh["states"] and sh["href"]]
                if workers:
                    log.info(f"post-mortem: {len(workers)} taken slots seen — "
                             f"URL pattern e.g. {workers[0]['href']}")
            except Exception as e:
                log.warning(f"post-mortem failed: {e}")
    finally:
        if booked is not None:
            rec.meta.booked_status = booked[0]
            rec.meta.booked_message = booked[3]
        rec.finalize()

    if booked is None:
        console.print(Panel(
            f"[bold red]Gave up — no open slots in window.\n"
            f"[/]Forensics in [cyan]{rec.dir}[/] — share that folder to refine for next release.",
            border_style="red"))
        raise typer.Exit(3)

    status, slot_url, day, msg = booked
    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold"); body.add_column()
    body.add_row("status", str(status))
    body.add_row("day",    day or "?")
    body.add_row("slot",   slot_url)
    if msg: body.add_row("message", msg)
    body.add_row("dumps",  str(rec.dir))
    style = "green" if status in (200, 302) else "yellow" if status == "dry-run" else "red"
    console.print(Panel(body, title="[bold]Result", border_style=style))


@app.command()
def scout(
    week: int = typer.Option(..., "--week", "-w"),
    anchor: str = typer.Option("2026-05-07", "--anchor"),
    target: Optional[str] = typer.Option(None, "--target", "-t"),
    dump_dir: Path = typer.Option(Path("./psfc_dumps"), "--dump-dir"),
    user: str = typer.Option(..., envvar="PSFC_USER"),
    password: str = typer.Option(..., envvar="PSFC_PASS",
                                 hide_input=True, prompt=False),
):
    """One-shot recon: log in, fetch the calendar, dump it, summarize shifts.

    Run this AFTER a release if you missed booking — taken slots
    (.shift.worker) leak the slot URL pattern so we can finalize the
    booking POST shape for next time."""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    rec = Recorder(dump_dir, f"scout_w{week}", {
        "command": "scout", "week": week, "anchor": anchor, "target": target,
    })
    cal_url = f"{BASE}/calendar/{week}/0/0/{anchor}/"
    with console.status("[bold green]logging in…"): login(s, user, password)
    r = s.get(cal_url, timeout=10); r.raise_for_status()
    rec.write("calendar.html", r.text)
    csrf = csrf_from(r.text) or s.cookies.get("csrftoken")
    rec.meta.primed_csrf_tail = csrf[-6:] if csrf else None
    rec.meta.primed_session_tail = s.cookies.get("sessionid", "")[-6:]
    log.info(f"primed; csrf …{rec.meta.primed_csrf_tail}, "
             f"sessionid …{rec.meta.primed_session_tail}")
    shifts = harvest_shifts(r.text, target)
    rec.write("shifts.json", json.dumps(shifts, indent=2, default=str))

    # also fetch detail page for first shift we see (open or taken)
    sample = next((sh for sh in shifts if sh["href"]), None)
    if sample:
        log.info(f"sampling detail page → {sample['href']}")
        try:
            rr = s.get(sample["href"], timeout=10)
            rec.write("sample_slot_detail.html", rr.text)
            log.info(f"detail status {rr.status_code} ({len(rr.text)} bytes)")
        except Exception as e:
            log.warning(f"sample fetch failed: {e}")

    # summary table
    t = Table(title=f"Calendar shifts at {cal_url}")
    t.add_column("day"); t.add_column("state"); t.add_column("href")
    for sh in shifts:
        t.add_row(sh["day"], ",".join(sh["states"]) or "open",
                  sh["href"] or "[dim]none[/]")
    console.print(t if shifts else "[yellow]no .shift elements found[/]")
    rec.finalize()


@app.command()
def home(
    dump_dir: Path = typer.Option(Path("./psfc_dumps"), "--dump-dir"),
    user: str = typer.Option(..., envvar="PSFC_USER"),
    password: str = typer.Option(..., envvar="PSFC_PASS",
                                 hide_input=True, prompt=False),
):
    """Recon: log in, fetch the home page, dump it, and surface any
    'Upcoming Orientations' content we can spot heuristically."""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    rec = Recorder(dump_dir, "home", {"command": "home"})
    with console.status("[bold green]logging in…"): login(s, user, password)
    r = s.get(f"{BASE}/home/", timeout=10); r.raise_for_status()
    rec.write("home.html", r.text)
    log.info(f"home {r.status_code} ({len(r.text)} bytes)")

    soup = BeautifulSoup(r.text, "lxml")
    # heuristic 1: anything with text containing "Upcoming" or "Orientation"
    candidates = []
    for el in soup.find_all(string=True):
        t = el.strip()
        if not t: continue
        low = t.lower()
        if "upcoming" in low or "orientation" in low:
            parent = el.parent
            candidates.append({
                "tag": parent.name,
                "classes": parent.get("class", []),
                "text": t[:200],
                "parent_html": str(parent)[:400],
            })
    rec.write("home_text_hits.json",
              json.dumps(candidates, indent=2, default=str))

    # heuristic 2: any element whose tag/class hints at an announcement
    sections = []
    for el in soup.select(
        "[class*=upcoming], [class*=orientation], [class*=announce], "
        "[class*=release], [id*=upcoming], [id*=orientation]"
    ):
        sections.append({
            "tag": el.name, "classes": el.get("class", []),
            "id": el.get("id"),
            "html": str(el)[:800],
        })
    rec.write("home_sections.json",
              json.dumps(sections, indent=2, default=str))

    log.info(f"text hits: {len(candidates)} | classed sections: {len(sections)}")
    if sections:
        for s_ in sections[:5]:
            console.print(Panel(s_["html"], title=f"{s_['tag']}.{'.'.join(s_['classes'])}"))
    rec.finalize()


if __name__ == "__main__":
    app()
