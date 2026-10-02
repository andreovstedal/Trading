"""Minimal reader for OpenDocument spreadsheets (.ods), standard library only.

Finansinspektionen publishes the Swedish short-selling register as .ods files.
We only need cell values, so a small reader beats depending on pandas + odfpy.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"

# Spreadsheets pad rows and columns with huge "repeated" runs of empty cells.
_MAX_REPEAT = 1000


def read_rows(data: bytes, sheet: int = 0) -> list[list[str]]:
    """Return the non-empty rows of one sheet as lists of strings.

    Numbers and dates come from the typed ``office:value``/``office:date-value``
    attributes when present, so "0.5" is not affected by the display locale.
    Trailing empty cells are dropped.
    """
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("content.xml"))
    tables = list(root.iter(_TABLE + "table"))
    rows: list[list[str]] = []
    for row in tables[sheet].iter(_TABLE + "table-row"):
        cells: list[str] = []
        for cell in row:
            if cell.tag not in (_TABLE + "table-cell", _TABLE + "covered-table-cell"):
                continue
            repeat = min(int(cell.get(_TABLE + "number-columns-repeated", "1")), _MAX_REPEAT)
            cells.extend([_cell_value(cell)] * repeat)
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            repeat = min(int(row.get(_TABLE + "number-rows-repeated", "1")), _MAX_REPEAT)
            rows.extend([list(cells) for _ in range(repeat)])
    return rows


def _cell_value(cell: ET.Element) -> str:
    for attr in ("value", "date-value", "boolean-value"):
        value = cell.get(_OFFICE + attr)
        if value is not None:
            return value
    return "\n".join(_text(p) for p in cell.findall(_TEXT + "p"))


def _text(elem: ET.Element) -> str:
    parts = [elem.text or ""]
    for child in elem:
        if child.tag == _TEXT + "s":
            parts.append(" " * int(child.get(_TEXT + "c", "1")))
        elif child.tag == _TEXT + "tab":
            parts.append("\t")
        elif child.tag == _TEXT + "line-break":
            parts.append("\n")
        else:
            parts.append(_text(child))
        parts.append(child.tail or "")
    return "".join(parts)
