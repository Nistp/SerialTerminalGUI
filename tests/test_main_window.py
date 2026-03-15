"""Tests for pure helper logic extracted from app/gui/main_window.py.

GUI widget construction is intentionally excluded (requires a Tk event loop).
Only the stateless calculation helpers are covered here.
"""

import pytest
from app.gui.main_window import _calculate_sash_positions


# ---------------------------------------------------------------------------
# _calculate_sash_positions
# ---------------------------------------------------------------------------

class TestCalculateSashPositions:
    """Sash position calculation for the collapsible suite PanedWindow."""

    # --- basic edge cases ---------------------------------------------------

    def test_single_pane_returns_empty(self):
        assert _calculate_sash_positions(["p0"], set(), 800) == []

    def test_empty_panes_returns_empty(self):
        assert _calculate_sash_positions([], set(), 800) == []

    # --- two panes ----------------------------------------------------------

    def test_two_panes_both_expanded_equal_split(self):
        # Each pane gets half the total width.
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, set(), 800)
        assert positions == [400]

    def test_two_panes_first_collapsed(self):
        # p0 is collapsed → sash sits at collapsed_width.
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, {"p0"}, 800)
        assert positions == [50]

    def test_two_panes_last_collapsed(self):
        # p1 is the last pane — no sash after it.
        # The sash between p0 and p1 should sit at total - collapsed_width.
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, {"p1"}, 800)
        assert positions == [750]

    def test_two_panes_both_collapsed(self):
        # Both collapsed → sash at collapsed_width.
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, {"p0", "p1"}, 800)
        assert positions == [50]

    # --- four panes ---------------------------------------------------------

    def test_four_panes_all_expanded_equal_split(self):
        panes = ["p0", "p1", "p2", "p3"]
        positions = _calculate_sash_positions(panes, set(), 1200)
        # ew = 1200 // 4 = 300
        assert positions == [300, 600, 900]

    def test_four_panes_one_collapsed_first(self):
        panes = ["p0", "p1", "p2", "p3"]
        # cw=50, n_collapsed=1, n_expanded=3, ew=(1200-50)//3=383
        positions = _calculate_sash_positions(panes, {"p0"}, 1200)
        assert positions == [50, 50 + 383, 50 + 766]

    def test_four_panes_one_collapsed_middle(self):
        panes = ["p0", "p1", "p2", "p3"]
        # p1 collapsed: cw=50, ew=(1200-50)//3=383
        # sash0: p0 expanded → 383
        # sash1: p1 collapsed → 383+50=433
        # sash2: p2 expanded → 433+383=816
        positions = _calculate_sash_positions(panes, {"p1"}, 1200)
        assert positions == [383, 433, 816]

    def test_four_panes_two_collapsed(self):
        panes = ["p0", "p1", "p2", "p3"]
        # p0, p2 collapsed: n_collapsed=2, n_expanded=2, ew=(1200-100)//2=550
        # sash0: p0 collapsed → 50
        # sash1: p1 expanded  → 50+550=600
        # sash2: p2 collapsed → 600+50=650
        positions = _calculate_sash_positions(panes, {"p0", "p2"}, 1200)
        assert positions == [50, 600, 650]

    def test_four_panes_all_collapsed(self):
        panes = ["p0", "p1", "p2", "p3"]
        # n_expanded=0 → ew=(1200-200)//1=1000, but only collapsed panes
        # so each sash advances by cw=50
        positions = _calculate_sash_positions(panes, {"p0", "p1", "p2", "p3"}, 1200)
        assert positions == [50, 100, 150]

    # --- custom collapsed_width ---------------------------------------------

    def test_custom_collapsed_width(self):
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, {"p0"}, 800, collapsed_width=80)
        assert positions == [80]

    # --- odd total widths (integer division) --------------------------------

    def test_odd_total_width_truncates(self):
        # 801 // 2 == 400 (truncated, not rounded)
        panes = ["p0", "p1"]
        positions = _calculate_sash_positions(panes, set(), 801)
        assert positions == [400]

    def test_three_panes_indivisible_width(self):
        # 1000 // 3 == 333
        panes = ["p0", "p1", "p2"]
        positions = _calculate_sash_positions(panes, set(), 1000)
        assert positions == [333, 666]
