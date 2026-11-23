"""Typed errors raised by external data source adapters."""


class DataSourceError(RuntimeError):
    """Base class for source acquisition and parsing failures."""


class DataSourceParseError(DataSourceError):
    """The source responded, but its HTML no longer matches a known layout."""
