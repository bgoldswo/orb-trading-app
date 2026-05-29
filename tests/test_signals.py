"""Paper-signal engine: scanning, sizing, idempotent logging, and no-orders."""

from __future__ import annotations

import dataclasses
import json

import pandas as pd
import pytest

from orb.config import ORBConfig
from orb.signals import (
    PaperSignal,
    load_signal_log,
    log_signals,
    scan_for_signals,
)
from synthetic import flat_day, set_bar, set_opening_range

DATE = "2024-03-04"


def breakout_day(date=DATE):
    df = flat_day(date, price=100.0)
    set_opening_range(df, date, high=100.0, low=99.0)
    set_bar(df, date, "09:45", c=100.5)  # confirms long
    set_bar(df, date, "09:46", o=100.5)  # entry reference
    return df


def test_scan_emits_one_signal_with_correct_plan():
    sigs = scan_for_signals({"SPY": breakout_day()}, ORBConfig(), emitted_at="2026-05-29T20:00:00Z")
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s, PaperSignal)
    assert s.symbol == "SPY" and s.direction == "long" and s.asof_date == DATE
    assert s.reference_entry == 100.5
    assert s.stop_level == 99.0                      # opposite range
    assert s.target_level == pytest.approx(103.5)    # entry 100.5 + 2R, R = 1.5
    assert s.risk_per_share == pytest.approx(1.5)
    # risk-based size: 1% of 100k = $1000 / $1.5 risk = 666 whole shares
    assert s.suggested_shares == 666
    assert s.emitted_at == "2026-05-29T20:00:00Z"


def test_scan_places_no_orders():
    sigs = scan_for_signals({"SPY": breakout_day()}, ORBConfig())
    assert all(s.placed_order is False for s in sigs)
    assert all("no order" in s.note.lower() for s in sigs)


def test_scan_respects_long_only_default_and_short_mode():
    df = flat_day(DATE, price=100.0)
    set_opening_range(df, DATE, high=101.0, low=100.0)
    set_bar(df, DATE, "09:45", c=99.0)  # downside breakout
    set_bar(df, DATE, "09:46", o=99.0)
    assert scan_for_signals({"X": df}, ORBConfig()) == []  # long_only ignores it
    short_cfg = dataclasses.replace(ORBConfig(), direction="long_short")
    sigs = scan_for_signals({"X": df}, short_cfg)
    assert len(sigs) == 1 and sigs[0].direction == "short"
    assert sigs[0].stop_level == 101.0  # opposite range = OR high for a short


def test_scan_picks_latest_session_by_default():
    bars = pd.concat([flat_day("2024-03-04", 100.0), breakout_day("2024-03-05")])
    sigs = scan_for_signals({"SPY": bars}, ORBConfig())
    assert len(sigs) == 1 and sigs[0].asof_date == "2024-03-05"


def test_scan_asof_selects_specific_day():
    bars = pd.concat([breakout_day("2024-03-04"), flat_day("2024-03-05", 100.0)])
    sigs = scan_for_signals({"SPY": bars}, ORBConfig(), asof="2024-03-04")
    assert len(sigs) == 1 and sigs[0].asof_date == "2024-03-04"


def test_log_is_idempotent_and_roundtrips(tmp_path):
    log = tmp_path / "signals.jsonl"
    sigs = scan_for_signals({"SPY": breakout_day()}, ORBConfig())

    new1 = log_signals(sigs, log)
    new2 = log_signals(sigs, log)  # same session+symbol -> no duplicates
    assert len(new1) == 1
    assert new2 == []
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1

    df = load_signal_log(log)
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "SPY"
    # The line is valid JSON with the no-order flag.
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["placed_order"] is False


def test_load_signal_log_empty_when_missing(tmp_path):
    assert load_signal_log(tmp_path / "nope.jsonl").empty
