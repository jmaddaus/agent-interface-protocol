from __future__ import annotations

import pytest

from agent_interface_protocol import (
    MAX_SUPPORTED_PROTOCOL_VERSION,
    MIN_SUPPORTED_PROTOCOL_VERSION,
    negotiate_protocol_version,
)


def test_overlapping_ranges_pick_common_max():
    assert negotiate_protocol_version((2, 3), (1, 2)) == 2
    assert negotiate_protocol_version((1, 2), (2, 3)) == 2
    assert negotiate_protocol_version((1, 3), (1, 3)) == 3


def test_one_range_inside_the_other():
    assert negotiate_protocol_version((2, 2), (1, 3)) == 2
    assert negotiate_protocol_version((1, 3), (2, 2)) == 2


def test_non_overlapping_returns_none():
    assert negotiate_protocol_version((5, 6), (1, 2)) is None
    assert negotiate_protocol_version((1, 2), (5, 6)) is None


def test_default_receiver_is_this_build_supported_range():
    """Omitting receiver_range defaults to this build's range."""
    high = MAX_SUPPORTED_PROTOCOL_VERSION
    low = MIN_SUPPORTED_PROTOCOL_VERSION
    assert negotiate_protocol_version((low, high)) == high
    assert negotiate_protocol_version((high, high + 5)) == high
    assert negotiate_protocol_version((high + 10, high + 20)) is None


def test_invalid_sender_range_rejected():
    with pytest.raises(ValueError, match="invalid sender_range"):
        negotiate_protocol_version((3, 1))


def test_invalid_receiver_range_rejected():
    with pytest.raises(ValueError, match="invalid receiver_range"):
        negotiate_protocol_version((1, 2), (3, 1))


def test_single_version_ranges():
    assert negotiate_protocol_version((2, 2), (2, 2)) == 2
    assert negotiate_protocol_version((2, 2), (3, 3)) is None
