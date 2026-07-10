"""Client layer.

Clients are thin, single-responsibility adapters that talk to external
providers (HTTP APIs, object stores, etc.). They expose async methods and know
nothing about business rules — that is the service layer's job.
"""
