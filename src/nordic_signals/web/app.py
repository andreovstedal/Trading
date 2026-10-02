"""The web app: account value in, suggested split out, with every recommendation logged.

Single-user by design. Set APP_PASSWORD to require a login (mandatory on
Railway) and SECRET_KEY to keep sessions valid across restarts.
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Undefined
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .. import jobs, text
from ..advisor import MODEL_VERSION, Policy, recommend
from ..advisor import evaluate as evaluation
from ..http import PoliteClient
from ..store import Store
from . import queries

log = logging.getLogger("nordic_signals.web")

HERE = Path(__file__).parent
OPEN_PATHS = ("/health", "/login", "/static/")


class Runner:
    """Runs one long job at a time (a recommendation, a refresh or a backfill) in a background thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current: str | None = None
        self.started: float | None = None

    def start(self, label: str, job: Callable[[], Any]) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self.current, self.started = label, time.monotonic()

        def target() -> None:
            try:
                job()
            except Exception:
                log.exception("%s failed", label)
            finally:
                self.current, self.started = None, None
                self._lock.release()

        threading.Thread(target=target, name=label, daemon=True).start()
        return True


def create_app(db: str | None = None) -> FastAPI:
    store = Store(db)
    runner = Runner()
    password = os.environ.get("APP_PASSWORD")
    on_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT_ID"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN202
        yield
        store.close()

    app = FastAPI(title="Nordic signals", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.runner = store, runner
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(nok=fmt_nok, pct=fmt_pct, points=fmt_points, num=fmt_num, when=fmt_when,
                                 day=fmt_day, ago=fmt_ago, label=fmt_label)
    templates.env.globals.update(model_version=MODEL_VERSION, runner=runner, auth_enabled=bool(password))
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.middleware("http")
    async def require_login(request: Request, call_next):  # noqa: ANN001, ANN202
        path = request.url.path
        if path.startswith(OPEN_PATHS):
            return await call_next(request)
        if on_railway and not password:
            return templates.TemplateResponse(request, "error.html", {
                "title": "Sett et passord først",
                "message": "Appen er tilgjengelig fra internett. Legg til variabelen APP_PASSWORD (og SECRET_KEY)"
                           " på web-tjenesten i Railway, og deploy på nytt.",
            }, status_code=503)
        if password and not request.session.get("signed_in"):
            return RedirectResponse(f"/login?next={quote(_return_path(request))}", status_code=303)
        return await call_next(request)

    # Added last so it wraps the login check and request.session is available there.
    app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
                       same_site="lax", https_only=on_railway, max_age=30 * 24 * 3600)

    def render(request: Request, name: str, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context)

    def refresh_data() -> dict[str, Any]:
        with PoliteClient() as client:
            results = jobs.run_set(store, client, "refresh")
        return {source: (summary.as_dict() if summary else "failed") for source, summary in results}

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/") -> Response:
        if request.session.get("signed_in"):
            return RedirectResponse(_safe_next(next), 303)
        return render(request, "login.html", next=next, error=None)

    @app.post("/login")
    def login(request: Request, password_input: str = Form(alias="password"), next: str = Form("/")) -> Response:
        if password and hmac.compare_digest(password_input.encode(), password.encode()):
            request.session["signed_in"] = True
            return RedirectResponse(_safe_next(next), 303)
        time.sleep(1)  # slow down guessing
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": "Feil passord"},
                                          status_code=401)

    @app.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", 303)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, error: str | None = None) -> HTMLResponse:
        statuses = queries.source_status(store)
        return render(request, "dashboard.html", policy=queries.last_policy(store) or Policy(300_000).as_dict(),
                      recommendations=queries.recent_recommendations(store), statuses=statuses,
                      stale=queries.stale_sources(statuses), error=error)

    @app.post("/recommendations")
    def create_recommendation(
        request: Request,
        account_value: float = Form(...),
        long_pct: float = Form(85.0),
        short_pct: float = Form(10.0),
        cash_pct: float = Form(5.0),
        max_positions: int = Form(12),
        min_position: float = Form(20_000.0),
        ask_only: bool = Form(False),
        paper_short: bool = Form(False),
        refresh: bool = Form(False),
    ) -> Response:
        try:
            policy = Policy(account_value=account_value, long_pct=long_pct, short_pct=short_pct, cash_pct=cash_pct,
                            max_positions=max_positions, min_position=min_position, ask_only=ask_only,
                            short_paper_only=paper_short)
        except ValueError as exc:
            return RedirectResponse(f"/?error={quote(str(exc))}", 303)
        if runner.current:
            return RedirectResponse(f"/?error={quote(f'Opptatt: {runner.current} pågår fortsatt')}", 303)
        rec_id = recommend.create(store, policy)
        started = runner.start(f"Anbefaling {rec_id}",
                               lambda: recommend.run(store, rec_id, refresh=refresh_data if refresh else None))
        if not started:
            return RedirectResponse(f"/?error={quote('En annen jobb startet akkurat; prøv igjen om litt')}", 303)
        return RedirectResponse(f"/recommendations/{rec_id}", 303)

    @app.get("/recommendations/{rec_id}", response_class=HTMLResponse)
    def recommendation(request: Request, rec_id: int) -> HTMLResponse:
        rec = store.get("recommendations", id=rec_id)
        if rec is None:
            return render_error(request, "Fant ikke siden", f"Det finnes ingen anbefaling nr. {rec_id}.", 404)
        lines = queries.recommendation_lines(store, rec_id) if rec["status"] == "done" else []
        picks = [line for line in lines if line["long_shares"]]
        eligible = [line for line in lines if line["eligible"]]
        runners_up = [line for line in eligible if not line["long_shares"]][:8]
        return render(request, "recommendation.html", rec=rec, picks=picks, runners_up=runners_up,
                      signals=queries.short_signal_lines(store, rec_id) if lines else [],
                      exclusions=queries.exclusion_counts(lines), universe=len(lines), eligible=len(eligible))

    @app.get("/recommendations/{rec_id}/export.csv")
    def recommendation_csv(rec_id: int) -> PlainTextResponse:
        # Semicolons, decimal commas and a byte-order mark, so Excel with Norwegian settings opens it directly.
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(["Plass", "Ticker", "Navn", "ISIN", "Land", "Antall", "Beløp (NOK)", "Vekt", "Kurs",
                         "Valuta", "Poeng", "Begrunnelse"])
        for line in queries.recommendation_lines(store, rec_id):
            if line["long_shares"]:
                writer.writerow([line["rank"], line["symbol"], line["name"], line["isin"], line["country"],
                                 line["long_shares"], round(line["long_amount"]), _decimal(line["long_weight"], 4),
                                 _decimal(line["ref_price"], 2), line["currency"], _decimal(line["score"], 3),
                                 " | ".join(line["reasons"] or [])])
        return PlainTextResponse("\ufeff" + out.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="anbefaling-{rec_id}.csv"'})

    @app.get("/stocks/{instrument_id}", response_class=HTMLResponse)
    def stock(request: Request, instrument_id: int) -> HTMLResponse:
        page = queries.stock_page(store, instrument_id)
        if page is None:
            return render_error(request, "Fant ikke siden", "Aksjen finnes ikke i det lagrede universet.", 404)
        return render(request, "stock.html", **page)

    @app.get("/signals", response_class=HTMLResponse)
    def signals(request: Request) -> HTMLResponse:
        return render(request, "signals.html", groups=queries.signals(store))

    @app.get("/track-record", response_class=HTMLResponse)
    def track_record(request: Request) -> HTMLResponse:
        return render(request, "track_record.html", record=evaluation.track_record(store))

    @app.get("/data", response_class=HTMLResponse)
    def data(request: Request, message: str | None = None) -> HTMLResponse:
        return render(request, "data.html", statuses=queries.source_status(store), counts=store.table_counts(),
                      backfill=queries.backfill_summary(), message=message)

    @app.post("/data/{action}")
    def data_action(action: str) -> RedirectResponse:
        def run_set(name: str) -> Callable[[], None]:
            def job() -> None:
                with PoliteClient() as client:
                    jobs.run_set(store, client, name)
            return job

        actions = {
            "refresh": ("Oppdatering av data", run_set("refresh")),
            "backfill": ("Henting av historikk", run_set("backfill")),
            "evaluate": ("Evaluering av utfall", lambda: evaluation.evaluate(store)),
        }
        if action not in actions:
            return RedirectResponse("/data", 303)
        label, job = actions[action]
        started = runner.start(label, job)
        message = f"{label} har startet" if started else f"Opptatt: {runner.current} pågår fortsatt"
        return RedirectResponse(f"/data?message={quote(message)}", 303)

    # The forms post to these addresses. Opened as a page (a bookmark, the browser history, or an old link back
    # after signing in) they lead to the page the form is on instead of a bare "Method Not Allowed".
    @app.get("/recommendations")
    def recommendations_page() -> RedirectResponse:
        return RedirectResponse("/", 303)

    @app.get("/data/{action}")
    def data_action_page(action: str) -> RedirectResponse:
        return RedirectResponse("/data", 303)

    @app.get("/logout")
    def logout_page() -> RedirectResponse:
        return RedirectResponse("/", 303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        fallback = ("Noe gikk galt", f"Serveren svarte med feilkode {exc.status_code}.")
        title, message = ERRORS.get(exc.status_code, fallback)
        return render_error(request, title, message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> Response:
        return render_error(request, "Ugyldig forespørsel", "Noe i adressen eller skjemaet var ikke gyldig.", 400)

    def render_error(request: Request, title: str, message: str, status: int) -> HTMLResponse:
        return templates.TemplateResponse(request, "error.html", {"title": title, "message": message},
                                          status_code=status)

    return app


ERRORS = {
    404: ("Fant ikke siden", "Adressen finnes ikke i appen."),
    405: ("Siden kan ikke åpnes slik", "Adressen tar bare imot skjemaer. Gå tilbake og prøv igjen."),
}


def _return_path(request: Request) -> str:
    """Where to go after signing in: the page itself, or for a form, the page the form was on.

    A form's own address only accepts the form, so sending the browser back to it would fail.
    """
    if request.method in ("GET", "HEAD"):
        query = request.url.query
        return request.url.path + (f"?{query}" if query else "")
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.netloc == request.url.netloc and referer.path.startswith("/") and referer.path != "/login":
        return referer.path + (f"?{referer.query}" if referer.query else "")
    return "/"


def _safe_next(next: str) -> str:
    """Only paths on this site, never another host ("//host" or "/\\host")."""
    return next if next.startswith("/") and not next.startswith(("//", "/\\")) else "/"


def serve(*, db: str | None, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(create_app(db), host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


# Formatting helpers used by the templates (Norwegian number and date formats).

def _missing(value: Any) -> bool:
    return value is None or isinstance(value, Undefined) or (isinstance(value, float) and not math.isfinite(value))


def fmt_nok(value: float | None, digits: int = 0) -> str:
    return "–" if _missing(value) else text.nok(value, digits)


def fmt_num(value: float | None, digits: int = 0, signed: bool = False) -> str:
    if _missing(value):
        return "–"
    return ("+" if signed and value > 0 else "") + text.number(value, digits)


def fmt_pct(value: float | None, digits: int = 1, signed: bool = False) -> str:
    return "–" if _missing(value) else text.percent(value, digits, signed)


def fmt_points(value: float | None, digits: int = 2) -> str:
    return "–" if _missing(value) else text.points(value, digits)


def fmt_when(value: datetime | str | None) -> str:
    if _missing(value):
        return "–"
    return text.date_time(datetime.fromisoformat(value) if isinstance(value, str) else value)


def fmt_day(value: date | str | None) -> str:
    if _missing(value) or value == "":
        return "–"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return text.day(value)


def fmt_ago(value: datetime | None) -> str:
    return "aldri" if _missing(value) else text.ago(value, queries.utcnow())


# Display names for the model's internal keys.
LABELS = {
    # Themes and overlays (stock page).
    "value": "Verdi", "quality": "Kvalitet", "momentum": "Momentum", "low_vol": "Lav volatilitet",
    "insider": "Innsidehandel", "buyback": "Tilbakekjøp", "short": "Shortandel",
    # Short-term signal types (track record page).
    "buyback_start": "Nytt tilbakekjøp", "insider_cluster": "Flere innsidekjøp", "short_increase": "Økt shortandel",
}


def fmt_label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _decimal(value: float | None, digits: int) -> str:
    return "" if _missing(value) else f"{value:.{digits}f}".replace(".", ",")
