"""JARVIS 2.0 version metadata for health / release probes."""

from __future__ import annotations

__version__ = "2.1.0"
__codename__ = "Personal AI OS"
PHASE = "0-14-complete"


def version_info() -> dict[str, str]:
    return {
        "version": __version__,
        "codename": __codename__,
        "phase": PHASE,
    }
