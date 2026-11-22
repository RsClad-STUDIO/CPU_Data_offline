"""Compatibility import path; implementation lives in cpu_data.infrastructure.database."""
import sys
from cpu_data.infrastructure import database as _implementation

sys.modules[__name__] = _implementation
