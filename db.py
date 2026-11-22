"""Compatibility module; implementation lives in cpu_data.database."""
import sys
from cpu_data import database as _implementation

sys.modules[__name__] = _implementation
