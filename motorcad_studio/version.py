"""Backward-compatible package version export.

Use :mod:`motorcad_studio.release` for release train, asset, API and module
contract metadata.  ``__version__`` remains available for existing callers.
"""
from .release import PRODUCT_VERSION

__version__ = PRODUCT_VERSION

__all__ = ["__version__"]
