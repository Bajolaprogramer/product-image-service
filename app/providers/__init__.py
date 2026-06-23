"""Image provider layer.

Providers are interchangeable adapters that, given a barcode, return domain
:class:`~app.models.product_image.ProductImage` results from a specific source.
They sit between the (provider-agnostic) clients layer and the service layer,
which queries them concurrently and aggregates their output.
"""
