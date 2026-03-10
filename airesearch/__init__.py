from pkgutil import extend_path
from pathlib import Path

__path__ = extend_path(__path__, __name__)
_src_pkg = Path(__file__).resolve().parent.parent / 'src' / 'airesearch'
if _src_pkg.exists():
    __path__.append(str(_src_pkg))

