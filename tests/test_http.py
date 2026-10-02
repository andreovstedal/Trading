import httpx
import pytest

from nordic_signals.http import FetchError, PoliteClient


def make_client(handler, *, sleeps, clock=None, **kwargs):
    return PoliteClient(
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        clock=clock or (lambda: 0.0),
        **kwargs,
    )


def test_retries_429_using_retry_after():
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")])
    sleeps: list[float] = []
    client = make_client(lambda _r: next(responses), sleeps=sleeps, min_interval=0)

    resp = client.get("https://example.no/x")

    assert resp.status == 200 and resp.body == b"ok"
    assert 7.0 in sleeps


def test_gives_up_after_max_retries():
    sleeps: list[float] = []
    client = make_client(lambda _r: httpx.Response(503), sleeps=sleeps, min_interval=0, max_retries=2)

    with pytest.raises(FetchError) as excinfo:
        client.get("https://example.no/x")

    assert excinfo.value.response.status == 503
    assert sleeps == [5.0, 10.0]  # exponential backoff from backoff_base=5


def test_http_errors_raise_unless_allowed():
    client = make_client(lambda _r: httpx.Response(404, text="nope"), sleeps=[], min_interval=0)

    with pytest.raises(FetchError):
        client.get("https://example.no/missing")
    assert client.get("https://example.no/missing", allow_status=(404,)).status == 404


def test_spaces_requests_to_the_same_host():
    now = [100.0]
    sleeps: list[float] = []
    client = make_client(lambda _r: httpx.Response(200), sleeps=sleeps, clock=lambda: now[0],
                         host_intervals={"slow.example": 4.0}, min_interval=1.0)

    client.get("https://slow.example/a")
    now[0] += 1.5
    client.get("https://slow.example/b")
    client.get("https://other.example/c")

    assert sleeps == [2.5]  # 4 s interval minus the 1.5 s already elapsed; other host not delayed


def test_sends_identifying_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200)

    make_client(handler, sleeps=[]).get("https://example.no/")
    assert "nordic-signals" in seen["ua"]
