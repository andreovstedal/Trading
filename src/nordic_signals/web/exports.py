"""Downloads shared by the pages: CSV for Excel with Norwegian settings, and JSON for analysis in code."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import Any

from .. import text


def filename(kind: str, now: datetime, name: str = "pumpfun-logg") -> str:
    """With the time as well as the date (Oslo), so two downloads on one day are never mixed up."""
    return f"{name}-{now.astimezone(text.OSLO):%Y-%m-%d-%H%M}.{kind}"


def cell(value: Any, digits: int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "ja" if value else "nei"
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(text.OSLO).strftime("%Y-%m-%d %H:%M:%S")
    if digits is not None and isinstance(value, int | float):
        return f"{value:.{digits}f}".replace(".", ",")
    return str(value)


def drain(out: io.StringIO) -> str:
    value = out.getvalue()
    out.seek(0)
    out.truncate()
    return value


def items(encoded: Iterator[str]) -> Iterator[str]:
    """Comma-separated, a few hundred at a time."""
    batch: list[str] = []
    first = True
    for item in encoded:
        batch.append(item)
        if len(batch) == 500:
            yield ("" if first else ",") + "\n" + ",\n".join(batch)
            batch, first = [], False
    if batch:
        yield ("" if first else ",") + "\n" + ",\n".join(batch)


def to_json(value: Any) -> str:
    return json.dumps(value, default=_encode, ensure_ascii=False)


def _encode(value: Any) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")
