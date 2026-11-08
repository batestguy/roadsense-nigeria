from __future__ import annotations

import email.message
import json
import urllib.error
import urllib.request

import pytest

# Import guard first: roadsense.sampler imports rasterio at module level, and rasterio is an
# optional extra. Without this, a bare `.[dev]` install fails at collection instead of skipping.
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

import numpy as np  # noqa: E402

from roadsense import sampler  # noqa: E402


def test_s3_href_becomes_anonymous_https():
    href = "s3://deafrica-services/gm_s2_rolling/0-0-1/x188/y089/2024-01--P3M/a_B04.tif"
    assert sampler.s3_to_https(href) == (
        "https://deafrica-services.s3.af-south-1.amazonaws.com/"
        "gm_s2_rolling/0-0-1/x188/y089/2024-01--P3M/a_B04.tif"
    )


def test_https_href_is_left_alone():
    url = "https://example.com/a.tif"
    assert sampler.s3_to_https(url) == url


def test_item_xy_derives_from_the_transform_origin():
    item = sampler.Item(
        item_id="x",
        month="2024-01",
        assets={},
        transform=(10.0, 0.0, 672_000.0, 0.0, -10.0, 1_152_000.0, 0.0, 0.0, 1.0),
        shape=(9600, 9600),
    )
    assert item.item_xy == (7, 11)


def test_ndvi_and_ndbi_are_computed_from_the_bands():
    red = np.array([[1000.0, 2000.0]], dtype="float32")
    nir = np.array([[3000.0, 2000.0]], dtype="float32")
    swir = np.array([[4000.0, 2000.0]], dtype="float32")
    mask = np.array([[True, True]])
    out = sampler.indices(red, nir, swir, mask)

    assert out["ndvi_mean"] == pytest.approx((0.5 + 0.0) / 2)
    assert out["ndbi_mean"] == pytest.approx((0.14285714 + 0.0) / 2, abs=1e-6)
    assert out["pixels"] == 2
    assert out["pixels_valid"] == 2


def test_zero_nodata_pixels_are_excluded_not_averaged_in():
    # A (0, 0) pixel is "no observation" in GeoMAD, not a black road.
    red = np.array([[1000.0, 0.0]], dtype="float32")
    nir = np.array([[3000.0, 0.0]], dtype="float32")
    swir = np.array([[4000.0, 0.0]], dtype="float32")
    mask = np.array([[True, True]])
    out = sampler.indices(red, nir, swir, mask)

    assert out["pixels"] == 2
    assert out["pixels_valid"] == 1
    assert out["ndvi_mean"] == pytest.approx(0.5)


def test_all_invalid_returns_nan_rather_than_raising():
    zeros = np.zeros((2, 2), dtype="float32")
    out = sampler.indices(zeros, zeros, zeros, np.ones((2, 2), dtype=bool))
    assert out["pixels_valid"] == 0
    assert np.isnan(out["ndvi_mean"])


def test_road_mask_is_empty_for_no_paths():
    mask = sampler.road_mask([], 85, 150, resolution=40)
    assert mask.shape == (200, 200)
    assert not mask.any()


def test_rings_returns_a_core_and_a_disjoint_ring():
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(681_000, 1_201_000)
    lon1, lat1 = tiles.to_wgs(687_000, 1_207_000)
    core, ring = sampler.rings([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=10)

    assert core.shape == ring.shape == (800, 800)
    assert core.any() and ring.any()
    # The ring must exclude the carriageway, or the contrast is contaminated by tarmac.
    assert not (core & ring).any()


def test_ring_sits_further_out_than_the_core():
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(684_000, 1_204_000)
    lon1, lat1 = tiles.to_wgs(684_000, 1_204_800)
    core, ring = sampler.rings([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=10)

    # A vertical line through the tile centre: the ring must have pixels both left and right of
    # the core, while the core itself stays narrow.
    core_cols = np.where(core.any(axis=0))[0]
    ring_cols = np.where(ring.any(axis=0))[0]
    assert core_cols.max() - core_cols.min() <= 3
    assert ring_cols.min() < core_cols.min()
    assert ring_cols.max() > core_cols.max()


def test_rings_are_empty_without_paths():
    core, ring = sampler.rings([], 85, 150, resolution=40)
    assert not core.any() and not ring.any()


def test_contrast_is_ring_minus_core():
    assert sampler.contrast({"ndvi_mean": 0.10}, {"ndvi_mean": 0.35}) == pytest.approx(0.25)


def test_contrast_is_nan_when_either_side_is_missing():
    nan = float("nan")
    assert np.isnan(sampler.contrast({"ndvi_mean": 0.1}, {"ndvi_mean": nan}))
    assert np.isnan(sampler.contrast({"ndvi_mean": nan}, {"ndvi_mean": 0.3}))


def test_road_mask_marks_pixels_along_a_projected_line():
    # A short segment inside tile (85, 150); coordinates are lon/lat and must be projected.
    left, bottom = 680_000.0, 1_200_000.0
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(left + 1000, bottom + 1000)
    lon1, lat1 = tiles.to_wgs(left + 7000, bottom + 7000)
    mask = sampler.road_mask([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=40)

    assert mask.shape == (200, 200)
    assert mask.any()
    # The line runs corner to corner, so it must not flag the whole tile.
    assert mask.mean() < 0.3


# --- STAC search retry ---------------------------------------------------------------------------
#
# Run 41149975095 lost 12 of 96 shards to a 503 storm on `stac/search`. These tests script
# urllib.request.urlopen and record the sleeps, so the schedule is proved without waiting for it.

SEARCH_URL = "https://explorer.digitalearth.africa/stac/search"


class _JsonResponse:
    """The subset of an ``http.client.HTTPResponse`` that ``_post_json`` touches."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _HtmlResponse(_JsonResponse):
    """A 200 carrying an error page — what an overloaded proxy actually returns."""

    def __init__(self):
        self._body = b"<html><body>503 Service Temporarily Unavailable</body></html>"


def _http_error(code: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(SEARCH_URL, code, "Service Temporarily Unavailable", headers, None)


def _script_urlopen(monkeypatch, script: list) -> list:
    """Replace ``urlopen``; each entry is a response or an exception. Returns the requests made."""
    calls: list = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        outcome = script[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_search_post_retries_six_503s_and_then_succeeds(monkeypatch):
    calls = _script_urlopen(monkeypatch, [_http_error(503)] * 6 + [_JsonResponse({"features": []})])
    sleeps: list[float] = []

    payload = sampler._post_json(SEARCH_URL, {"collections": ["x"]}, sleep=sleeps.append)

    assert payload == {"features": []}
    # Six failures then the answer: seven attempts, six waits between them.
    assert len(calls) == 7
    assert len(sleeps) == 6
    assert all(delay >= 1.0 for delay in sleeps)


def test_search_post_gives_up_loudly_after_a_bounded_number_of_attempts(monkeypatch):
    calls = _script_urlopen(monkeypatch, [_http_error(503)] * 12)
    sleeps: list[float] = []

    with pytest.raises(RuntimeError) as excinfo:
        sampler._post_json(SEARCH_URL, {}, sleep=sleeps.append)

    message = str(excinfo.value)
    assert "STAC search failed at" in message and SEARCH_URL in message
    assert "503" in message
    # Bounded, and bounded generously enough to ride out the storm that killed the run.
    assert sampler.SEARCH_ATTEMPTS == 10
    assert len(calls) == sampler.SEARCH_ATTEMPTS
    assert len(sleeps) == sampler.SEARCH_ATTEMPTS - 1
    assert sum(sleeps) >= 180.0, "must tolerate at least ~3 minutes of continuous 503"
    for attempt, delay in enumerate(sleeps):
        base = min(2.0**attempt, sampler.SEARCH_BACKOFF_CAP_S)
        assert base <= delay <= base * (1.0 + sampler.SEARCH_JITTER)


def test_search_post_makes_one_attempt_when_the_first_call_succeeds(monkeypatch):
    calls = _script_urlopen(monkeypatch, [_JsonResponse({"features": [{"id": "a"}]})])
    sleeps: list[float] = []

    payload = sampler._post_json(SEARCH_URL, {}, sleep=sleeps.append)

    assert payload == {"features": [{"id": "a"}]}
    assert len(calls) == 1
    assert sleeps == []


def test_search_post_does_not_retry_a_bad_request(monkeypatch):
    # A 400 is a broken request body; the tenth attempt sends the same body. Fail at once.
    calls = _script_urlopen(monkeypatch, [_http_error(400), _JsonResponse({})])
    sleeps: list[float] = []

    with pytest.raises(RuntimeError, match="STAC search failed at"):
        sampler._post_json(SEARCH_URL, {}, sleep=sleeps.append)

    assert len(calls) == 1
    assert sleeps == []


def test_search_post_honours_retry_after_and_caps_it(monkeypatch):
    calls = _script_urlopen(
        monkeypatch,
        [_http_error(503, retry_after="7"), _http_error(503, retry_after="99999"), _JsonResponse({})],
    )
    sleeps: list[float] = []

    sampler._post_json(SEARCH_URL, {}, sleep=sleeps.append)

    assert len(calls) == 3
    assert sleeps[0] == 7.0
    # A misconfigured header must not hold a shard open for hours.
    assert sleeps[1] == sampler.RETRY_AFTER_CAP_S


def test_search_post_retries_a_dropped_connection(monkeypatch):
    calls = _script_urlopen(
        monkeypatch, [urllib.error.URLError("connection reset"), _JsonResponse({"features": []})]
    )

    payload = sampler._post_json(SEARCH_URL, {}, sleep=lambda _delay: None)

    assert payload == {"features": []}
    assert len(calls) == 2


def test_search_post_retries_a_non_json_body(monkeypatch):
    # An overloaded proxy answers 200 with an HTML error page; that is a transport failure.
    calls = _script_urlopen(monkeypatch, [_HtmlResponse(), _JsonResponse({"features": []})])

    payload = sampler._post_json(SEARCH_URL, {}, sleep=lambda _delay: None)

    assert payload == {"features": []}
    assert len(calls) == 2

