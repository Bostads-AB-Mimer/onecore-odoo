"""Tests for the planned-date-after-due-date warning flag (MIM-1961)."""
from datetime import date, datetime

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import create_maintenance_request


@tagged("onecore")
class TestScheduleDateAfterDueDate(TransactionCase):
    def setUp(self):
        super().setUp()
        # The flag compares calendar dates in the user's timezone, so the
        # timezone has to be pinned for the comparison to be deterministic.
        self.env.user.tz = "Europe/Stockholm"
        self.due_date = date(2026, 8, 20)

    def _create(self, schedule_date):
        return create_maintenance_request(
            self.env,
            due_date=self.due_date,
            schedule_date=schedule_date,
        )

    def test_flag_set_when_schedule_date_is_after_due_date(self):
        request = self._create(datetime(2026, 8, 21, 8, 0, 0))
        self.assertTrue(request.schedule_date_after_due_date)

    def test_flag_clear_when_schedule_date_is_before_due_date(self):
        request = self._create(datetime(2026, 8, 19, 8, 0, 0))
        self.assertFalse(request.schedule_date_after_due_date)

    def test_flag_clear_when_schedule_date_is_on_due_date(self):
        request = self._create(datetime(2026, 8, 20, 8, 0, 0))
        self.assertFalse(request.schedule_date_after_due_date)

    def test_flag_clear_for_late_time_of_day_on_due_date(self):
        """A time of day on the due date itself is not a breach."""
        request = self._create(datetime(2026, 8, 20, 18, 0, 0))
        self.assertFalse(request.schedule_date_after_due_date)

    def test_flag_uses_user_timezone_not_utc(self):
        """22:30 UTC on the due date is 00:30 the next day in Stockholm."""
        request = self._create(datetime(2026, 8, 20, 22, 30, 0))
        self.assertTrue(request.schedule_date_after_due_date)

    def test_flag_clear_without_schedule_date(self):
        request = self._create(False)
        self.assertFalse(request.schedule_date_after_due_date)

    def test_flag_clear_without_due_date(self):
        request = create_maintenance_request(
            self.env,
            priority_expanded=False,
            schedule_date=datetime(2026, 8, 21, 8, 0, 0),
        )
        self.assertFalse(request.due_date)
        self.assertFalse(request.schedule_date_after_due_date)

    def test_flag_recomputes_when_due_date_moves_before_schedule_date(self):
        request = self._create(datetime(2026, 8, 19, 8, 0, 0))
        self.assertFalse(request.schedule_date_after_due_date)

        request.write({"due_date": date(2026, 8, 18)})
        self.assertTrue(request.schedule_date_after_due_date)
