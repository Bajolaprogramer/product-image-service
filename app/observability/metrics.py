"""Prometheus metric definitions and recording helpers.

All metrics register against the ``prometheus_client`` default registry, which
the ``/metrics`` endpoint serializes. Counter objects are created without the
``_total`` suffix because ``prometheus_client`` appends it automatically — e.g.
``Counter("image_search_requests", ...)`` is exposed as
``image_search_requests_total``.

Exposed series:
    * ``http_requests_total`` — total HTTP requests (labels: method, endpoint,
      http_status). [the "total_http_requests" counter]
    * ``request_duration_seconds`` — request latency histogram (labels: method,
      endpoint).
    * ``image_search_requests_total`` — image searches received.
    * ``image_search_success_total`` / ``image_search_partial_success_total`` /
      ``image_search_failed_total`` — searches by outcome.
    * ``provider_failures_total`` — provider failures during aggregation
      (label: provider).
    * ``circuit_breaker_open_total`` — calls rejected by an open circuit
      (label: provider).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from app.models.product_image import SearchStatus

# --- HTTP-level metrics (populated by the middleware) -----------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests",
    "Total number of HTTP requests processed.",
    labelnames=("method", "endpoint", "http_status"),
)

REQUEST_DURATION_SECONDS = Histogram(
    "request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "endpoint"),
)

# --- Domain metrics (populated by the service) ------------------------------
IMAGE_SEARCH_REQUESTS_TOTAL = Counter(
    "image_search_requests",
    "Total number of product image search requests.",
)

IMAGE_SEARCH_SUCCESS_TOTAL = Counter(
    "image_search_success",
    "Product image searches that completed with status SUCCESS.",
)

IMAGE_SEARCH_PARTIAL_SUCCESS_TOTAL = Counter(
    "image_search_partial_success",
    "Product image searches that completed with status PARTIAL_SUCCESS.",
)

IMAGE_SEARCH_FAILED_TOTAL = Counter(
    "image_search_failed",
    "Product image searches that completed with status FAILED.",
)

PROVIDER_FAILURES_TOTAL = Counter(
    "provider_failures",
    "Total provider failures encountered during aggregation.",
    labelnames=("provider",),
)

CIRCUIT_BREAKER_OPEN_TOTAL = Counter(
    "circuit_breaker_open",
    "Total calls rejected because a provider's circuit breaker was open.",
    labelnames=("provider",),
)

# Maps a search outcome to the counter that tracks it.
_STATUS_COUNTERS: dict[SearchStatus, Counter] = {
    SearchStatus.SUCCESS: IMAGE_SEARCH_SUCCESS_TOTAL,
    SearchStatus.PARTIAL_SUCCESS: IMAGE_SEARCH_PARTIAL_SUCCESS_TOTAL,
    SearchStatus.FAILED: IMAGE_SEARCH_FAILED_TOTAL,
}


def record_search_request() -> None:
    """Increment the image-search request counter."""

    IMAGE_SEARCH_REQUESTS_TOTAL.inc()


def record_search_status(status: SearchStatus) -> None:
    """Increment the per-outcome counter for a completed search."""

    counter = _STATUS_COUNTERS.get(status)
    if counter is not None:
        counter.inc()


def record_provider_failure(provider: str) -> None:
    """Increment the failure counter for a named provider."""

    PROVIDER_FAILURES_TOTAL.labels(provider=provider).inc()


def record_circuit_open(provider: str) -> None:
    """Increment the open-circuit rejection counter for a named provider."""

    CIRCUIT_BREAKER_OPEN_TOTAL.labels(provider=provider).inc()
