"""Pushing the small pump.fun log to a GitHub branch."""

import base64
import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx

from nordic_signals import logpush, scheduler

REPO = "https://api.github.com/repos/owner/trading"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class GitHub:
    """Answers the Git Data API calls and keeps what was sent."""

    def __init__(self, server, *, branch_exists):
        self.sent, self.branch_exists = [], branch_exists
        for method, path, sha in (("POST", "/git/blobs", "blob1"), ("POST", "/git/trees", "tree1"),
                                  ("POST", "/git/commits", "commit1"), ("POST", "/git/refs", None)):
            server.add(method, REPO + path, self.answer(path, sha))
        server.add("PATCH", REPO + "/git/refs/heads/pumpfun-logg", self.answer("update", None))

    def answer(self, path, sha):
        def handle(request):
            self.sent.append((path, request.headers["authorization"], json.loads(request.content)))
            if path == "update" and not self.branch_exists:
                return httpx.Response(422, json={"message": "Reference does not exist"})
            return httpx.Response(201 if sha else 200, json={"sha": sha} if sha else {})
        return handle


def test_the_log_replaces_the_branch(server, store):
    github = GitHub(server, branch_exists=True)
    with server.client() as client:
        sha = logpush.push(store, client, token="secret", repo="owner/trading", branch="pumpfun-logg", now=NOW)

    assert sha == "commit1"
    assert [path for path, _, _ in github.sent] == ["/git/blobs", "/git/trees", "/git/commits", "update"]
    assert all(auth == "Bearer secret" for _, auth, _ in github.sent)
    blob, tree, commit, update = (body for _, _, body in github.sent)
    log = json.loads(gzip.decompress(base64.b64decode(blob["content"])))
    assert list(log) == ["meta", "funnel", "tokens", "trades", "equity"]
    assert [entry["path"] for entry in tree["tree"]] == ["pumpfun-analyse.json.gz", "README.md"]
    assert commit["parents"] == [] and commit["tree"] == "tree1"  # the branch's only commit
    assert update == {"sha": "commit1", "force": True}


def test_the_branch_is_created_the_first_time(server, store):
    github = GitHub(server, branch_exists=False)
    with server.client() as client:
        logpush.push(store, client, token="secret", repo="owner/trading", branch="pumpfun-logg", now=NOW)
    assert github.sent[-1][0] == "/git/refs" and github.sent[-1][2] == {"ref": "refs/heads/pumpfun-logg",
                                                                        "sha": "commit1"}


def test_the_push_runs_hourly_once_set_up(store, monkeypatch):
    for name in ("GITHUB_TOKEN", "LOG_REPO", "LOG_BRANCH"):
        monkeypatch.delenv(name, raising=False)
    (job,) = [j for j in scheduler.JOBS if j.name == "pumpfun-log"]
    assert logpush.settings({}) is None and not job.is_due(store, job.name, NOW)

    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("LOG_REPO", "owner/trading")
    assert logpush.settings({"GITHUB_TOKEN": "secret", "LOG_REPO": "owner/trading"})["branch"] == "pumpfun-logg"
    assert job.is_due(store, job.name, NOW)
    with store.engine.begin() as conn:
        conn.execute(store.table("schedule").insert().values(job="pumpfun-log", started_at=NOW, ok=True,
                                                             finished_at=NOW))
    assert not job.is_due(store, job.name, NOW + timedelta(minutes=30))
    assert job.is_due(store, job.name, NOW + timedelta(hours=1))
