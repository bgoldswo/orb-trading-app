"""ORB signal logic. IMPLEMENTED IN PHASE 2.

LOOK-AHEAD SAFETY CONTRACT (do not violate when implementing):
- OR_high / OR_low are fixed only AFTER the opening-range window closes. No bar
  inside or after the window may use information from later bars.
- A breakout is detected on a COMPLETED bar (bar_close confirmation). The entry
  is executed at the NEXT bar's open. We never assume a fill at a price the bar
  had not yet traded through at the moment of the decision.
- If a single bar's range spans BOTH the stop and the target, the intrabar path
  is unknown from OHLC alone — resolve conservatively (assume the stop hit
  first). This is the easiest place to accidentally inflate results.
"""

from __future__ import annotations


def compute_opening_range(bars, cfg):
    raise NotImplementedError("Implemented in Phase 2.")


def generate_signals(bars, cfg):
    raise NotImplementedError("Implemented in Phase 2.")
