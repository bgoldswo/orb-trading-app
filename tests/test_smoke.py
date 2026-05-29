"""Smoke tests — real assertions so CI green means something."""

from orb.config import ORBConfig


def test_package_imports():
    import orb  # noqa: F401

    assert orb.__version__


def test_default_config_is_sane():
    cfg = ORBConfig()
    assert cfg.opening_range_minutes in (5, 15, 30)
    assert 0 < cfg.risk_per_trade < 1
    assert cfg.take_profit_r > 0


def test_default_entry_is_lookahead_safe():
    # Guards against someone flipping the default to an intrabar/same-bar entry.
    cfg = ORBConfig()
    assert cfg.entry_timing == "next_bar_open"
    assert cfg.breakout_confirmation == "bar_close"
