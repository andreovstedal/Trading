"""One collector per source; each module's docstring documents its endpoints and terms."""

from .base import Collector, RunSummary
from .fi_insider import FiInsiderCollector
from .fi_short import FiShortCollector
from .mfn import MfnCollector
from .newsweb import NewsWebCollector
from .no_short import NoShortCollector
from .nordnet import NordnetCollector
from .yahoo import YahooCollector

COLLECTORS: dict[str, type[Collector]] = {
    c.source: c
    for c in (
        NewsWebCollector,
        FiInsiderCollector,
        FiShortCollector,
        NoShortCollector,
        MfnCollector,
        YahooCollector,
        NordnetCollector,
    )
}

__all__ = ["COLLECTORS", "Collector", "RunSummary"]
