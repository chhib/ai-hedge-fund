"""Simple logging utility for verbose output control."""

_verbose_enabled = False


def set_verbose(enabled: bool):
    """Set whether verbose logging is enabled."""
    global _verbose_enabled
    _verbose_enabled = enabled


def is_verbose() -> bool:
    """Check if verbose logging is enabled."""
    return _verbose_enabled


def vprint(*args, **kwargs):
    """Print only if verbose logging is enabled."""
    if _verbose_enabled:
        print(*args, **kwargs)