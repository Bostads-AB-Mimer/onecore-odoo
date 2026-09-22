from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.constants import PRIORITY_CUSTOM, LEGACY_PRIORITY_WEEKS
from ...models.utils.priority import priority_days_from, priority_label_for


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
