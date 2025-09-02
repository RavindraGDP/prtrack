from __future__ import annotations

# Time conversion constants
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


def format_time_ago(seconds: int) -> str:
    """Convert seconds to a human-readable time-ago string.

    Args:
        seconds: Number of seconds ago.

    Returns:
        Human-readable time string (e.g., "5m ago").
    """
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s ago"
    if seconds < SECONDS_PER_HOUR:
        minutes = seconds // SECONDS_PER_MINUTE
        return f"{minutes}m ago"
    if seconds < SECONDS_PER_DAY:
        hours = seconds // SECONDS_PER_HOUR
        return f"{hours}h ago"
    days = seconds // SECONDS_PER_DAY
    return f"{days}d ago"
