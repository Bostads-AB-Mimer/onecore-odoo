"""Tests for MIM-486 — the "Återsänd" stage and its automation.

Covers: the stage record itself, returned_date stamping/clearing, the hand-back
of the request to the orderer's team (owner_user_id, fallback create_uid,
fallback Kundcenter), the user_id clearing without a stage bounce, and the
external contractor return flow.
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError

from ...utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
)


class StageTestMixin:
    """Mixin for maintenance stage lookups"""

    def _get_stage(self, stage_name):
        """Get maintenance stage by name"""
        return self.env["maintenance.stage"].search([("name", "=", stage_name)])

    def _setup_common_stages(self):
        """Setup commonly used stage references"""
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.stage_paborjad = self._get_stage("Påbörjad")
        self.stage_atersand = self.env.ref(
            "onecore_maintenance_extension.stage_atersand"
        )


@tagged("onecore")
class TestMaintenanceReturnStage(StageTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_common_stages()

        self.internal_user = create_internal_user(self.env)
        self.teamless_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.other_contractor = create_external_contractor_user(self.env)

        self.contractor_team = self.env["maintenance.team"].create(
            {
                "name": "Contractor Team",
                "member_ids": [(4, self.external_user.id), (4, self.other_contractor.id)],
            }
        )
        self.orderer_team = self.env["maintenance.team"].create(
            {"name": "Orderer Team", "member_ids": [(4, self.internal_user.id)]}
        )
        self.kundcenter_team = self.env.ref("onecore_maintenance_extension.7")

    def _create_returnable_request(self, **kwargs):
        """Request on the contractor's team, ordered by internal_user."""
        defaults = {
            "maintenance_team_id": self.contractor_team.id,
            "owner_user_id": self.internal_user.id,
            "stage_id": self.stage_paborjad.id,
            "user_id": self.external_user.id,
        }
        defaults.update(kwargs)
        return create_maintenance_request(self.env, **defaults)

    def test_atersand_stage_exists_with_xmlid_and_values(self):
        """The stage is created by the post_init_hook with the expected values"""
        stage = self.stage_atersand
        self.assertTrue(stage)
        self.assertEqual(stage.name, "Återsänd")
        self.assertTrue(stage.fold)
        self.assertFalse(stage.done)
        self.assertEqual(stage.sequence, 7)

    def test_returned_date_stamped_on_atersand(self):
        """Moving to 'Återsänd' should set returned_date"""
        request = self._create_returnable_request()
        self.assertFalse(request.returned_date)

        request.write({"stage_id": self.stage_atersand.id})
        self.assertTrue(request.returned_date)

    def test_returned_date_cleared_when_leaving_atersand(self):
        """Moving out of 'Återsänd' should clear returned_date"""
        request = self._create_returnable_request()
        request.write({"stage_id": self.stage_atersand.id})
        self.assertTrue(request.returned_date)

        # Move out as an internal user: the default test env user (root) is in
        # the external contractor group and is blocked from leaving Återsänd
        request.with_user(self.internal_user).write(
            {"stage_id": self.stage_vantar.id}
        )
        self.assertFalse(request.returned_date)

    def test_team_switches_to_orderer_team(self):
        """Returning hands the request back to the orderer's team and clears user_id"""
        request = self._create_returnable_request()

        request.write({"stage_id": self.stage_atersand.id})
        self.assertEqual(request.maintenance_team_id, self.orderer_team)
        self.assertFalse(request.user_id)

    def test_team_fallback_to_create_uid_team(self):
        """Without owner_user_id, the creator's team is used"""
        request = create_maintenance_request(
            self.env(user=self.internal_user),
            maintenance_team_id=self.contractor_team.id,
            owner_user_id=False,
            stage_id=self.stage_paborjad.id,
            user_id=self.external_user.id,
        )
        self.assertEqual(request.create_uid, self.internal_user)

        request.write({"stage_id": self.stage_atersand.id})
        self.assertEqual(request.maintenance_team_id, self.orderer_team)

    def test_team_fallback_to_kundcenter(self):
        """An orderer without any team sends the request to Kundcenter"""
        request = self._create_returnable_request(
            owner_user_id=self.teamless_user.id
        )

        request.write({"stage_id": self.stage_atersand.id})
        self.assertEqual(request.maintenance_team_id, self.kundcenter_team)

    def test_orderer_in_multiple_teams_takes_first(self):
        """An orderer in several teams: the first match is used"""
        second_team = self.env["maintenance.team"].create(
            {"name": "Second Orderer Team", "member_ids": [(4, self.internal_user.id)]}
        )
        expected_team = self.env["maintenance.team"].search(
            [("member_ids", "in", [self.internal_user.id])], limit=1
        )
        request = self._create_returnable_request()

        request.write({"stage_id": self.stage_atersand.id})
        self.assertEqual(request.maintenance_team_id, expected_team)
        self.assertIn(request.maintenance_team_id, self.orderer_team | second_team)

    def test_user_cleared_without_stage_bounce(self):
        """Clearing user_id on return must not bounce to 'Väntar på handläggning'"""
        request = self._create_returnable_request()
        self.assertTrue(request.user_id)

        request.write({"stage_id": self.stage_atersand.id})
        self.assertEqual(request.stage_id, self.stage_atersand)
        self.assertFalse(request.user_id)

    def test_clear_user_while_in_atersand_does_not_bounce(self):
        """A later user_id=False write must not move the request out of 'Återsänd'"""
        request = self._create_returnable_request()
        request.write({"stage_id": self.stage_atersand.id})

        request.write({"user_id": False})
        self.assertEqual(request.stage_id, self.stage_atersand)

    def test_contractor_can_return_request(self):
        """An external contractor can return a request; afterwards it leaves their view"""
        request = self._create_returnable_request()

        request.with_user(self.external_user).write(
            {"stage_id": self.stage_atersand.id}
        )

        self.assertTrue(request.returned_date)
        self.assertEqual(request.stage_id, self.stage_atersand)
        self.assertEqual(request.maintenance_team_id, self.orderer_team)
        self.assertFalse(request.user_id)

        # Team-based access is revoked: contractors in the team who are not
        # followers of the request no longer see it. (The returning resource
        # themselves stays a follower via _add_followers, and core maintenance's
        # equipment_request_rule_user still grants followers access.)
        other_contractor_env = self.env(user=self.other_contractor)
        self.assertFalse(
            other_contractor_env["maintenance.request"].search(
                [("id", "=", request.id)]
            )
        )
        with self.assertRaises(AccessError):
            other_contractor_env["maintenance.request"].browse(request.id).name

    def test_contractor_can_return_without_assigned_user(self):
        """Returning from 'Väntar på handläggning' without a resource is allowed"""
        request = self._create_returnable_request(
            stage_id=self.stage_vantar.id, user_id=False
        )

        request.with_user(self.external_user).write(
            {"stage_id": self.stage_atersand.id}
        )
        self.assertEqual(request.stage_id, self.stage_atersand)
        self.assertTrue(request.returned_date)

    def test_returning_contractor_keeps_access_via_follower(self):
        """A non-follower contractor is subscribed on return, so web_save's
        re-read in the same transaction cannot AccessError-rollback the write"""
        request = self._create_returnable_request(
            stage_id=self.stage_vantar.id, user_id=False
        )
        self.assertNotIn(
            self.external_user.partner_id, request.message_partner_ids
        )

        request.with_user(self.external_user).write(
            {"stage_id": self.stage_atersand.id}
        )

        self.assertIn(self.external_user.partner_id, request.message_partner_ids)
        contractor_env = self.env(user=self.external_user)
        self.assertTrue(
            contractor_env["maintenance.request"].search([("id", "=", request.id)])
        )
        self.assertEqual(
            contractor_env["maintenance.request"].browse(request.id).stage_id,
            self.stage_atersand,
        )

    def test_atersand_exempt_from_priority_requirement(self):
        """Returning must work even when no priority is set"""
        request = self._create_returnable_request(
            stage_id=self.stage_vantar.id, user_id=False, priority_expanded=False
        )

        request.with_user(self.internal_user).write(
            {"stage_id": self.stage_atersand.id}
        )
        self.assertEqual(request.stage_id, self.stage_atersand)

    def test_contractor_still_blocked_from_utford_and_to_avslutad(self):
        """Existing contractor stage restrictions are unaffected"""
        request = self._create_returnable_request(stage_id=self.stage_utford.id)
        with self.assertRaisesRegex(UserError, "från Utförd"):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_atersand.id}
            )

        request2 = self._create_returnable_request()
        with self.assertRaisesRegex(UserError, "till Avslutad"):
            request2.with_user(self.external_user).write(
                {"stage_id": self.stage_avslutad.id}
            )

    def test_contractor_blocked_from_moving_out_of_atersand(self):
        """A contractor cannot un-return a request (same block as Utförd/Avslutad)"""
        request = self._create_returnable_request()
        request.with_user(self.external_user).write(
            {"stage_id": self.stage_atersand.id}
        )

        with self.assertRaisesRegex(UserError, "från Återsänd"):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_vantar.id}
            )
        self.assertEqual(request.stage_id, self.stage_atersand)

    def test_atersand_column_folds_only_when_empty(self):
        """The Återsänd kanban column is folded when empty, open when populated"""

        def group_stage_id(value):
            if not value:
                return None
            if isinstance(value, (tuple, list)):
                return value[0]
            return value.id

        def atersand_group(domain):
            # read_group_expand is sent by the webclient for kanban views; it
            # enables both empty-column expansion and __fold stamping
            res = self.env["maintenance.request"].with_context(
                read_group_expand=True
            ).web_read_group(domain, ["stage_id"], auto_unfold=True)
            return next(
                g
                for g in res["groups"]
                if group_stage_id(g["stage_id"]) == self.stage_atersand.id
            )

        # Folded while empty: web_read_group sends no __records for the group
        self.assertNotIn("__records", atersand_group([("id", "=", 0)]))

        request = self._create_returnable_request()
        request.write({"stage_id": self.stage_atersand.id})
        self.assertIn("__records", atersand_group([("id", "=", request.id)]))

    def test_performed_date_cleared_when_returning_from_utford(self):
        """An internal user moving Utförd -> Återsänd clears performed_date"""
        request = self._create_returnable_request(
            user_id=self.internal_user.id, stage_id=self.stage_paborjad.id
        )
        request.write({"stage_id": self.stage_utford.id})
        self.assertTrue(request.performed_date)

        request.with_user(self.internal_user).write(
            {"stage_id": self.stage_atersand.id}
        )
        self.assertFalse(request.performed_date)
        self.assertTrue(request.returned_date)
