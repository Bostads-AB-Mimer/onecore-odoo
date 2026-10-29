"""Whoever passes an ärende on to another resource group becomes its orderer.

Covers OrderingDepartmentService.pass_on and where write() calls it: the new
orderer and department, the log line, the backfill stamp, what is not passing
on (Kundcenter's moves, sending back to Kundcenter, taking an ärende into your
own group, archived and closed ärenden, the superuser, resending the same
group), the Återsänd handback, several ärenden at once, and the passing
group's monitoring on its card. The field's label: test_migration_19_0_1_0_14.
"""
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...models.services.ordering_department_service import OrderingDepartmentService
from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)


@tagged("onecore")
class TestPassOnOrderer(TransactionCase):
    def setUp(self):
        super().setUp()
        # Fixed names: the log line escapes them, and a generated name with
        # an apostrophe would not be found in the body as written.
        self.mover = create_internal_user(
            self.env, name="Daniel Testsson", ad_office_location="Fastighetsserviceenheten"
        )
        self.appliances = create_maintenance_team(
            self.env, name="Appliance team (test)", member_ids=[(4, self.mover.id)]
        )
        self.contractor = create_external_contractor_user(self.env)
        self.contractor_team = create_maintenance_team(
            self.env, name="Electrician Ltd (test)", member_ids=[(4, self.contractor.id)]
        )
        self.kc_user = create_internal_user(
            self.env, ad_office_location="Kundcenterenheten"
        )
        self.kundcenter = self.env.ref("onecore_maintenance_extension.7")
        self.kundcenter.member_ids = [(4, self.kc_user.id)]
        self.integration_user = create_internal_user(self.env, name="Integration Testsson")
        self.request = self._mina_sidor_request(self.appliances)

    def _mina_sidor_request(self, team):
        return create_maintenance_request(
            self.env(user=self.integration_user),
            creation_origin="mimer-nu",
            maintenance_team_id=team.id,
        )

    def _orderer_notes(self, request):
        return request.message_ids.filtered(
            lambda message: "Beställare:" in (message.body or "")
        )

    def _move(self, requests, user, team):
        requests.with_user(user).write({"maintenance_team_id": team.id})

    def _assert_orderer_unchanged(self, request):
        self.assertEqual(request.owner_user_id, self.integration_user)
        self.assertEqual(request.ordering_department, "Mina sidor")
        self.assertFalse(self._orderer_notes(request))

    def test_moving_to_another_group_makes_the_mover_the_orderer(self):
        self._move(self.request, self.mover, self.contractor_team)

        self.assertEqual(self.request.owner_user_id, self.mover)
        self.assertEqual(self.request.ordering_department, "Fastighetsserviceenheten")
        note = self._orderer_notes(self.request)
        self.assertEqual(len(note), 1)
        self.assertIn("Integration Testsson (Mina sidor)", note.body)
        self.assertIn("Daniel Testsson (Fastighetsserviceenheten)", note.body)

    def test_passing_on_clears_the_backfill_stamp(self):
        """The department is now a live stamp, not a guess from the backfill."""
        self.request.sudo().write({"ordering_backfilled_at": fields.Datetime.now()})

        self._move(self.request, self.mover, self.contractor_team)

        self.assertFalse(self.request.ordering_backfilled_at)

    def test_kundcenter_does_not_become_the_orderer(self):
        request = self._mina_sidor_request(self.kundcenter)

        self._move(request, self.kc_user, self.appliances)

        self.assertEqual(request.maintenance_team_id, self.appliances)
        self._assert_orderer_unchanged(request)

    def test_sending_a_request_back_to_kundcenter_changes_nothing(self):
        self._move(self.request, self.mover, self.kundcenter)

        self.assertEqual(self.request.maintenance_team_id, self.kundcenter)
        self._assert_orderer_unchanged(self.request)

    def test_taking_a_request_into_your_own_group_changes_nothing(self):
        request = self._mina_sidor_request(self.kundcenter)

        self._move(request, self.mover, self.appliances)

        self.assertEqual(request.maintenance_team_id, self.appliances)
        self._assert_orderer_unchanged(request)

    def test_archived_and_closed_requests_keep_their_orderer(self):
        archived = self._mina_sidor_request(self.appliances)
        archived.sudo().write({"archive": True})
        closed = self._mina_sidor_request(self.appliances)
        closed.sudo().write({"stage_id": self.env.ref("maintenance.stage_6").id})

        self._move(archived | closed, self.mover, self.contractor_team)

        for request in archived | closed:
            with self.subTest(request=request.id):
                self.assertEqual(request.maintenance_team_id, self.contractor_team)
                self._assert_orderer_unchanged(request)

    def test_a_mover_without_a_department_leaves_it_to_the_backfill(self):
        """Their unit arrives at their next SSO login. Until then the
        department is empty and unstamped, and the backfill fills in theirs,
        not the Mina sidor value of a request still ordered by the tenant."""
        colleague = create_internal_user(self.env)
        self.appliances.member_ids = [(4, colleague.id)]

        self._move(self.request, colleague, self.contractor_team)

        self.assertEqual(self.request.owner_user_id, colleague)
        self.assertFalse(self.request.ordering_department)
        self.assertFalse(self.request.ordering_backfilled_at)

        colleague.ad_office_location = "Driftenheten"
        self.env["maintenance.request"]._cron_backfill_ordering_department()

        self.assertEqual(self.request.ordering_department, "Driftenheten")

    def test_someone_in_no_resource_group_does_not_pass_on(self):
        """Återsänd hands back to the orderer's first resource group; theirs
        would go to Kundcenter instead of where the ärende came from."""
        manager = create_internal_user(self.env, ad_office_location="Distriktsledning")

        self._move(self.request, manager, self.contractor_team)

        self.assertEqual(self.request.maintenance_team_id, self.contractor_team)
        self._assert_orderer_unchanged(self.request)

    def test_resending_the_same_group_changes_nothing(self):
        """A form save or list multi-edit sends the group again unchanged.
        The writer is not a member of that group, so only the comparison
        with the group before the write keeps this from being a move."""
        request = self._mina_sidor_request(self.contractor_team)

        request.with_user(self.mover).write(
            {"maintenance_team_id": self.contractor_team.id, "priority_expanded": "1"}
        )

        self._assert_orderer_unchanged(request)

    def test_a_return_goes_back_to_the_group_that_passed_it_on(self):
        self._move(self.request, self.mover, self.contractor_team)
        self.request.sudo().write(
            {"stage_id": self.env.ref("maintenance.stage_3").id, "user_id": self.contractor.id}
        )

        self.request.with_user(self.contractor).write(
            {"stage_id": self.env.ref("onecore_maintenance_extension.stage_atersand").id}
        )

        self.assertEqual(self.request.maintenance_team_id, self.appliances)
        self.assertEqual(self.request.owner_user_id, self.mover)
        self.assertEqual(len(self._orderer_notes(self.request)), 1)

    def test_superuser_moves_change_nothing(self):
        """Crons run as the superuser, and the Återsänd handback writes the
        team under sudo()."""
        self.request.with_user(self.mover).sudo().write(
            {"maintenance_team_id": self.contractor_team.id}
        )

        self._assert_orderer_unchanged(self.request)

    def test_who_passes_on(self):
        def passes_on(env):
            return OrderingDepartmentService(env).passes_on()

        self.assertTrue(passes_on(self.env(user=self.mover)))
        self.assertFalse(passes_on(self.env(user=self.kc_user)))
        self.assertFalse(passes_on(self.env(user=self.contractor)))
        self.assertFalse(passes_on(self.env(user=self.mover, su=True)))
        self.assertFalse(passes_on(self.env(user=create_internal_user(self.env))))

    def test_moving_several_requests_at_once(self):
        requests = self.request | self._mina_sidor_request(self.appliances)

        self._move(requests, self.mover, self.contractor_team)

        self.assertEqual(requests.mapped("owner_user_id"), self.mover)
        self.assertEqual(
            set(requests.mapped("ordering_department")), {"Fastighetsserviceenheten"}
        )

    def test_the_passing_group_monitors_the_request(self):
        self.assertEqual(self.appliances.ordered_active_count, 0)

        self._move(self.request, self.mover, self.contractor_team)

        self.appliances.invalidate_recordset(["ordered_active_count"])
        self.assertEqual(self.appliances.ordered_active_count, 1)
