"""Pushes the small pump.fun analysis log to a branch on GitHub, so it can be read straight from the
repository instead of being downloaded and sent on.

Set on the web service:

* ``GITHUB_TOKEN``: a fine-grained GitHub token for the repository, with Contents: read and write;
* ``LOG_REPO``: the repository, ``owner/name``;
* ``LOG_BRANCH`` (optional): the branch, ``pumpfun-logg`` by default.

Every hour the schedule writes the analysis log (``web.pumpfun_page.export_analysis_json``), gzipped, as the
branch's only commit. The branch is replaced each time rather than added to, so the repository does not
grow with every copy, and it holds no code, so Railway (which deploys the code branch) does not redeploy.

It goes through GitHub's Git Data API (blob, tree, commit, ref), so the service needs no git or ssh.
"""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .http import PoliteClient
from .store import Store, utcnow
from .web import pumpfun_page

API = "https://api.github.com"
DEFAULT_BRANCH = "pumpfun-logg"
FILE = "pumpfun-analyse.json.gz"
README = """# pump.fun log

Written by the Nordic signals web service every hour: `pumpfun-analyse.json.gz` is the small analysis log
from the pump.fun page (every measured token, the counts of the rest, the three fake accounts, the main
account's value and the price paths of the tokens that passed). The branch is replaced each time, so it only
ever holds the latest copy.

    git fetch origin pumpfun-logg
    git show origin/pumpfun-logg:pumpfun-analyse.json.gz | gunzip > pumpfun-analyse.json
"""


def settings(env: Mapping[str, str]) -> dict[str, str] | None:
    """The push's settings, or None when it is not set up."""
    token, repo = env.get("GITHUB_TOKEN", "").strip(), env.get("LOG_REPO", "").strip()
    if not token or not repo:
        return None
    return {"token": token, "repo": repo, "branch": env.get("LOG_BRANCH", "").strip() or DEFAULT_BRANCH}


def push(store: Store, client: PoliteClient, *, token: str, repo: str, branch: str,
         now: datetime | None = None) -> str:
    """Write the log as the branch's only commit, creating the branch if needed; returns the commit."""
    now = now or utcnow()
    log = "".join(pumpfun_page.export_analysis_json(store, now)).encode()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}

    def call(method: str, path: str, payload: dict[str, Any], allow: tuple[int, ...] = ()) -> tuple[int, Any]:
        resp = client.request(method, f"{API}/repos/{repo}{path}", headers=headers, content=json.dumps(payload),
                              allow_status=allow)
        return resp.status, json.loads(resp.body or b"{}")

    _, blob = call("POST", "/git/blobs", {"content": base64.b64encode(gzip.compress(log)).decode(),
                                          "encoding": "base64"})
    _, tree = call("POST", "/git/trees", {"tree": [
        {"path": FILE, "mode": "100644", "type": "blob", "sha": blob["sha"]},
        {"path": "README.md", "mode": "100644", "type": "blob", "content": README},
    ]})
    _, commit = call("POST", "/git/commits", {"message": f"pump.fun log, {now:%Y-%m-%d %H:%M} UTC",
                                              "tree": tree["sha"], "parents": []})
    status, _ = call("PATCH", f"/git/refs/heads/{branch}", {"sha": commit["sha"], "force": True}, allow=(404, 422))
    if status in (404, 422):  # the branch does not exist yet
        call("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    return commit["sha"]
