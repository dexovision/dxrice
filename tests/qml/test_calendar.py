#!/usr/bin/env python3
"""The calendar panel's month change: the right month lands, the grid and the
label slide out and back in, clicks in a hurry still land on the right month,
and reduced motion makes it instant.

    python3 tests/qml/test_calendar.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402
from test_customization import with_theme  # noqa: E402

CAL = "findNamed('calendarPanel')"


class MonthChangeTest(unittest.TestCase):
    def open(self, **theme):
        self.s = Scene(width=1920, height=1080, setup=with_theme(**theme))
        self.s.ev("panels.open('calendar')")
        self.s.wait(900)
        self.s.ev(f"{CAL}.viewDate = new Date(2026, 5, 1)")   # June 2026
        self.s.wait(50)

    def tearDown(self):
        self.s.close()

    def month(self):
        return self.s.ev("findNamed('calendarMonth').text")

    def test_next_and_previous_land_on_the_right_month(self):
        self.open()
        self.s.ev(f"{CAL}.nextMonth()")
        self.s.wait(700)
        self.assertEqual(self.month(), "July 2026")
        self.s.ev(f"{CAL}.prevMonth()"); self.s.wait(700)
        self.s.ev(f"{CAL}.prevMonth()"); self.s.wait(700)
        self.assertEqual(self.month(), "May 2026")

    def record(self, signal, expr):
        """A recorder inside the panel that pushes `expr` (about `p`, the
        panel) whenever `signal` fires, readable as findNamed('rec').seen:
        polling from Python is too coarse to see a 100 ms animation."""
        qml = ("import QtQuick; Item { id: r; objectName: 'rec'; property var seen: []; "
               "Connections { target: r.parent; function %s() { var p = r.parent; r.seen.push(%s); } } }" % (signal, expr))
        self.s.ev(f"Qt.createQmlObject({json.dumps(qml)}, {CAL}, 'rec')")

    def seen(self):
        return self.s.ev("JSON.stringify(findNamed('rec').seen)")

    def test_the_grid_slides_out_and_back_through_invisible(self):
        self.open()
        self.record("onShiftChanged", "[p.shift, p.monthGrid.opacity, p.monthGrid.x]")
        self.s.ev(f"{CAL}.nextMonth()")
        self.s.wait(900)
        frames = json.loads(self.seen())
        self.assertGreater(len(frames), 4, "the change was not animated")
        self.assertEqual(min(f[1] for f in frames), 0, "the grid never faded out completely")
        self.assertTrue(any(f[2] < -1 for f in frames), "the grid never slid out to the left")
        self.assertTrue(any(f[2] > 1 for f in frames), "the grid never came in from the right")
        self.assertEqual(frames[-1][1:], [1, 0])

    def test_the_month_changes_only_while_it_is_hidden(self):
        self.open()
        self.record("onViewDateChanged", "p.shift")
        self.s.ev(f"{CAL}.nextMonth()")
        self.s.wait(900)
        self.assertEqual([abs(v) for v in json.loads(self.seen())], [1], "the month swapped while the grid was still visible")

    def test_clicking_three_times_in_a_hurry_lands_three_months_on(self):
        self.open()
        for _ in range(3):
            self.s.ev(f"{CAL}.nextMonth()")
            self.s.wait(40)
        self.s.wait(1200)
        self.assertEqual(self.month(), "September 2026")
        self.assertEqual(self.s.ev("findNamed('calendarGrid').opacity"), 1)

    def test_reduced_motion_is_instant_enough(self):
        self.open(reduce_motion=True, anim_duration_ms=0)
        self.s.ev(f"{CAL}.nextMonth()")
        self.s.wait(120)
        self.assertEqual(self.month(), "July 2026")
        self.assertEqual(self.s.ev("findNamed('calendarGrid').opacity"), 1)

    def test_the_days_are_the_real_days(self):
        self.open()
        self.assertEqual(self.s.ev(f"{CAL}.weeks.length"), 5)          # June 2026: Mon 1st .. Tue 30th
        self.s.ev(f"{CAL}.nextMonth()"); self.s.wait(700)
        self.assertEqual(self.s.ev(f"{CAL}.weeks[0][3].getDate()"), 1)  # July 1st 2026 is a Wednesday


if __name__ == "__main__":
    unittest.main()
