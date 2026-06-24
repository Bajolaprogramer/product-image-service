"""Kafka integration: event models, producer, consumer, and processor.

This package is a thin transport/adapter layer. It carries domain events to and
from Kafka but contains **no business logic** — the processor delegates all
search work to :class:`~app.services.product_image_service.ProductImageService`.

``confluent_kafka`` is imported lazily (only when a real broker client is
created), so these modules import cleanly in environments without the library or
a running broker, which keeps the unit tests fast and broker-free.
"""
