"""Store ("tienda") use-case package.

Exposes ``build_registry(config)`` consumed by ``core.load_agent("tienda")``.
This is the only required entry point a use-case must provide.
"""
from .tools import build_registry

__all__ = ["build_registry"]
