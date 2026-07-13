"""OctoPulse v3: local, marker-based project status pulses."""

from .core import MARKER_NAME, RELEASE_VERSION, VERSION

__version__ = RELEASE_VERSION

__all__ = ["MARKER_NAME", "RELEASE_VERSION", "VERSION", "__version__"]
