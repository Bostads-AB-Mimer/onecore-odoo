"""Tests for MIM-1970 — "Beställande resursgrupp" on maintenance requests.

Covers the create() stamp (including the Mina sidor case, where create_uid is
a technical integration user and a derivation would be meaningless), the
backfill cron and its guess stamp, and the search facet that makes the
follow-up views MIM-1975/1976/1977 pure configuration.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import (
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)


@tagged("onecore")
class TestOrderingTeamService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.kundcenter = self.env.ref("onecore_maintenance_extension.7")

        self.district_user = create_internal_user(self.env)
        self.district_team = create_maintenance_team(
            self.env,
            name="Distrikt Testväst",
            cost_center_code="61140",
            member_ids=[(4, self.district_user.id)],
        )

        self.other_user = create_internal_user(self.env)
        self.other_team = create_maintenance_team(
            self.env,
            name="Annan resursgrupp",
            cost_center_code="61130",
            member_ids=[(4, self.other_user.id)],
        )

        # No team at all — falls through to Kundcenter
        self.teamless_user = create_internal_user(self.env)

    def _clear_ordering(self, *requests):
        """Make a request look like it predates MIM-1970."""
        for request in requests:
            request.sudo().write(
                {"ordering_team_id": False, "ordering_cost_center_code": False}
            )

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def test_create_stamps_the_creators_team(self):
        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_team_id, self.district_team)
        # Denormalised so the district facet does not have to join
        self.assertEqual(request.ordering_cost_center_code, "61140")
        # Not a guess: it was recorded while we knew
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_prefers_owner_over_creator(self):
        """owner_user_id is the orderer when it is set; create_uid is a fallback."""
        request = create_maintenance_request(
            self.env(user=self.district_user), owner_user_id=self.other_user.id
        )

        self.assertEqual(request.create_uid, self.district_user)
        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    def test_create_falls_back_to_kundcenter_without_a_team(self):
        request = create_maintenance_request(self.env(user=self.teamless_user))

        self.assertEqual(request.ordering_team_id, self.kundcenter)
        # Kundcenter carries no cost center, so the district code stays empty
        self.assertFalse(request.ordering_cost_center_code)

    def test_create_from_mimer_nu_resolves_kundcenter_not_the_integration_user(self):
        """MIM-1970's decisive case.

        Mina sidor-ärenden arrive over XML-RPC with a technical integration
        user as create_uid. Here that user is deliberately a member of another
        team: the stamp must still be Kundcenter, because the tenant ordered
        the request and the integration user's membership says nothing. This
        is exactly what a derived field would get wrong — and it would get it
        wrong for the largest inflow.
        """
        integration_user = create_internal_user(self.env)
        self.other_team.write({"member_ids": [(4, integration_user.id)]})

        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.create_uid, integration_user)
        self.assertEqual(request.ordering_team_id, self.kundcenter)
        self.assertNotEqual(request.ordering_team_id, self.other_team)

    def test_create_keeps_a_team_stamped_by_the_caller(self):
        """core over XML-RPC (and later MIM-1971) wins over the derivation."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            ordering_team_id=self.other_team.id,
            ordering_cost_center_code="61130",
        )

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    def test_create_fills_the_district_code_when_only_the_team_was_stamped(self):
        """A caller may pass just the team. The denormalised code has to
        follow, or the district facet misses the request forever — the
        backfill only ever revisits rows without an ordering team."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            ordering_team_id=self.other_team.id,
        )

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------
    def test_backfill_stamps_old_requests_and_marks_them_as_guessed(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        processed = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(processed, 1)
        self.assertEqual(request.ordering_team_id, self.district_team)
        self.assertEqual(request.ordering_cost_center_code, "61140")
        # The stamp is what separates a guess from a recorded fact
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_never_touches_team_resource_or_stage(self):
        """Display only: the backfill must not reroute anything."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            maintenance_team_id=self.other_team.id,
            user_id=self.other_user.id,
        )
        self._clear_ordering(request)
        team_before = request.maintenance_team_id
        user_before = request.user_id
        stage_before = request.stage_id

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.maintenance_team_id, team_before)
        self.assertEqual(request.user_id, user_before)
        self.assertEqual(request.stage_id, stage_before)

    def test_backfill_is_self_consuming(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        first = self.env["maintenance.request"]._cron_backfill_ordering_team()
        second = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)

    def test_backfill_resolves_mimer_nu_to_kundcenter(self):
        integration_user = create_internal_user(self.env)
        self.other_team.write({"member_ids": [(4, integration_user.id)]})
        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.kundcenter)

    def test_backfill_leaves_no_chatter_note(self):
        """SKIP_FIELDS: the backfill writes outside the creating_records
        context, so without it every stamped request would get a note."""
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)
        messages_before = len(request.message_ids)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(len(request.message_ids), messages_before)

    # ------------------------------------------------------------------
    # Cron record / search facet
    # ------------------------------------------------------------------
    def test_backfill_cron_exists(self):
        cron = self.env.ref(
            "onecore_maintenance_extension.ir_cron_backfill_ordering_team"
        )

        self.assertEqual(cron.model_id.model, "maintenance.request")
        self.assertTrue(cron.active)
        self.assertIn("_cron_backfill_ordering_team", cron.code)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "hours"))

    def test_search_view_exposes_the_facet_and_grouping(self):
        """What makes MIM-1975/1976/1977 configuration instead of development."""
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_search_extension"
        )

        self.assertIn('name="ordering_team_id"', view.arch_db)
        self.assertIn('name="ordering_cost_center_code"', view.arch_db)
        self.assertIn("'group_by': 'ordering_team_id'", view.arch_db)
