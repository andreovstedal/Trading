"""Parsers against trimmed copies of real responses captured on 2026-10-02."""

import pytest
from conftest import FI_AGGREGATE_ROWS, FI_POSITION_ROWS, fixture_bytes, fixture_json

from nordic_signals.collectors import fi_insider, fi_short, mfn, newsweb, no_short, nordnet, yahoo


def test_newsweb_list():
    messages, overflow = newsweb.parse_list(fixture_json("newsweb_list.json"))

    assert overflow is False
    assert [m["message_id"] for m in messages] == [683462, 683454, 683463]
    insider = messages[0]
    assert insider["category_ids"] == [1102]
    assert insider["issuer_sign"] == "NOFIN"
    assert insider["published_at"] == "2026-10-01T19:33:50.664Z"
    assert insider["corrected_by_message_id"] is None  # 0 means "none" in the API
    assert insider["num_attachments"] == 1


def test_newsweb_message_detail():
    body, attachments = newsweb.parse_message(fixture_json("newsweb_message.json"))

    assert body["message_id"] == 683462
    assert "purchased 6,737 shares" in body["body"]
    assert attachments == [{"attachment_id": 334111, "name": "Holding 01102026 KRT-1500.pdf"}]


def test_newsweb_categories():
    rows = newsweb.parse_categories(fixture_json("newsweb_categories.json"))

    assert len(rows) == 25
    by_id = {r["category_id"]: r for r in rows}
    assert by_id[1102]["name_no"] == "MELDEPLIKTIG HANDEL FOR PRIMÆRINNSIDERE"
    assert by_id[1006]["name_en"] == "MAJOR SHAREHOLDINGS NOTIFICATION"


def test_fi_insider_export():
    rows = fi_insider.parse_export(fixture_bytes("fi_insider.csv"))

    assert [r["nature"] for r in rows] == ["Förvärv", "Avyttring", "Tilldelning"]
    buy, sell, award = rows
    assert buy["published_at"] == "2026-10-01T20:49:19+02:00"
    assert buy["linked_to_share_program"] is True and buy["is_first_report"] is True
    assert buy["closely_associated"] is None
    assert (buy["volume"], buy["price"]) == (2000.0, 28.9)
    assert sell["isin"] == "SE0010663161" and sell["transaction_date"] == "2026-09-29"
    assert sell["price"] == 64.8 and sell["venue"] == "SPOTLIGHT STOCK MARKET"
    assert award["price"] == 0.0
    assert "\xa0" not in buy["position"]
    assert len({r["row_hash"] for r in rows}) == 3


def test_fi_insider_rejects_unexpected_columns():
    with pytest.raises(ValueError, match="missing columns"):
        fi_insider.parse_export("Datum;Bolag\r\n".encode("utf-16-le"))


def test_fi_short_positions_and_aggregate():
    positions = fi_short.parse_positions(FI_POSITION_ROWS)
    aggregate = fi_short.parse_aggregate(FI_AGGREGATE_ROWS)

    assert positions[0] == {
        "holder": "Two Sigma Investments, LP", "issuer": "Sivers Semiconductors AB",
        "isin": "SE0003917798", "position_pct": 0.5, "position_date": "2026-10-01", "comment": "",
    }
    assert positions[1]["comment"] == "Revised"
    assert aggregate[0] == {
        "issuer": "Svenska Handelsbanken AB", "lei": "NHBDILHZTYCNBV5UYZ31",
        "total_pct": 3.89, "position_date": "2026-10-02",
    }


def test_no_short_register():
    totals, positions = no_short.parse_instruments(fixture_json("ssr_instruments.json"))

    assert len(totals) == 4 and len(positions) == 5
    assert totals[0] == {"isin": "BMG9156K1018", "date": "2026-09-30", "issuer_name": "2020 BULKERS",
                         "short_pct": 1.8, "short_shares": 413635}
    assert positions[0]["holder"] == "GSA CAPITAL PARTNERS LLP"
    assert positions[0]["position_date"] == "2026-09-30"


def test_mfn_feed_and_entity_lookup():
    items, next_url = mfn.parse_feed(fixture_json("mfn_feed.json"))

    assert next_url and "offset=" in next_url
    first = items[0]
    assert first["entity_id"] == "f9cedcd2-6006-4325-bb43-6ffb51e93b6b"
    assert first["isins"] == ["SE0015988019"]
    assert first["tickers"][0] == "XSTO:NIBE B"
    assert first["publish_date"] == "2026-08-21T06:02:00Z"
    assert first["lang"] == "en" and "sub:ci" in first["tags"]

    html = fixture_bytes("mfn_company_page.html").decode()
    assert mfn.parse_entity_id(html) == "f9cedcd2-6006-4325-bb43-6ffb51e93b6b"
    assert mfn.parse_entity_id("<html>nothing here</html>") is None


@pytest.mark.parametrize("name, expected", [
    ("NIBE Industrier AB", ["nibe-industrier-ab", "nibe-industrier"]),
    ("Sinch AB (publ)", ["sinch-ab-publ", "sinch"]),
    ("Höegh Autoliners ASA", ["hoegh-autoliners-asa", "hoegh-autoliners"]),
    ("AAK", ["aak"]),
])
def test_mfn_slug_candidates(name, expected):
    assert mfn.slug_candidates(name) == expected


def test_yahoo_chart():
    bars, dividends, splits = yahoo.parse_chart(fixture_json("yahoo_chart.json"))

    # Of the last four bars, two are null-priced: the newest day on a long range and a padded gap.
    assert len(bars) == 2
    assert {b["symbol"] for b in bars} == {"MOWI.OL"}
    assert bars[0]["interval"] == "1d" and bars[0]["currency"] == "NOK"
    assert all(b["close"] is not None and b["adjclose"] is not None for b in bars)
    assert len(dividends) == 1 and dividends[0]["amount"] > 0
    assert splits == []


def test_yahoo_chart_error():
    with pytest.raises(ValueError):
        yahoo.parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})


def test_yahoo_symbols():
    assert yahoo.yahoo_symbol("VOLV B", "SE") == "VOLV-B.ST"
    assert yahoo.yahoo_symbol("EQNR", "NO") == "EQNR.OL"


def test_nordnet_stocklist():
    instruments, observations = nordnet.parse_stocklist(fixture_json("nordnet_stocklist.json"),
                                                        "2026-10-02T04:00:00.000Z")

    assert len(instruments) == len(observations) == 2
    eqnr = instruments[0]
    assert (eqnr["symbol"], eqnr["isin"], eqnr["exchanges"]) == ("EQNR", "NO0010096985", ["Euronext Oslo"])
    assert eqnr["is_tradable"] is True
    obs = observations[0]
    assert obs["number_of_owners"] == 45182
    assert obs["statistics_at"] == "2026-10-01T17:52:39.513Z"
    assert (obs["last"], obs["bid"], obs["ask"]) == (401.8, 393.5, 402.0)
    assert obs["report_date"] == "2026-10-28"  # local-midnight epoch ms -> Oslo date
    assert obs["ex_date"] == "2026-11-13"
    assert obs["report_type"] == "THIRD_QUARTER_EARNINGS_RESULTS"
