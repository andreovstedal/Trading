import io
import zipfile

from conftest import FI_AGGREGATE_ROWS, make_ods

from nordic_signals.ods import read_rows


def test_reads_rows_and_drops_padding():
    rows = read_rows(make_ods(FI_AGGREGATE_ROWS))

    assert rows[0] == ["Aggregerade positioner"]
    assert rows[3][3] == "Positionsdatum senaste position\n(Position date, latest position)"
    assert rows[4] == [" Svenska Handelsbanken AB", "NHBDILHZTYCNBV5UYZ31", "3.89", "2026-10-02"]
    assert len(rows) == len(FI_AGGREGATE_ROWS)  # the million repeated empty rows are skipped


def test_expands_space_elements_and_repeated_cells():
    content = (
        '<?xml version="1.0"?><office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>'
        '<table:table table:name="s"><table:table-row>'
        '<table:table-cell><text:p>Two<text:s text:c="2"/>Sigma</text:p></table:table-cell>'
        '<table:table-cell table:number-columns-repeated="2"><text:p>x</text:p></table:table-cell>'
        '<table:table-cell office:value-type="date" office:date-value="2026-10-01"><text:p>01.10.26</text:p>'
        "</table:table-cell></table:table-row></table:table></office:spreadsheet></office:body>"
        "</office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", content)

    assert read_rows(buf.getvalue()) == [["Two  Sigma", "x", "x", "2026-10-01"]]
