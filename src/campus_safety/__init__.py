"""Location-aware campus safety signal for IU Bloomington."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("campus-safety-signal")
except PackageNotFoundError:  # Lambda ships src/ without install metadata
    __version__ = "0.1.0"
