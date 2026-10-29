from __future__ import annotations

import urllib.parse

import pytest

from roadsense import netcount


def test_tally_accumulates_and_resets():
    tally = netcount.Tally()
    tally.add(100)
    tally.add(50)
    assert tally.bytes_out == 150
    assert tally.requests == 2
    tally.reset()
    assert tally.bytes_out == 0
    assert tally.requests == 0


def test_rewire_wraps_the_url_for_the_proxy():
    proxy = netcount.CountingProxy().start()
    try:
        url = "https://deafrica-services.s3.af-south-1.amazonaws.com/a/B04.tif"
        rewired = proxy.rewire(url)
        assert rewired.startswith(f"http://127.0.0.1:{proxy.port}/r/")
        assert "%3A%2F%2F" in rewired  # the scheme is percent-encoded, not passed raw
        assert urllib.parse.unquote(rewired.split("/r/", 1)[1]) == url
    finally:
        proxy.stop()


def test_port_is_only_available_while_running():
    proxy = netcount.CountingProxy()
    with pytest.raises(RuntimeError, match="not running"):
        _ = proxy.port
