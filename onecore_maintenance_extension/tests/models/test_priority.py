from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.constants import PRIORITY_CUSTOM, LEGACY_PRIORITY_WEEKS
from ...models.utils.priority import priority_days_from, priority_label_for
from ..utils.test_utils import create_internal_user, create_maintenance_request


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

    def test_preset_beats_a_leftover_weeks_value(self):
        """Branch-ordering regression, not arithmetic.

        Nothing ever clears priority_weeks when a request leaves 'custom' —
        not the form, not write(), not the 19.0.1.0.12 migration (which
        WRITES priority_weeks on every migrated row and never touches it
        again). So a migrated ärende permanently carries a priority_weeks of
        2..52 no matter what preset it is later given, and the only thing
        that keeps priority_days correct is that priority_days_from checks
        `preset == PRIORITY_CUSTOM` before it ever looks at weeks — see the
        `if preset == PRIORITY_CUSTOM` / `return int(preset)` ordering in
        priority.py. If a future edit checked `if weeks:` first instead, this
        test would start failing while every other preset-only test (which
        all pass weeks=False) would keep passing.

        Akut is the case that matters most: a migrated "6 månader" ärende
        (priority_weeks=26) re-prioritised to Akut must land on 0 days, not
        182 — the difference between a same-day and a six-months-out
        förfallodatum on the most urgent class of ärende.
        """
        self.assertEqual(priority_days_from("0", 26), 0)
        self.assertEqual(priority_days_from("7", 26), 7)

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

    def test_preset_beats_a_leftover_priority_weeks_on_the_model(self):
        """Model-level twin of TestPriorityHelpers.test_preset_beats_a_leftover_weeks_value.

        Nothing on this model ever clears priority_weeks when leaving
        'custom' — reproduces a migrated-then-reprioritised ärende directly
        through create(), the same way a handläggare would trigger it: pick
        Akut on a request that (as every migrated legacy row does) already
        carries a non-zero priority_weeks from the 19.0.1.0.12 migration.
        """
        request = create_maintenance_request(
            self.env, priority_expanded="0", priority_weeks=26
        )
        self.assertEqual(request.priority_days, 0)
        self.assertEqual(request.priority_label, "Akut")


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

    def test_custom_without_weeks_keeps_the_previous_due_date(self):
        """Picking 'Antal veckor' before typing a number must not look like Akut.

        The weeks box is empty (shown as 0) until the handläggare types in it,
        and priority_days is 0 then. Saving is blocked by the constraint, but
        the form's onchange still recomputes — so förfallodatum must hold
        still instead of jumping to the base date, and the label stay empty.
        Uses new() because that is the unsaved record the form works on.
        """
        request_date = date.today()
        request = self.env["maintenance.request"].new(
            {"request_date": request_date, "priority_expanded": "7"}
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=7))

        request.priority_expanded = PRIORITY_CUSTOM
        self.assertEqual(request.due_date, request_date + timedelta(days=7))
        self.assertFalse(request.priority_label)

        request.priority_weeks = 3
        self.assertEqual(request.due_date, request_date + timedelta(days=21))
        self.assertEqual(request.priority_label, "3 veckor")

    def test_manual_due_date_survives_a_weeks_change(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=2
        )
        manual = date.today() + timedelta(days=99)
        request.write({"priority_weeks": 4, "due_date": manual})
        self.assertEqual(request.due_date, manual)


@tagged("onecore")
class TestPriorityStageGate(TransactionCase):
    """maintenance_workflow_service gates handling stages on priority being
    set. Akut is 0 days, and Odoo reads a NULL Integer as 0 — so if that gate
    is ever moved from priority_expanded onto priority_days, every Akut ärende
    silently becomes unmovable. These two tests are the tripwire."""

    def setUp(self):
        super().setUp()
        self.stage_vantar = self.env["maintenance.stage"].search(
            [("name", "=", "Väntar på handläggning")]
        )
        self.stage_tilldelad = self.env["maintenance.stage"].search(
            [("name", "=", "Resurs tilldelad")]
        )
        self.internal_user = create_internal_user(self.env)

    def test_akut_request_can_move_to_a_handling_stage(self):
        """Akut (priority_days == 0, same as unset) must still be movable.

        The user is assigned in the same write as the stage change, so
        ``has_user`` is true from ``vals`` and the resource check is
        skipped — the only thing standing between this write and success is
        the priority gate.
        """
        request = create_maintenance_request(
            self.env, stage_id=self.stage_vantar.id, priority_expanded="0"
        )
        self.assertEqual(request.priority_days, 0)

        request.write(
            {"stage_id": self.stage_tilldelad.id, "user_id": self.internal_user.id}
        )
        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_request_without_priority_is_still_blocked(self):
        """A genuinely unset priority must still block the move — and for
        the priority reason specifically.

        ``_validate_priority_set`` (maintenance_workflow_service.py:107) runs
        before ``_validate_unassigned_resource`` inside ``handle_stage_change``
        (maintenance_workflow_service.py:28-36), so this record — created with
        no priority and no resource — already raises the priority UserError
        first. Asserting on the exact message (rather than any UserError)
        keeps this test honest even if that ordering is ever reversed.
        """
        request = create_maintenance_request(
            self.env, stage_id=self.stage_vantar.id, priority_expanded=False
        )

        with self.assertRaisesRegex(UserError, "Prioritet måste anges"):
            request.write({"stage_id": self.stage_tilldelad.id})
