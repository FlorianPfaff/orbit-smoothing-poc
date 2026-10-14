"""Versioned comparison protocol, independent of the published v2 experiment."""

from .config import ComparisonConfig, load_config

__all__ = ["ComparisonConfig", "load_config"]
