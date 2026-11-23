"""Compatibility entry point; implementation lives in cpu_data.updater."""
import sys
from cpu_data import updater as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
