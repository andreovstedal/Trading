"""The collection schedule, run inside the web service.

The web service on Railway is always on, so it runs the collectors itself; no separate cron service is
needed. Two background threads:

* **pump.fun:** the pump.fun measurement every 5 minutes, around the clock.
* **Nordic:** the share collectors on weekdays (times in UTC):

  * intraday every 15 minutes from 05:00 to 18:59: new Oslo announcements and Swedish insider trades
  * nightly from 20:30: the daily set, then outcomes for past recommendations
  * MFN from 21:00: Swedish press releases
  * prices from 21:30: Yahoo end-of-day prices for every share, about 90 minutes

  These wait while a job started from the web page is running.

A job is due when the ``runs`` log shows it hasn't run recently. Whatever already ran, from this schedule,
a button on the Data page or a separate cron service, is not repeated, and a job missed while the service
was down runs once it is back (the same evening for the daily jobs). A daily job that failed is retried
after an hour. Runs cut off by a restart are marked as interrupted.

On by default on Railway. Set SCHEDULER=off to turn it off, or SCHEDULER=on to run it elsewhere.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update

from . import jobs
from .advisor import evaluate as evaluation
from .http import PoliteClient
from .store import Store, utcnow

log = logging.getLogger(__name__)

TICK = 30.0  # seconds between checks
RETRY_AFTER = timedelta(hours=1)
INTERRUPTED_AFTER = timedelta(hours=3)  # no run takes this long; an unfinished one was cut off
CLEANUP_EVERY = timedelta(hours=1)
INTERRUPTED = "Avbrutt (tjenesten startet på nytt)"

IsDue = Callable[[Store, str, datetime], bool]


@dataclass(frozen=True)
class Job:
    name: str
    lane: str  # "pumpfun" or "nordic": jobs in one lane run one after another
    is_due: IsDue
    run: Callable[[Store, PoliteClient], bool]  # True if every collector succeeded


def enabled(env: Mapping[str, str]) -> bool:
    default = "on" if env.get("RAILWAY_ENVIRONMENT_ID") else "off"
    return env.get("SCHEDULER", default).strip().lower() in ("on", "1", "true", "yes")


class Scheduler:
    def __init__(self, store: Store, *, busy: Callable[[], bool] = lambda: False,
                 client_factory: Callable[[], PoliteClient] = PoliteClient,
                 clock: Callable[[], datetime] = utcnow):
        self.store = store
        self.busy = busy
        self.client_factory = client_factory
        self.clock = clock
        self._stop = threading.Event()
        self._last_cleanup: datetime | None = None

    def start(self) -> None:
        self.cleanup()
        for lane in ("pumpfun", "nordic"):
            threading.Thread(target=self._loop, args=(lane,), name=f"schedule-{lane}", daemon=True).start()
        log.info("collection schedule started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self, lane: str) -> None:
        while not self._stop.is_set():
            try:
                if lane == "nordic" and self.clock() - (self._last_cleanup or self.clock()) >= CLEANUP_EVERY:
                    self.cleanup()
                self.run_due(lane)
            except Exception:  # keep the schedule alive; the next check tries again
                log.exception("schedule %s failed", lane)
            self._stop.wait(TICK)

    def run_due(self, lane: str) -> list[str]:
        """Run the jobs in ``lane`` that are due now, one after another; returns their names."""
        ran = []
        for job in JOBS:
            if job.lane != lane or self._stop.is_set():
                continue
            if lane == "nordic" and self.busy():
                break  # a job from the web page is running; the next check tries again
            if job.is_due(self.store, job.name, self.clock()):
                self._run(job)
                ran.append(job.name)
        return ran

    def _run(self, job: Job) -> None:
        s = self.store.table("schedule")
        with self.store.engine.begin() as conn:
            conn.execute(self.store._insert(s).values(job=job.name, started_at=self.clock())
                         .on_conflict_do_update(index_elements=["job"],
                                                set_={"started_at": self.clock(), "finished_at": None,
                                                      "ok": None, "error": None}))
        ok, error = False, None
        try:
            with self.client_factory() as client:
                ok = job.run(self.store, client)
        except Exception as exc:
            log.exception("scheduled job %s failed", job.name)
            error = f"{type(exc).__name__}: {exc}"
        with self.store.engine.begin() as conn:
            conn.execute(update(s).where(s.c.job == job.name).values(finished_at=self.clock(), ok=ok, error=error))

    def cleanup(self) -> None:
        """Mark runs and attempts cut off by a restart (or a crashed job) as interrupted."""
        now = self.clock()
        runs, s = self.store.table("runs"), self.store.table("schedule")
        with self.store.engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.finished_at.is_(None),
                                            runs.c.started_at < now - INTERRUPTED_AFTER)
                         .values(finished_at=now, ok=False, error=INTERRUPTED))
            if self._last_cleanup is None:  # at start, any unfinished attempt belonged to the old process
                conn.execute(update(s).where(s.c.finished_at.is_(None)).values(finished_at=now, ok=False,
                                                                                error=INTERRUPTED))
        self._last_cleanup = now


# When jobs are due

def every(interval: timedelta, *, source: str, weekdays: bool = False,
          hours: tuple[int, int] | None = None) -> IsDue:
    """Due when ``source`` has not run for ``interval`` (minus one check, so the pace holds)."""
    def is_due(store: Store, job: str, now: datetime) -> bool:
        if weekdays and now.weekday() >= 5:
            return False
        if hours and not hours[0] <= now.hour < hours[1]:
            return False
        recent = [t for t in (_latest_run(store, source), _attempt(store, job).get("started_at")) if t]
        return not recent or now - max(recent) >= interval - timedelta(seconds=TICK)
    return is_due


def daily(at: time, *, done: Callable[[Store, datetime], bool]) -> IsDue:
    """Due once a weekday from ``at``, unless ``done`` finds it already ran (a cron service, a button)."""
    def is_due(store: Store, job: str, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        opens = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if now < opens:
            return False
        since = opens - timedelta(minutes=30)  # a cron service starting right on time counts
        attempt = _attempt(store, job)
        if attempt.get("started_at") and attempt["started_at"] >= since:  # this schedule tried today
            if attempt["ok"] is False:
                return now - attempt["started_at"] >= RETRY_AFTER
            return False  # done, or still running
        return not done(store, since)
    return is_due


def ran(source: str) -> Callable[[Store, datetime], bool]:
    def done(store: Store, since: datetime) -> bool:
        runs = store.table("runs")
        return bool(store.scalar(select(func.count()).select_from(runs)
                                 .where(runs.c.source == source, runs.c.started_at >= since)))
    return done


def universe_prices(store: Store, since: datetime) -> bool:
    """A Yahoo run for every share, as opposed to the quick SEK/NOK refresh: still running, long, or failed."""
    runs = store.table("runs")
    for r in store.query(select(runs.c.started_at, runs.c.finished_at, runs.c.ok)
                         .where(runs.c.source == "yahoo", runs.c.started_at >= since)):
        if r["ok"] is not True or r["finished_at"] is None:
            return True
        if _aware(r["finished_at"]) - _aware(r["started_at"]) >= timedelta(minutes=5):
            return True
    return False


def _latest_run(store: Store, source: str) -> datetime | None:
    runs = store.table("runs")
    return _aware(store.scalar(select(func.max(runs.c.started_at)).where(runs.c.source == source)))


def _attempt(store: Store, job: str) -> dict[str, Any]:
    s = store.table("schedule")
    rows = store.query(select(s).where(s.c.job == job))
    return {**rows[0], "started_at": _aware(rows[0]["started_at"])} if rows else {}


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# What the jobs run (the same as the CLI commands in the README)

def _source(source: str, **raw: Any) -> Callable[[Store, PoliteClient], bool]:
    def run(store: Store, client: PoliteClient) -> bool:
        return jobs.run_source(store, client, source, **jobs.options_for(store, source, raw)) is not None
    return run


def _set(name: str, *, then_evaluate: bool = False) -> Callable[[Store, PoliteClient], bool]:
    def run(store: Store, client: PoliteClient) -> bool:
        ok = all(summary is not None for _, summary in jobs.run_set(store, client, name))
        if then_evaluate:
            evaluation.evaluate(store)
        return ok
    return run


JOBS = [
    Job("pumpfun", "pumpfun", every(timedelta(minutes=5), source="pumpfun"), _source("pumpfun")),
    Job("intraday", "nordic", every(timedelta(minutes=15), source="newsweb", weekdays=True, hours=(5, 19)),
        _set("intraday")),
    Job("nightly", "nordic", daily(time(20, 30), done=ran("no-short")), _set("daily", then_evaluate=True)),
    Job("mfn", "nordic", daily(time(21, 0), done=ran("mfn")),
        _source("mfn", universe=["SE"], days=3, max_pages=1)),
    Job("prices", "nordic", daily(time(21, 30), done=universe_prices),
        _source("yahoo", universe=["NO", "SE"], range_="5d")),
]
