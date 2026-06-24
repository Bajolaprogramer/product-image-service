"""Tests for the Kafka layer: event serialization, producer, and processor.

No broker (or ``confluent_kafka``) is required: a fake producer is injected to
capture published messages, and the processor is driven directly with event
payloads. Business processing uses in-memory stub providers.
"""

from __future__ import annotations

import json

from app.kafka.events import (
    TOPIC_IMAGE_SEARCH_COMPLETED,
    TOPIC_IMAGE_SEARCH_FAILED,
    TOPIC_IMAGE_SEARCH_REQUESTED,
    TOPIC_PROVIDER_FAILURE,
    ImageSearchCompletedEvent,
    ImageSearchFailedEvent,
    ImageSearchRequestedEvent,
    ProviderFailureEvent,
)
from app.kafka.processor import SearchEventProcessor
from app.kafka.producer import EventProducer
from app.models.product_image import ImageSource, ProductImage, SearchStatus
from app.providers.base_provider import ImageProvider
from app.providers.registry import ProviderRegistry
from app.services.product_image_service import ProductImageService

BARCODE = "3017620422003"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeKafkaProducer:
    """Captures produce() calls instead of talking to a broker."""

    def __init__(self) -> None:
        self.produced: list[dict] = []
        self.flushed = 0

    def produce(self, topic, value, key=None, on_delivery=None) -> None:
        self.produced.append({"topic": topic, "value": value, "key": key})

    def poll(self, timeout=0) -> int:
        return 0

    def flush(self, timeout=None) -> int:
        self.flushed += 1
        return 0


class StubProvider(ImageProvider):
    """Returns canned images or raises a canned error."""

    def __init__(self, *, name, images=None, error=None) -> None:
        self.name = name
        self._images = images or []
        self._error = error

    async def search_images(self, barcode: str):
        if self._error is not None:
            raise self._error
        return list(self._images)


def _img(url: str) -> ProductImage:
    return ProductImage(image_url=url, source=ImageSource.OPEN_FOOD_FACTS, relevance_score=0.9)


def _processor(*providers: ImageProvider) -> tuple[SearchEventProcessor, FakeKafkaProducer]:
    """Build a processor whose service uses the given providers, plus its fake producer."""

    fake = FakeKafkaProducer()
    producer = EventProducer(producer=fake)
    processor = SearchEventProcessor(service=None, producer=producer)  # type: ignore[arg-type]
    processor._service = ProductImageService(
        registry=ProviderRegistry(list(providers)), event_sink=processor
    )
    return processor, fake


def _topics(fake: FakeKafkaProducer) -> list[str]:
    return [p["topic"] for p in fake.produced]


# --------------------------------------------------------------------------- #
# Event serialization
# --------------------------------------------------------------------------- #
def test_requested_event_roundtrip() -> None:
    event = ImageSearchRequestedEvent(search_id="s1", barcode=BARCODE)

    raw = event.serialize()
    restored = ImageSearchRequestedEvent.from_bytes(raw)

    assert isinstance(raw, bytes)
    assert restored.search_id == "s1"
    assert restored.barcode == BARCODE
    assert restored.event_type == "image_search_requested"
    assert restored.key() == "s1"
    assert ImageSearchRequestedEvent.topic == TOPIC_IMAGE_SEARCH_REQUESTED

    # The wire payload carries identifying/audit fields.
    payload = json.loads(raw)
    assert payload["event_type"] == "image_search_requested"
    assert "event_id" in payload and "occurred_at" in payload


def test_completed_event_roundtrip_preserves_images() -> None:
    event = ImageSearchCompletedEvent(
        search_id="s2",
        query=BARCODE,
        status="SUCCESS",
        total_images=2,
        image_urls=["https://a/1.jpg", "https://b/2.jpg"],
    )

    restored = ImageSearchCompletedEvent.from_bytes(event.serialize())

    assert restored.total_images == 2
    assert restored.image_urls == ["https://a/1.jpg", "https://b/2.jpg"]
    assert ImageSearchCompletedEvent.topic == TOPIC_IMAGE_SEARCH_COMPLETED


# --------------------------------------------------------------------------- #
# Producer invocation
# --------------------------------------------------------------------------- #
def test_producer_publishes_to_event_topic() -> None:
    fake = FakeKafkaProducer()
    producer = EventProducer(producer=fake)

    producer.publish(ProviderFailureEvent(provider="open_food_facts", query=BARCODE, error="boom"))

    assert len(fake.produced) == 1
    entry = fake.produced[0]
    assert entry["topic"] == TOPIC_PROVIDER_FAILURE
    assert entry["key"] == "open_food_facts"
    body = json.loads(entry["value"])
    assert body["provider"] == "open_food_facts"
    assert body["error"] == "boom"


def test_producer_flush_delegates() -> None:
    fake = FakeKafkaProducer()
    EventProducer(producer=fake).flush()
    assert fake.flushed == 1


# --------------------------------------------------------------------------- #
# Processor flow (consume -> process -> produce)
# --------------------------------------------------------------------------- #
async def test_processor_success_flow_publishes_completed() -> None:
    processor, fake = _processor(StubProvider(name="stub", images=[_img("https://a/1.jpg")]))

    requested = ImageSearchRequestedEvent(search_id="s1", barcode=BARCODE).serialize()
    result = await processor.process(requested)

    assert isinstance(result, ImageSearchCompletedEvent)
    assert result.search_id == "s1"
    assert result.status == SearchStatus.SUCCESS.value
    assert result.total_images == 1
    assert _topics(fake) == [TOPIC_IMAGE_SEARCH_COMPLETED]


async def test_processor_failure_flow_publishes_failed() -> None:
    # Provider returns no images -> FAILED.
    processor, fake = _processor(StubProvider(name="stub", images=[]))

    requested = ImageSearchRequestedEvent(search_id="s2", barcode=BARCODE).serialize()
    result = await processor.process(requested)

    assert isinstance(result, ImageSearchFailedEvent)
    assert result.search_id == "s2"
    assert result.reason == "no images found"
    assert _topics(fake) == [TOPIC_IMAGE_SEARCH_FAILED]


async def test_processor_publishes_provider_failure_event() -> None:
    # One provider fails, one succeeds -> PARTIAL_SUCCESS (completed) AND a
    # provider-failure event emitted via the sink during processing.
    processor, fake = _processor(
        StubProvider(name="flaky", error=RuntimeError("down")),
        StubProvider(name="good", images=[_img("https://good/1.jpg")]),
    )

    requested = ImageSearchRequestedEvent(search_id="s3", barcode=BARCODE).serialize()
    result = await processor.process(requested)

    topics = _topics(fake)
    assert TOPIC_PROVIDER_FAILURE in topics
    assert TOPIC_IMAGE_SEARCH_COMPLETED in topics
    assert isinstance(result, ImageSearchCompletedEvent)
    assert result.status == SearchStatus.PARTIAL_SUCCESS.value


async def test_processor_invalid_request_publishes_failed() -> None:
    # Neither barcode nor sku -> request validation fails -> failed event.
    processor, fake = _processor(StubProvider(name="stub", images=[_img("https://a/1.jpg")]))

    requested = ImageSearchRequestedEvent(search_id="s4").serialize()
    result = await processor.process(requested)

    assert isinstance(result, ImageSearchFailedEvent)
    assert _topics(fake) == [TOPIC_IMAGE_SEARCH_FAILED]
