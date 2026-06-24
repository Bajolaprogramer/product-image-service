"""Observability: Prometheus metrics and the HTTP metrics middleware.

Centralizes all metric definitions and the cross-cutting instrumentation so the
rest of the app depends on small, named helpers rather than scattering metric
plumbing through business logic.
"""
