import decimal
import unittest

from providers import _common

FIRST_READ_FROM_TS = 1_760_000_000
WINDOW = {"from_ts": 1_760_003_600, "to_ts": 1_760_007_200, "first_read_from_ts": FIRST_READ_FROM_TS}


class ReadStartTest(unittest.TestCase):
    def test_starts_at_the_first_read_start_when_there_is_no_cursor(self):
        self.assertEqual(_common.read_start(WINDOW, None), FIRST_READ_FROM_TS)

    def test_starts_at_a_cursor_later_than_the_first_read_start(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS + 500), FIRST_READ_FROM_TS + 500)

    def test_starts_at_the_first_read_start_when_the_cursor_is_earlier(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS - 500), FIRST_READ_FROM_TS)

    def test_starts_at_the_first_read_start_when_the_cursor_equals_it(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS), FIRST_READ_FROM_TS)

    def test_keeps_the_exact_value_of_a_later_decimal_cursor(self):
        cursor = decimal.Decimal("1760000500.000050")
        self.assertEqual(_common.read_start(WINDOW, cursor), cursor)

    def test_starts_at_the_first_read_start_when_a_decimal_cursor_is_earlier(self):
        self.assertEqual(_common.read_start(WINDOW, decimal.Decimal("1759999999.999999")), FIRST_READ_FROM_TS)

    def test_ignores_the_run_window_start(self):
        window = {**WINDOW, "from_ts": FIRST_READ_FROM_TS + 9000}
        self.assertEqual(_common.read_start(window, FIRST_READ_FROM_TS + 100), FIRST_READ_FROM_TS + 100)


if __name__ == "__main__":
    unittest.main()
