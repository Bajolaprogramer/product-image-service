"""HTTP metrics middleware.

Wraps every request to record three things: a request count (by method,
endpoint, and status code), the response latency, and — implicitly — the status
code distribution. The ``/metrics`` scrape endpoint is excluded so Prometheus
polling does not inflate the application's own request metrics.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability import metrics


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Records request count, latency, and status code for each request."""

    def __init__(self, app: Callable, metrics_path: str = "/metrics") -> None:
        """Initialize the middleware.

        Args:
            app: The wrapped ASGI application.
            metrics_path: Path of the scrape endpoint to exclude from metrics.
        """

        super().__init__(app)
        self._metrics_path = metrics_path

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Time the request and record metrics for it.

        On an unhandled exception the request is still recorded (as HTTP 500)
        before the exception is re-raised, so error rates remain observable.
        """

        if request.url.path == self._metrics_path:
            return await call_next(request)

        method = request.method
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._record(request, method, "500", start)
            raise

        self._record(request, method, str(response.status_code), start)
        return response

    def _record(
        self, request: Request, method: str, status: str, start: float
    ) -> None:
        """Emit the count and latency samples for a finished request."""

        duration = time.perf_counter() - start
        endpoint = self._endpoint_label(request)
        metrics.HTTP_REQUESTS_TOTAL.labels(
            method=method, endpoint=endpoint, http_status=status
        ).inc()
        metrics.REQUEST_DURATION_SECONDS.labels(
            method=method, endpoint=endpoint
        ).observe(duration)

    @staticmethod
    def _endpoint_label(request: Request) -> str:
        """Return a low-cardinality endpoint label.

        Prefers the matched route's path template (e.g. ``/api/v1/images/search``)
        over the raw URL so path parameters never explode label cardinality.
        Unmatched requests (404s) are bucketed under ``"unmatched"``.
        """

        route = request.scope.get("route")
        path = getattr(route, "path", None)
        return path if path else "unmatched"
