"""A local HTTP proxy that counts the bytes GDAL actually downloads.

Why this exists: the plan's "measure the pilot, don't estimate it" instruction is not satisfiable
by asking rasterio how much it fetched — GDAL's range requests happen in C and expose no byte
counter. Estimating from request counts would repeat the guessing that produced the original
30–40 GB figure, so the pilot measures instead.

How it works: the proxy sits on ``127.0.0.1``, forwards to the real HTTPS URL, and tallies every
response body it relays. GDAL is given a ``http://127.0.0.1:PORT/r/<urlencoded-url>`` href, so the
range headers it sends pass through untouched and the response is a genuine 206 with the real
``Content-Range``.

This is a measurement instrument, not a production component. Nothing but the pilot uses it.
"""

from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER_AGENT = "roadsense-ng/0.1 (+research project)"


@dataclass
class Tally:
    """Bytes and requests relayed, reset per measurement."""

    bytes_out: int = 0
    requests: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, n: int) -> None:
        with self._lock:
            self.bytes_out += n
            self.requests += 1

    def reset(self) -> None:
        with self._lock:
            self.bytes_out = 0
            self.requests = 0


class CountingProxy:
    """A threaded proxy in front of an HTTPS host, with byte accounting."""

    def __init__(self) -> None:
        self.tally = Tally()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("proxy is not running")
        return int(self._server.server_address[1])

    def start(self) -> CountingProxy:
        tally = self.tally

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _target(self) -> str | None:
                if not self.path.startswith("/r/"):
                    self.send_error(404)
                    return None
                return urllib.parse.unquote(self.path[3:])

            def do_HEAD(self) -> None:  # noqa: N802 - required name
                """GDAL probes with HEAD before it ranges; answering 501 breaks the open."""
                target = self._target()
                if target is None:
                    return
                req = urllib.request.Request(
                    target, headers={"User-Agent": USER_AGENT}, method="HEAD"
                )
                try:
                    upstream = urllib.request.urlopen(req, timeout=120)
                except Exception:  # noqa: BLE001 - surface as a 502 to GDAL
                    self.send_error(502)
                    return
                with upstream:
                    self.send_response(upstream.status)
                    # Content-Length must be the entity length, not 0: GDAL uses the HEAD to
                    # decide whether range requests are viable. Reporting 0 makes it abandon
                    # ranges and stream the entire 172 MB file, which silently destroys the
                    # measurement (and cost 172 MB to discover).
                    for header in ("Content-Type", "Accept-Ranges", "Content-Length", "ETag"):
                        if upstream.headers.get(header):
                            self.send_header(header, upstream.headers[header])
                    self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 - required name
                target = self._target()
                if target is None:
                    return
                headers = {"User-Agent": USER_AGENT}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]

                req = urllib.request.Request(target, headers=headers)
                try:
                    upstream = urllib.request.urlopen(req, timeout=120)
                except Exception:  # noqa: BLE001 - surface as a 502 to GDAL
                    self.send_error(502)
                    return

                with upstream:
                    body = upstream.read()
                    status = upstream.status
                    self.send_response(status)
                    for header in ("Content-Type", "Content-Range", "Accept-Ranges", "ETag"):
                        if upstream.headers.get(header):
                            self.send_header(header, upstream.headers[header])
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    tally.add(len(body))

            def log_message(self, *args) -> None:  # silence per-request logging
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def rewire(self, url: str) -> str:
        """Rewrite an HTTPS URL to go through this proxy."""
        return f"http://127.0.0.1:{self.port}/r/{urllib.parse.quote(url, safe='')}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
