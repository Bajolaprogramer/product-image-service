"""Kafka event producer.

A thin wrapper over ``confluent_kafka.Producer`` that publishes
:class:`~app.kafka.events.KafkaEvent` instances. The underlying client is created
lazily so importing this module never requires the library or a broker; a client
may also be injected (used by tests to capture calls without a broker).

``Producer.produce`` is non-blocking (it buffers and sends in the background),
which keeps :meth:`publish` cheap to call from both sync and async code.
"""

from __future__ import annotations

import logging
from typing import Any

from app.kafka.events import KafkaEvent

logger = logging.getLogger(__name__)


class EventProducer:
    """Publishes domain events to Kafka."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        *,
        producer: Any | None = None,
        flush_timeout_seconds: float = 5.0,
    ) -> None:
        """Configure the producer.

        Args:
            bootstrap_servers: Kafka bootstrap servers (``host:port``).
            producer: Pre-built client with ``produce``/``poll``/``flush``.
                When omitted, a real ``confluent_kafka.Producer`` is created on
                first use. Inject a fake in tests.
            flush_timeout_seconds: Default timeout for :meth:`flush`.
        """

        self._bootstrap_servers = bootstrap_servers
        self._producer = producer
        self._flush_timeout = flush_timeout_seconds

    def _client(self) -> Any:
        """Return the underlying client, creating a real one on first use."""

        if self._producer is None:
            from confluent_kafka import Producer  # lazy import

            self._producer = Producer({"bootstrap.servers": self._bootstrap_servers})
        return self._producer

    def publish(self, event: KafkaEvent) -> None:
        """Publish an event to its topic.

        Serialization and topic selection come from the event itself, so callers
        never deal with Kafka specifics.
        """

        client = self._client()
        client.produce(
            topic=event.topic,
            value=event.serialize(),
            key=event.key(),
            on_delivery=self._on_delivery,
        )
        # Serve delivery callbacks without blocking.
        client.poll(0)

    def flush(self, timeout: float | None = None) -> None:
        """Block until buffered messages are delivered (or the timeout lapses)."""

        self._client().flush(timeout if timeout is not None else self._flush_timeout)

    @staticmethod
    def _on_delivery(error: Any, message: Any) -> None:
        """Delivery-report callback for logging failures."""

        if error is not None:
            logger.warning("Kafka delivery failed: %s", error)
