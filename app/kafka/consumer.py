"""Kafka event consumer.

A thin wrapper over ``confluent_kafka.Consumer``. It is intentionally
event-agnostic: it yields raw broker messages and lets the caller (the
processor) decide how to deserialize them, keeping this module free of domain
knowledge. The client is created lazily and may be injected for tests.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


class EventConsumer:
    """Consumes raw messages from one or more Kafka topics."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: Sequence[str],
        *,
        consumer: Any | None = None,
        auto_offset_reset: str = "earliest",
    ) -> None:
        """Configure the consumer.

        Args:
            bootstrap_servers: Kafka bootstrap servers (``host:port``).
            group_id: Consumer group id for offset tracking.
            topics: Topics to subscribe to.
            consumer: Pre-built client with ``poll``/``subscribe``/``close``.
                When omitted, a real ``confluent_kafka.Consumer`` is created on
                first use. Inject a fake in tests.
            auto_offset_reset: Where to start when no offset is committed.
        """

        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = list(topics)
        self._consumer = consumer
        self._auto_offset_reset = auto_offset_reset

    def _client(self) -> Any:
        """Return the underlying client, creating and subscribing on first use."""

        if self._consumer is None:
            from confluent_kafka import Consumer  # lazy import

            self._consumer = Consumer(
                {
                    "bootstrap.servers": self._bootstrap_servers,
                    "group.id": self._group_id,
                    "auto.offset.reset": self._auto_offset_reset,
                    "enable.auto.commit": True,
                }
            )
            self._consumer.subscribe(self._topics)
        return self._consumer

    def poll(self, timeout: float = 1.0) -> Any | None:
        """Poll for a single message.

        Returns:
            The broker message, or ``None`` if nothing arrived within ``timeout``
            or the message carried a (logged) error.
        """

        message = self._client().poll(timeout)
        if message is None:
            return None
        if message.error():
            logger.warning("Kafka consume error: %s", message.error())
            return None
        return message

    def close(self) -> None:
        """Close the consumer, committing final offsets."""

        if self._consumer is not None:
            self._consumer.close()
