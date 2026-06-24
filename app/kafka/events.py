"""Kafka event models and topic names.

Clean, self-describing Pydantic v2 events. Each event knows the topic it belongs
to (``topic`` class var) and serializes to/from JSON bytes for the wire. Events
are pure data — they hold no behavior beyond (de)serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar

from pydantic import BaseModel, Field

# --- Topic names ------------------------------------------------------------
TOPIC_IMAGE_SEARCH_REQUESTED = "image-search-requested"
TOPIC_IMAGE_SEARCH_COMPLETED = "image-search-completed"
TOPIC_IMAGE_SEARCH_FAILED = "image-search-failed"
TOPIC_PROVIDER_FAILURE = "provider-failure"
TOPIC_CIRCUIT_BREAKER_OPENED = "circuit-breaker-opened"


def _new_id() -> str:
    """Generate a unique event identifier."""

    return str(uuid.uuid4())


def _now() -> datetime:
    """Current UTC timestamp."""

    return datetime.now(timezone.utc)


class KafkaEvent(BaseModel):
    """Base class for all events carried over Kafka.

    Subclasses set ``topic`` and a default ``event_type``. ``serialize`` /
    ``from_bytes`` move between the model and the JSON-bytes wire format.
    """

    #: Topic this event is published to. Overridden by each subclass.
    topic: ClassVar[str] = ""

    event_id: str = Field(default_factory=_new_id)
    event_type: str = "kafka_event"
    occurred_at: datetime = Field(default_factory=_now)

    def serialize(self) -> bytes:
        """Encode the event as UTF-8 JSON bytes for the Kafka value."""

        return self.model_dump_json().encode("utf-8")

    def key(self) -> str | None:
        """Partition key for ordering. ``None`` by default (round-robin)."""

        return None

    @classmethod
    def from_bytes(cls, data: bytes | str) -> "KafkaEvent":
        """Decode JSON bytes/str into an instance of this event class."""

        return cls.model_validate_json(data)


class ImageSearchRequestedEvent(KafkaEvent):
    """A request to search for product images (search starts)."""

    topic: ClassVar[str] = TOPIC_IMAGE_SEARCH_REQUESTED

    event_type: str = "image_search_requested"
    search_id: str
    barcode: str | None = None
    sku: str | None = None

    def key(self) -> str | None:
        return self.search_id


class ImageSearchCompletedEvent(KafkaEvent):
    """A search that completed with images (success / partial success)."""

    topic: ClassVar[str] = TOPIC_IMAGE_SEARCH_COMPLETED

    event_type: str = "image_search_completed"
    search_id: str
    query: str
    status: str
    total_images: int
    image_urls: list[str] = Field(default_factory=list)

    def key(self) -> str | None:
        return self.search_id


class ImageSearchFailedEvent(KafkaEvent):
    """A search that produced no images or failed to process."""

    topic: ClassVar[str] = TOPIC_IMAGE_SEARCH_FAILED

    event_type: str = "image_search_failed"
    search_id: str
    query: str | None = None
    reason: str

    def key(self) -> str | None:
        return self.search_id


class ProviderFailureEvent(KafkaEvent):
    """A single provider failed during aggregation."""

    topic: ClassVar[str] = TOPIC_PROVIDER_FAILURE

    event_type: str = "provider_failure"
    provider: str
    query: str
    error: str

    def key(self) -> str | None:
        return self.provider


class CircuitBreakerOpenedEvent(KafkaEvent):
    """A provider call was rejected because its circuit breaker is open."""

    topic: ClassVar[str] = TOPIC_CIRCUIT_BREAKER_OPENED

    event_type: str = "circuit_breaker_opened"
    provider: str
    query: str

    def key(self) -> str | None:
        return self.provider
