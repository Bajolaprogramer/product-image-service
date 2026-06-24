"""Search event processor — a hybrid Kafka consumer **and** producer.

Flow:
    1. Consume ``image-search-requested`` events.
    2. Execute business processing by delegating to ``ProductImageService``
       (this module holds no business logic of its own).
    3. Publish ``image-search-completed`` on success/partial success, or
       ``image-search-failed`` when no images are found / processing errors.

It also implements :class:`~app.services.event_sink.SearchEventSink`, so while a
search runs the service notifies it of provider failures and circuit-open
rejections, which it republishes as ``provider-failure`` and
``circuit-breaker-opened`` events. That dual role (consumer + producer) is the
required hybrid module.
"""

from __future__ import annotations

import asyncio
import logging

from app.kafka.consumer import EventConsumer
from app.kafka.events import (
    TOPIC_IMAGE_SEARCH_REQUESTED,
    CircuitBreakerOpenedEvent,
    ImageSearchCompletedEvent,
    ImageSearchFailedEvent,
    ImageSearchRequestedEvent,
    KafkaEvent,
    ProviderFailureEvent,
)
from app.kafka.producer import EventProducer
from app.models.product_image import ProductImageSearchRequest, SearchStatus
from app.services.product_image_service import (
    ProductImageService,
    build_product_image_service,
)

logger = logging.getLogger(__name__)


class SearchEventProcessor:
    """Consumes search requests, runs them, and publishes the outcome."""

    def __init__(
        self,
        service: ProductImageService,
        producer: EventProducer,
        consumer: EventConsumer | None = None,
    ) -> None:
        """Wire the processor.

        Args:
            service: Business logic. The processor delegates all search work here.
            producer: Used to publish outcome and provider/circuit events.
            consumer: Source of request events. Optional so the processor can be
                driven directly (e.g. in tests) without a broker.
        """

        self._service = service
        self._producer = producer
        self._consumer = consumer

    # --- SearchEventSink implementation (producer role during a search) -----
    def on_provider_failure(self, *, provider: str, query: str, error: str) -> None:
        """Publish a ``provider-failure`` event."""

        self._producer.publish(
            ProviderFailureEvent(provider=provider, query=query, error=error)
        )

    def on_circuit_open(self, *, provider: str, query: str) -> None:
        """Publish a ``circuit-breaker-opened`` event."""

        self._producer.publish(
            CircuitBreakerOpenedEvent(provider=provider, query=query)
        )

    # --- Core processing (consumer role) ------------------------------------
    async def process(self, payload: bytes | str) -> KafkaEvent:
        """Process one ``image-search-requested`` payload.

        Args:
            payload: Raw JSON bytes/str of an
                :class:`ImageSearchRequestedEvent`.

        Returns:
            The outcome event that was published (completed or failed) — useful
            for testing and logging.
        """

        requested = ImageSearchRequestedEvent.from_bytes(payload)

        try:
            request = ProductImageSearchRequest(
                barcode=requested.barcode, sku=requested.sku
            )
            response = await self._service.search(request)
        except Exception as exc:  # validation or unexpected processing error
            logger.exception("Search processing failed for %s", requested.search_id)
            return self._publish(
                ImageSearchFailedEvent(
                    search_id=requested.search_id,
                    query=requested.barcode or requested.sku,
                    reason=repr(exc),
                )
            )

        if response.status is SearchStatus.FAILED:
            return self._publish(
                ImageSearchFailedEvent(
                    search_id=requested.search_id,
                    query=response.query,
                    reason="no images found",
                )
            )

        return self._publish(
            ImageSearchCompletedEvent(
                search_id=requested.search_id,
                query=response.query,
                status=response.status.value,
                total_images=response.total_images,
                image_urls=[image.image_url for image in response.images],
            )
        )

    def _publish(self, event: KafkaEvent) -> KafkaEvent:
        """Publish and return an event."""

        self._producer.publish(event)
        return event

    # --- Long-running consume loop ------------------------------------------
    def run(self, poll_timeout: float = 1.0) -> None:
        """Block, consuming request events until interrupted.

        Each message is processed on a private event loop (the underlying Kafka
        client is synchronous); buffered outcome events are flushed afterwards.
        """

        if self._consumer is None:
            raise RuntimeError("A consumer is required to run the processing loop.")

        loop = asyncio.new_event_loop()
        try:
            logger.info("Search event processor started.")
            while True:
                message = self._consumer.poll(poll_timeout)
                if message is None:
                    continue
                loop.run_until_complete(self.process(message.value()))
                self._producer.flush()
        except KeyboardInterrupt:  # pragma: no cover - operational shutdown
            logger.info("Search event processor stopping.")
        finally:
            loop.close()
            self._consumer.close()

    @classmethod
    def from_settings(cls, settings: object) -> "SearchEventProcessor":
        """Build a processor (producer + consumer + service) from settings.

        The service is wired with this processor as its event sink so provider /
        circuit-breaker events are published during processing.
        """

        bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:9092")
        group_id = getattr(
            settings, "kafka_consumer_group_id", "product-image-service"
        )

        producer = EventProducer(bootstrap)
        consumer = EventConsumer(
            bootstrap_servers=bootstrap,
            group_id=group_id,
            topics=[TOPIC_IMAGE_SEARCH_REQUESTED],
        )
        processor = cls(service=None, producer=producer, consumer=consumer)  # type: ignore[arg-type]
        processor._service = build_product_image_service(event_sink=processor)
        return processor


def main() -> None:  # pragma: no cover - operational entrypoint
    """Run the processor as a standalone worker (``python -m app.kafka.processor``)."""

    logging.basicConfig(level=logging.INFO)
    from app.core.config import get_settings

    SearchEventProcessor.from_settings(get_settings()).run()


if __name__ == "__main__":  # pragma: no cover
    main()
