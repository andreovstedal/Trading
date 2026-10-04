"""The collection schedule run inside the web service."""

from datetime import datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import insert, select

from nordic_signals import scheduler
from nordic_signals.scheduler import Job, Scheduler

MONDAY = datetime(2026, 10, 5, tzinfo=timezone.utc)


def at(day, hour, minute=0):
    return day.replace(hour=hour, minute=minute)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class NoNetwork:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def add_run(store, source, started, minutes=1.0, ok=True):
    finished = None if ok is None else started + timedelta(minutes=minutes)
    with store.engine.begin() as conn:
        conn.execute(insert(store.table("runs")).values(source=source, started_at=started, finished_at=finished, ok=ok))


def due(store, now):
    return [job.name for job in scheduler.JOBS if job.is_due(store, job.name, now)]


PUMPFUN = ["pumpfun", "pumpfun-quotes"]


def test_jobs_due_through_a_weekday(store):
    assert due(store, at(MONDAY, 3)) == PUMPFUN
    assert due(store, at(MONDAY, 12)) == [*PUMPFUN, "intraday"]
    assert due(store, at(MONDAY, 20, 31)) == [*PUMPFUN, "nightly", "lekepenger"]
    assert due(store, at(MONDAY, 21, 31)) == [*PUMPFUN, "nightly", "lekepenger", "mfn", "prices"]
    assert due(store, at(MONDAY + timedelta(days=5), 21, 31)) == PUMPFUN  # Saturday


def test_what_already_ran_is_not_repeated(store, monkeypatch):
    monkeypatch.setattr(scheduler, "JOBS", [job for job in scheduler.JOBS if job.name != "pumpfun-quotes"])
    now = at(MONDAY, 21, 40)
    add_run(store, "pumpfun", now - timedelta(minutes=2))
    add_run(store, "no-short", at(MONDAY, 20, 30))  # the nightly set, from a cron service
    add_run(store, "lekepenger", at(MONDAY, 20, 35))
    add_run(store, "mfn", at(MONDAY, 21, 0))
    add_run(store, "yahoo", at(MONDAY, 21, 35), minutes=0.1)  # the quick SEK/NOK refresh is not the price job
    assert due(store, now) == ["prices"]

    add_run(store, "yahoo", at(MONDAY, 21, 30), ok=None)  # prices for every share, still running
    assert due(store, now) == []
    assert due(store, now + timedelta(minutes=3)) == ["pumpfun"]


def test_a_failed_daily_job_is_retried_after_an_hour(store, monkeypatch):
    outcomes = [False, True]
    job = Job("nightly", "nordic", scheduler.daily(time(20, 30), done=scheduler.ran("no-short")),
              lambda _store, _client: outcomes.pop(0))
    monkeypatch.setattr(scheduler, "JOBS", [job])
    clock = Clock(at(MONDAY, 20, 31))
    schedule = Scheduler(store, client_factory=NoNetwork, clock=clock)

    assert schedule.run_due("nordic") == ["nightly"]  # fails
    clock.now = at(MONDAY, 21, 0)
    assert schedule.run_due("nordic") == []
    clock.now = at(MONDAY, 21, 32)
    assert schedule.run_due("nordic") == ["nightly"]  # retried, and succeeds
    clock.now = at(MONDAY, 23, 0)
    assert schedule.run_due("nordic") == []
    (attempt,) = store.query(select(store.table("schedule")))
    assert attempt["ok"] is True and attempt["job"] == "nightly"


def test_the_play_money_account_is_logged_like_a_collector(store, monkeypatch):
    monkeypatch.setattr(scheduler.paper, "decide", lambda _store: {"ok": False, "note": "Mangler sluttkurser fra i dag"})
    assert scheduler._paper(store, NoNetwork()) is False  # so the schedule tries again in an hour
    (run,) = store.query(select(store.table("runs")))
    assert (run["source"], run["ok"], run["error"]) == ("lekepenger", False, "Mangler sluttkurser fra i dag")


def test_nordic_jobs_wait_while_the_web_page_runs_a_job(store, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "JOBS", [
        Job("pumpfun", "pumpfun", lambda *_: True, lambda *_: calls.append("pumpfun") or True),
        Job("nightly", "nordic", lambda *_: True, lambda *_: calls.append("nightly") or True),
    ])
    schedule = Scheduler(store, busy=lambda: True, client_factory=NoNetwork)
    assert schedule.run_due("nordic") == []
    assert schedule.run_due("pumpfun") == ["pumpfun"]  # pump.fun does not wait
    assert calls == ["pumpfun"]


def test_cleanup_marks_interrupted_runs(store):
    now = at(MONDAY, 12)
    add_run(store, "yahoo", now - timedelta(hours=4), ok=None)  # cut off by a restart
    add_run(store, "nordnet", now - timedelta(minutes=10), ok=None)  # may still be running elsewhere
    with store.engine.begin() as conn:
        conn.execute(insert(store.table("schedule")).values(job="prices", started_at=now - timedelta(hours=1)))

    Scheduler(store, clock=lambda: now).cleanup()

    runs = {r["source"]: r for r in store.query(select(store.table("runs")))}
    assert runs["yahoo"]["ok"] is False and runs["yahoo"]["error"] == scheduler.INTERRUPTED
    assert runs["nordnet"]["ok"] is None
    (attempt,) = store.query(select(store.table("schedule")))
    assert attempt["ok"] is False


@pytest.mark.parametrize("env, expected", [
    ({}, False),
    ({"RAILWAY_ENVIRONMENT_ID": "env-1"}, True),
    ({"RAILWAY_ENVIRONMENT_ID": "env-1", "SCHEDULER": "off"}, False),
    ({"SCHEDULER": "on"}, True),
])
def test_on_by_default_on_railway(env, expected):
    assert scheduler.enabled(env) is expected


def test_the_pumpfun_job_runs_the_collector(server, store, monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    server.add("GET", "https://frontend-api-v3.pump.fun/coins", httpx.Response(200, json=[]))
    monkeypatch.setattr(scheduler, "JOBS", [job for job in scheduler.JOBS if job.name == "pumpfun"])

    assert Scheduler(store, client_factory=server.client).run_due("pumpfun") == ["pumpfun"]

    (run,) = store.last_runs()
    assert run["source"] == "pumpfun" and run["ok"] is True


def test_quotes_run_every_minute_without_logging_runs(store, monkeypatch):
    quoted = []
    monkeypatch.setattr(scheduler.PumpFunCollector, "quote", lambda self: quoted.append(self) or 0)
    monkeypatch.setattr(scheduler, "JOBS", [job for job in scheduler.JOBS if job.name == "pumpfun-quotes"])
    clock = Clock(at(MONDAY, 12))
    schedule = Scheduler(store, client_factory=NoNetwork, clock=clock)

    assert schedule.run_due("pumpfun") == ["pumpfun-quotes"]
    clock.now += timedelta(seconds=scheduler.TICK)  # the next check: too soon
    assert schedule.run_due("pumpfun") == []
    clock.now += timedelta(seconds=scheduler.TICK)
    assert schedule.run_due("pumpfun") == ["pumpfun-quotes"]
    assert len(quoted) == 2 and store.last_runs() == []
