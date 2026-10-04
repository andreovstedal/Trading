import time
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import seed_universe
from fastapi.testclient import TestClient

from nordic_signals.http import FetchedResponse
from nordic_signals.web import app as web


@pytest.fixture
def make_client(db_url, monkeypatch):
    def make(**env: str) -> TestClient:
        for name in ("APP_PASSWORD", "RAILWAY_ENVIRONMENT_ID", "SECRET_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("SCHEDULER", "off")  # no background collection in tests
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return TestClient(web.create_app(db_url))
    return make


def wait_until_done(client: TestClient, url: str) -> str:
    for _ in range(100):
        page = client.get(url)
        if 'http-equiv="refresh"' not in page.text:
            return page.text
        time.sleep(0.1)
    raise AssertionError("recommendation did not finish")


def test_pages_render_on_an_empty_database(make_client):
    with make_client() as client:
        assert client.get("/health").json() == {"ok": True}
        for path in ("/", "/signals", "/track-record", "/data"):
            response = client.get(path)
            assert response.status_code == 200, path
        assert "Ingen ennå" in client.get("/").text
        assert "Ingenting å måle ennå" in client.get("/track-record").text


def test_password_protects_everything_but_health(make_client):
    with make_client(APP_PASSWORD="s3cret") as client:
        assert client.get("/health").status_code == 200
        response = client.get("/data", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login?next=/data"

        assert client.post("/login", data={"password": "wrong", "next": "/data"}).status_code == 401
        response = client.post("/login", data={"password": "s3cret", "next": "/data"}, follow_redirects=False)
        assert response.headers["location"] == "/data"
        assert client.get("/data").status_code == 200

        client.post("/logout")
        assert client.get("/data", follow_redirects=False).status_code == 303


def test_login_ignores_offsite_redirects(make_client):
    with make_client(APP_PASSWORD="s3cret") as client:
        for target in ("//evil.example", "/\\evil.example", "https://evil.example"):
            response = client.post("/login", data={"password": "s3cret", "next": target}, follow_redirects=False)
            assert response.headers["location"] == "/", target


def test_a_form_sent_after_the_session_expired_returns_to_its_page(make_client):
    # E.g. after a redeploy without SECRET_KEY. The form's own address only accepts the form, so after signing in
    # the browser must go back to the page the form was on.
    with make_client(APP_PASSWORD="s3cret") as client:
        response = client.post("/recommendations", data={"account_value": "300000"},
                               headers={"referer": "http://testserver/"}, follow_redirects=False)
        assert response.headers["location"] == "/login?next=/"
        response = client.post("/data/backfill", headers={"referer": "http://testserver/data"}, follow_redirects=False)
        assert response.headers["location"] == "/login?next=/data"
        response = client.post("/data/backfill", follow_redirects=False)  # no referer
        assert response.headers["location"] == "/login?next=/"


def test_form_addresses_opened_as_pages_lead_to_the_page(make_client):
    with make_client(APP_PASSWORD="s3cret") as client:
        # An old login link still pointing at a form address.
        response = client.post("/login", data={"password": "s3cret", "next": "/recommendations"})
        assert response.status_code == 200 and response.url.path == "/"
        for path, target in (("/recommendations", "/"), ("/data/backfill", "/data"), ("/logout", "/")):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303 and response.headers["location"] == target, path
        # Already signed in: the login page passes straight through.
        assert client.get("/login?next=/data", follow_redirects=False).headers["location"] == "/data"


def test_errors_are_pages_in_norwegian(make_client):
    with make_client() as client:
        response = client.get("/no-such-page")
        assert response.status_code == 404 and "Fant ikke siden" in response.text
        response = client.put("/data")
        assert response.status_code == 405 and "Siden kan ikke åpnes slik" in response.text
        response = client.get("/recommendations/abc")
        assert response.status_code == 400 and "Ugyldig forespørsel" in response.text


def test_railway_refuses_to_serve_without_a_password(make_client):
    with make_client(RAILWAY_ENVIRONMENT_ID="env-1") as client:
        assert client.get("/health").status_code == 200
        response = client.get("/")
        assert response.status_code == 503 and "APP_PASSWORD" in response.text


def test_recommendation_flow(store, make_client):
    seed_universe(store)
    with make_client() as client:
        response = client.post("/recommendations", data={
            "account_value": "200000", "long_pct": "90", "short_pct": "10",
            "max_positions": "4", "min_position": "20000", "paper_short": "on",
        }, follow_redirects=False)
        assert response.status_code == 303
        url = response.headers["location"]

        page = wait_until_done(client, url)
        assert "Langsiktige posisjoner" in page and "AAA Corp" in page
        assert "Nytt tilbakekjøpsprogram annonsert" in page  # BBB, short-term sleeve
        assert "Offentliggjort shortandel økte til 2,2\u00a0%" in page  # AAA, avoid list

        csv = client.get(f"{url}/export.csv")
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        rows = csv.text.strip().splitlines()
        assert rows[0].startswith("\ufeffPlass;Ticker;Navn") and len(rows) == 5  # header + 4 positions
        weight, price = rows[1].split(";")[7:9]
        assert "," in weight and "," in price  # decimal commas, as Excel expects with Norwegian settings

        assert "AAA Corp" in client.get("/stocks/1").text
        assert "Siste anbefalinger" in client.get("/").text


def test_invalid_input_comes_back_as_a_message(make_client):
    with make_client() as client:
        response = client.post("/recommendations", data={
            "account_value": "100000", "long_pct": "90", "short_pct": "20",
        }, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"].startswith("/?error=")
        assert "til sammen utgjøre 100" in client.get(response.headers["location"]).text


def test_unknown_pages_are_404(make_client):
    with make_client() as client:
        assert client.get("/recommendations/999").status_code == 404
        assert client.get("/stocks/999").status_code == 404


def test_stock_page_lists_only_open_short_positions(store, make_client):
    now = seed_universe(store)
    old, new = (now - timedelta(days=60)).date(), (now - timedelta(days=2)).date()

    def fetch(source, url):
        return store.record_fetch(source, FetchedResponse("GET", url, 200, "", url.encode(), now))

    # Norway: each register event lists the positions open at that time; "Old Fund" has since dropped out.
    store.upsert("no_short_positions", [
        {"isin": "NO0000000001", "date": old, "holder": "Old Fund", "position_date": old, "short_pct": 1.0},
        {"isin": "NO0000000001", "date": new, "holder": "New Fund", "position_date": new, "short_pct": 2.2},
    ], fetch_id=fetch("no-short", "https://ssr.finanstilsynet.no/api/v2/instruments"))
    # Sweden: one table holds both FI's history file and its current-positions file.
    store.upsert("se_short_positions", [
        {"holder": "Closed Fund", "isin": "SE0000000010", "position_pct": 0.6, "position_date": old},
    ], fetch_id=fetch("fi-short", "https://www.fi.se/BlankningsRegister/GetHistFile"))
    store.upsert("se_short_positions", [
        {"holder": "Open Fund", "isin": "SE0000000010", "position_pct": 0.7, "position_date": new},
    ], fetch_id=fetch("fi-short", "https://www.fi.se/BlankningsRegister/GetAktuellFile"))

    with make_client() as client:
        norwegian, swedish = client.get("/stocks/1").text, client.get("/stocks/10").text
    assert "New Fund" in norwegian and "Old Fund" not in norwegian
    assert "Open Fund" in swedish and "Closed Fund" not in swedish


def test_signals_page_lists_fresh_events(store, make_client):
    seed_universe(store)
    with make_client() as client:
        page = client.get("/signals").text
        assert "SEC Corp" in page  # Swedish insider purchases
        assert "BBB ASA launches share buyback programme" in page


def test_evaluate_action_runs_in_the_background(make_client):
    with make_client() as client:
        response = client.post("/data/evaluate", follow_redirects=False)
        location = response.headers["location"]
        assert response.status_code == 303 and "Evaluering%20av%20utfall%20har%20startet" in location


@pytest.mark.parametrize("value, expected", [(1234567.4, "1 234 567 NOK"), (None, "–")])
def test_nok_format(value, expected):
    assert web.fmt_nok(value) == expected


def test_norwegian_formats():
    assert web.fmt_pct(0.0534) == "5,3\u00a0%"
    assert web.fmt_pct(0.12, 0, True) == "+12\u00a0%"
    assert web.fmt_num(-0.05, 2, True) == "-0,05"
    assert web.fmt_when(datetime(2026, 10, 2, 4, 38, tzinfo=timezone.utc)) == "2. okt. 2026, 06:38"  # Oslo time
    assert web.fmt_when(datetime(2026, 1, 15, 12, 0)) == "15. jan. 2026, 13:00"  # naive means UTC
    assert web.fmt_day("2026-09-30") == web.fmt_day(date(2026, 9, 30)) == "30. sep. 2026"
    assert web.fmt_day(None) == "–" and web.fmt_ago(None) == "aldri"
    assert web.fmt_label("low_vol") == "Lav volatilitet"
