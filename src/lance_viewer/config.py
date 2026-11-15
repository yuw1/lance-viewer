"""App config: dependency availability flags (pylance/pyarrow) + path constants."""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

try:
    import lance  # pylance package (import name is lance)
    LANCE_AVAILABLE = True
except ImportError:
    lance = None
    LANCE_AVAILABLE = False

try:
    import pyarrow as pa
    import pyarrow.ipc as ipc
    PYARROW_AVAILABLE = True
except ImportError:
    pa = None
    ipc = None
    PYARROW_AVAILABLE = False


