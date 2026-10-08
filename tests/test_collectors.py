"""Collectors end to end against a fake server serving recorded responses."""

from datetime import date

import httpx
import pytest
from conftest import FI_AGGREGATE_ROWS, FI_POSITION_ROWS, fixture_bytes, fixture_json, make_ods

from nordic_signals import cli
from nordic_signals.collectors import COLLECTORS, fi_insider
from nordic_signals.store import Store

NEWSWEB = "https://api3.oslo.oslobors.no/v1/newsreader"
FI_SHORT = "https://www.fi.se/BlankningsRegister"
SSR = "https://ssr.finanstilsynet.no/api/v2/instruments"
STOCKLIST = "https://www.nordnet.no/api/2/instrument_search/query/stocklist"
MFN_FEED = "https://feed.mfn.se/v1/feed/f9cedcd2-6006-4325-bb43-6ffb51e93b6b.json"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart"


def run(source, server, store, **options):
    with server.client() as client:
        return COLLECTORS[source](client, store).run(**options)


def add_newsweb_routes(server, *, overflow_on_unfiltered=False):
    listing = fixture_json("newsweb_list.json")

    def list_handler(request):
        if overflow_on_unfiltered and "category" not in request.url.params:
            first_only = listing["data"]["messages"][:1]
            return httpx.Response(200, json={"data": {"messages": first_only, "overflow": True}})
        category = request.url.params.get("category")
        messages = [m for m in listing["data"]["messages"]
                    if category is None or m["category"][0]["id"] == int(category)]
        return httpx.Response(200, json={"data": {"messages": messages, "overflow": False}})

    def message_handler(request):
        payload = fixture_json("newsweb_message.json")
        payload["data"]["message"]["messageId"] = int(request.url.params["messageId"])
        return httpx.Response(200, json=payload)

    server.add("POST", f"{NEWSWEB}/categories", httpx.Response(200, json=fixture_json("newsweb_categories.json")))
    server.add("GET", f"{NEWSWEB}/list", list_handler)
    server.add("GET", f"{NEWSWEB}/message", message_handler)
    server.add("GET", f"{NEWSWEB}/attachment", httpx.Response(200, content=b"%PDF-1.4 fake"))


def test_newsweb_fetches_details_only_for_key_categories(server, store):
    add_newsweb_routes(server)

    summary = run("newsweb", server, store, start=date(2026, 10, 1), end=date(2026, 10, 1), attachments=True)

    paths = [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in server.requests]
    assert paths.count(("GET", "list")) == 1
    # insider trade (1102) and flagging (1006) get full text; the press release (1104) does not
    detailed = sorted(int(r.url.params["messageId"]) for r in server.requests if r.url.path.endswith("/message"))
    assert detailed == [683454, 683462]
    assert paths.count(("GET", "attachment")) == 2
    assert summary.tables["newsweb_messages"].inserted == 3
    assert store.table_counts()["newsweb_attachments"] == 2

    # A second run re-lists the day but does not re-fetch stored bodies.
    server.requests.clear()
    run("newsweb", server, store, start=date(2026, 10, 1), end=date(2026, 10, 1))
    assert not [r for r in server.requests if r.url.path.endswith("/message")]


def test_newsweb_splits_an_overflowing_day_by_category(server, store):
    add_newsweb_routes(server, overflow_on_unfiltered=True)

    run("newsweb", server, store, start=date(2026, 10, 1), end=date(2026, 10, 1))

    per_category = [r for r in server.requests if r.url.path.endswith("/list") and "category" in r.url.params]
    assert len(per_category) == 25
    assert store.table_counts()["newsweb_messages"] == 3


def test_fi_insider_halves_windows_that_hit_the_row_cap(server, store, monkeypatch):
    monkeypatch.setattr(fi_insider, "ROW_CAP", 3)
    full = fixture_bytes("fi_insider.csv")  # header + 3 rows: "full" at a cap of 3
    header_only = full.decode("utf-16-le").splitlines()[0].encode("utf-16-le")
    windows = []

    def handler(request):
        start, end = request.url.params["Publiceringsdatum.From"], request.url.params["Publiceringsdatum.To"]
        windows.append((start, end))
        return httpx.Response(200, content=full if start != end else header_only)

    server.add("GET", fi_insider.EXPORT_URL, handler)
    summary = run("fi-insider", server, store, start=date(2026, 9, 28), end=date(2026, 10, 1))

    assert windows == [
        ("2026-09-28", "2026-10-01"),
        ("2026-09-28", "2026-09-29"), ("2026-09-28", "2026-09-28"), ("2026-09-29", "2026-09-29"),
        ("2026-09-30", "2026-10-01"), ("2026-09-30", "2026-09-30"), ("2026-10-01", "2026-10-01"),
    ]
    assert summary.warnings == []


def test_fi_short_reads_both_files(server, store):
    server.add("GET", f"{FI_SHORT}/GetAktuellFile", httpx.Response(200, content=make_ods(FI_POSITION_ROWS)))
    server.add("GET", f"{FI_SHORT}/GetBlankningsregisterAggregat",
               httpx.Response(200, content=make_ods(FI_AGGREGATE_ROWS)))

    summary = run("fi-short", server, store)

    assert summary.tables["se_short_positions"].inserted == 2
    assert summary.tables["se_short_aggregate"].inserted == 2


def test_nordnet_pages_through_each_country(server, store):
    page = fixture_json("nordnet_stocklist.json")
    offsets = []

    def handler(request):
        assert request.headers["client-id"] == "NEXT"
        offsets.append((request.url.params["apply_filters"], int(request.url.params["offset"])))
        offset = int(request.url.params["offset"])
        results = page["results"][offset:offset + 1]
        return httpx.Response(200, json={"total_hits": 2, "rows": len(results), "results": results})

    server.add("GET", STOCKLIST, handler)
    run("nordnet", server, store, countries=["NO"], page_size=1)

    assert offsets == [("exchange_country=NO", 0), ("exchange_country=NO", 1)]
    assert store.table_counts()["instruments"] == 2
    assert store.table_counts()["nordnet_observations"] == 2


def test_mfn_resolves_slugs_once_and_caches_misses(server, store):
    page = fixture_bytes("mfn_company_page.html")
    server.add("GET", "https://mfn.se/all/a/nibe-industrier", httpx.Response(200, content=page))
    feed = fixture_json("mfn_feed.json")
    feed["next_url"] = None
    server.add("GET", MFN_FEED, httpx.Response(200, json=feed))

    summary = run("mfn", server, store, slugs=["nibe-industrier", "no-such-company"])

    assert summary.tables["mfn_items"].inserted == 2
    assert summary.warnings == ["no MFN company page found for slug 'no-such-company'"]

    server.requests.clear()
    run("mfn", server, store, slugs=["nibe-industrier", "no-such-company"])
    assert [r.url.host for r in server.requests] == ["feed.mfn.se"]  # both slugs answered from the cache


def test_yahoo_warns_on_bad_symbol_and_continues(server, store):
    server.add("GET", f"{CHART}/MOWI.OL", httpx.Response(200, json=fixture_json("yahoo_chart.json")))
    server.add("GET", f"{CHART}/NOPE.OL",
               httpx.Response(200, json={"chart": {"result": None, "error": {"code": "Not Found"}}}))

    server.add("GET", f"{CHART}/GONE.OL", httpx.Response(404, json={"chart": {"result": None}}))

    summary = run("yahoo", server, store, symbols=["NOPE.OL", "GONE.OL", "MOWI.OL"])

    assert summary.tables["price_bars"].inserted == 2
    assert [w.split(":")[0] for w in summary.warnings] == ["NOPE.OL", "GONE.OL"]  # a 404 does not stop the run


def test_cli_daily_runs_every_source_and_logs_runs(server, db_url, monkeypatch, capsys):
    add_newsweb_routes(server)
    server.add("GET", fi_insider.EXPORT_URL, httpx.Response(200, content=fixture_bytes("fi_insider.csv")))
    server.add("GET", f"{FI_SHORT}/GetAktuellFile", httpx.Response(200, content=make_ods(FI_POSITION_ROWS)))
    server.add("GET", f"{FI_SHORT}/GetBlankningsregisterAggregat",
               httpx.Response(200, content=make_ods(FI_AGGREGATE_ROWS)))
    server.add("GET", SSR, httpx.Response(200, json=fixture_json("ssr_instruments.json")))
    server.add("GET", STOCKLIST,
               httpx.Response(200, json=fixture_json("nordnet_stocklist.json") | {"total_hits": 2}))
    for symbol in ("SEKNOK=X", "OSEBX.OL", "^OMXSBGI"):  # the rate, and the play-money account's yardstick
        server.add("GET", f"{CHART}/{symbol}", httpx.Response(200, json=fixture_json("yahoo_chart.json")))
    monkeypatch.setattr(cli, "PoliteClient", server.client)
    assert cli.main(["--db", db_url, "collect", "daily"]) == 0
    assert cli.main(["--db", db_url, "status"]) == 0

    out = capsys.readouterr().out
    assert "fi-insider: 1 requests; se_insider_trades +3 new" in out
    with Store(db_url) as store:
        runs = {r["source"]: r for r in store.last_runs()}
        assert set(runs) == {"nordnet", "newsweb", "fi-insider", "fi-short", "no-short", "yahoo"}
        assert all(r["ok"] is True for r in runs.values())
        assert runs["no-short"]["summary"]["tables"]["no_short_totals"]["inserted"] == 4


def test_cli_records_failed_runs(server, db_url, monkeypatch):
    server.add("GET", SSR, httpx.Response(500))
    monkeypatch.setattr(cli, "PoliteClient", server.client)

    assert cli.main(["--db", db_url, "collect", "no-short"]) == 1
    with Store(db_url) as store:
        (run_row,) = store.last_runs()
        assert run_row["ok"] is False and "HTTP 500" in run_row["error"]


@pytest.mark.parametrize("source", sorted(COLLECTORS))
def test_every_collector_has_a_source_name(source):
    assert COLLECTORS[source].source == source


def test_cli_refuses_to_run_on_railway_without_a_database(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env-123")

    assert cli.main(["status"]) == 2
    assert not (tmp_path / "data").exists()  # no throwaway SQLite file was created
