from __future__ import annotations

from prtrack.utils.time import (
    HOUR_PER_DAY,
    MINUTE_PER_HOUR,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    format_time_ago,
)


def test_time_constants():
    """Test that time constants are correctly defined."""
    assert SECONDS_PER_MINUTE == 60
    assert MINUTE_PER_HOUR == 60
    assert HOUR_PER_DAY == 24
    assert SECONDS_PER_HOUR == 3600  # 60 * 60
    assert SECONDS_PER_DAY == 86400  # 3600 * 24


def test_format_time_ago_seconds():
    """Test format_time_ago with seconds."""
    # Test values less than a minute
    assert format_time_ago(0) == "0s ago"
    assert format_time_ago(30) == "30s ago"
    assert format_time_ago(59) == "59s ago"


def test_format_time_ago_minutes():
    """Test format_time_ago with minutes."""
    # Test values at least a minute but less than an hour
    assert format_time_ago(60) == "1m ago"  # 1 minute
    assert format_time_ago(120) == "2m ago"  # 2 minutes
    assert format_time_ago(3599) == "59m ago"  # 59 minutes and 59 seconds


def test_format_time_ago_hours():
    """Test format_time_ago with hours."""
    # Test values at least an hour but less than a day
    assert format_time_ago(3600) == "1h ago"  # 1 hour
    assert format_time_ago(7200) == "2h ago"  # 2 hours
    assert format_time_ago(82800) == "23h ago"  # 23 hours


def test_format_time_ago_days():
    """Test format_time_ago with days."""
    # Test values at least a day
    assert format_time_ago(86400) == "1d ago"  # 1 day
    assert format_time_ago(172800) == "2d ago"  # 2 days
    assert format_time_ago(864000) == "10d ago"  # 10 days


def test_format_time_ago_boundary_conditions():
    """Test format_time_ago at boundary conditions."""
    # Exactly at minute boundary
    assert format_time_ago(60) == "1m ago"

    # Exactly at hour boundary
    assert format_time_ago(3600) == "1h ago"

    # Exactly at day boundary
    assert format_time_ago(86400) == "1d ago"

    # Just below minute boundary
    assert format_time_ago(59) == "59s ago"

    # Just below hour boundary
    assert format_time_ago(3599) == "59m ago"

    # Just below day boundary
    assert format_time_ago(86399) == "23h ago"


def test_format_time_ago_large_values():
    """Test format_time_ago with large values."""
    # Test with a large number of seconds
    assert format_time_ago(1000000) == "11d ago"  # Approximately 11.57 days
