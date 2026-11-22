"""Compatibility import path; implementation lives in cpu_data.application.update."""
import sys
from cpu_data.application import update as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
