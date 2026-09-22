from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.constants import PRIORITY_CUSTOM, LEGACY_PRIORITY_WEEKS
from ...models.utils.priority import priority_days_from, priority_label_for
from ..utils.test_utils import create_maintenance_request


@tagged("onecore")
class TestPriorityHelpers(TransactionCase):
    """Pure arithmetic — no records involved, but kept in the Odoo suite so
    it runs in CI alongside everything else."""

    def test_days_from_preset(self):
        for preset, expected in (("0", 0), ("1", 1), ("5", 5), ("7", 7), ("10", 10)):
            self.assertEqual(priority_days_from(preset, False), expected)

    def test_days_from_custom_weeks(self):
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, 3), 21)
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, 26), 182)

    def test_days_is_zero_without_a_preset(self):
        """0 here is incidental, not Akut. Odoo Integers cannot be NULL, so
        the caller must check priority_expanded before trusting this."""
        self.assertEqual(priority_days_from(False, 0), 0)

    def test_days_is_zero_when_custom_without_weeks(self):
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, 0), 0)
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, False), 0)

    def test_label_for_zero_is_akut(self):
        """The helper is pure arithmetic: 0 days is Akut. Suppressing the
        label for an unprioritised ärende is the model's job, not this one's."""
        self.assertEqual(priority_label_for(0), "Akut")

    def test_label_days_and_weeks(self):
        self.assertEqual(priority_label_for(1), "1 dag")
        self.assertEqual(priority_label_for(5), "5 dagar")
        self.assertEqual(priority_label_for(7), "7 dagar")
        self.assertEqual(priority_label_for(10), "10 dagar")
        self.assertEqual(priority_label_for(14), "2 veckor")
        self.assertEqual(priority_label_for(21), "3 veckor")
        self.assertEqual(priority_label_for(182), "26 veckor")

    def test_label_for_non_week_multiple_falls_back_to_days(self):
        """A legacy value that is not a whole number of weeks stays honest."""
        self.assertEqual(priority_label_for(183), "183 dagar")

    def test_legacy_mapping_is_consistent_with_the_arithmetic(self):
        """Every retired value maps to weeks the helpers agree with.

        The 19.0.1.0.12 migration writes these weeks into priority_weeks and
        lets init_models() derive priority_days from them, so a typo in the
        table would silently shift a live ärende's förfallodatum. 183 and 365
        are deliberately NOT whole weeks — they round to 182 and 364.
        """
        for value, weeks in LEGACY_PRIORITY_WEEKS.items():
            self.assertEqual(
                priority_days_from(PRIORITY_CUSTOM, weeks),
                weeks * 7,
                "legacy value %s maps to %d weeks" % (value, weeks),
            )
            self.assertLessEqual(
                abs(int(value) - weeks * 7),
                1,
                "legacy value %s must not move by more than a day" % value,
            )


@tagged("onecore")
class TestPriorityFields(TransactionCase):
    def test_preset_sets_days_and_label(self):
        request = create_maintenance_request(self.env, priority_expanded="10")
        self.assertEqual(request.priority_days, 10)
        self.assertEqual(request.priority_label, "10 dagar")

    def test_custom_weeks_sets_days_and_label(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=9
        )
        self.assertEqual(request.priority_days, 63)
        self.assertEqual(request.priority_label, "9 veckor")

    def test_changing_weeks_recomputes_days(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=2
        )
        request.write({"priority_weeks": 4})
        self.assertEqual(request.priority_days, 28)
        self.assertEqual(request.priority_label, "4 veckor")

    def test_unset_priority_is_not_mistaken_for_akut(self):
        """The 0-collision regression test.

        priority_days is 0 for BOTH an unset ärende and an Akut one — Odoo
        Integers cannot be NULL. So the label must stay empty, and the Akut
        filter must key on priority_expanded, which is nullable and does tell
        them apart. If either assertion here fails, some caller has started
        trusting priority_days to answer a question it cannot answer.
        """
        request = create_maintenance_request(self.env, priority_expanded=False)
        self.assertFalse(request.priority_label)

        akut = create_maintenance_request(self.env, priority_expanded="0")
        self.assertEqual(akut.priority_label, "Akut")

        both = (request | akut).ids
        matches_akut = self.env["maintenance.request"].search(
            [("id", "in", both), ("priority_expanded", "=", "0")]
        )
        self.assertEqual(matches_akut, akut, "unset must not match the Akut filter")

        has_priority = self.env["maintenance.request"].search(
            [("id", "in", both), ("priority_expanded", "!=", False)]
        )
        self.assertEqual(has_priority, akut, "unset must not match the range filters")

    def test_custom_rejects_weeks_out_of_range(self):
        for weeks in (0, -1, 53):
            with self.assertRaises(ValidationError):
                create_maintenance_request(
                    self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=weeks
                )

    def test_custom_accepts_range_bounds(self):
        for weeks in (1, 52):
            request = create_maintenance_request(
                self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=weeks
            )
            self.assertEqual(request.priority_days, weeks * 7)


@tagged("onecore")
class TestPriorityDueDate(TransactionCase):
    def test_due_date_from_custom_weeks(self):
        request_date = date.today()
        request = create_maintenance_request(
            self.env,
            request_date=request_date,
            priority_expanded=PRIORITY_CUSTOM,
            priority_weeks=6,
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=42))

    def test_akut_due_date_is_the_base_date(self):
        """Akut is 0 days, not 'no priority' — due_date must still be set."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="0"
        )
        self.assertEqual(request.due_date, request_date)

    def test_manual_due_date_survives_a_weeks_change(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=2
        )
        manual = date.today() + timedelta(days=99)
        request.write({"priority_weeks": 4, "due_date": manual})
        self.assertEqual(request.due_date, manual)
