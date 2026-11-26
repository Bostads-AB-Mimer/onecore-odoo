"""An ärende without a real orderer gets one when it is passed on.

Covers OrderingDepartmentService.pass_on and where write() calls it. Whoever
passes a Mina sidor ärende, an ärende Kundcenter mediated, or one whose orderer
nobody can follow up on to another resource group becomes its orderer. A real
orderer, who created the ärende, is kept, also while their department waits
for the backfill: their follow-up views and Återsänd keep working. Someone
who took an ärende over is replaced by the next group that passes it on.
Also covered: the new orderer and department, the log line, the backfill
stamp, what is not passing on (Kundcenter's moves, sending back to
Kundcenter, taking an ärende into your own group, archived and closed
ärenden, the superuser, resending the same group), the Återsänd handback (to
Kundcenter for a kept orderer in no group), several ärenden at once, the
passing group's monitoring on its card, and who orders a duplicate. The field's label:
test_migration_19_0_1_0_14.
"""
from odoo import fields
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval
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
        # A real orderer in a group of their own, who orders from appliances.
        self.orderer = create_internal_user(
            self.env, name="Markus Testsson", ad_office_location="Förvaltningsadministrationen"
        )
        self.orderer_team = create_maintenance_team(
            self.env,
            name="Property administration (test)",
            member_ids=[(4, self.orderer.id)],
        )

    def _mina_sidor_request(self, team):
        return create_maintenance_request(
            self.env(user=self.integration_user),
            creation_origin="mimer-nu",
            maintenance_team_id=team.id,
        )

    def _internal_request(self, user, team, **kwargs):
        return create_maintenance_request(
            self.env(user=user), maintenance_team_id=team.id, **kwargs
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

    # ------------------------------------------------------------------
    # A real orderer is kept
    # ------------------------------------------------------------------
    def _assert_taken_over(self, request):
        self.assertEqual(request.owner_user_id, self.mover)
        self.assertEqual(request.ordering_department, "Fastighetsserviceenheten")
        self.assertEqual(len(self._orderer_notes(request)), 1)

    def _assert_kept_by_orderer(self, request):
        self.assertEqual(request.owner_user_id, self.orderer)
        self.assertEqual(request.ordering_department, "Förvaltningsadministrationen")
        self.assertFalse(self._orderer_notes(request))

    def test_a_real_orderer_is_kept_when_another_group_passes_it_on(self):
        request = self._internal_request(self.orderer, self.appliances)

        self._move(request, self.mover, self.contractor_team)

        self.assertEqual(request.maintenance_team_id, self.contractor_team)
        self._assert_kept_by_orderer(request)
        self.assertFalse(request.ordering_backfilled_at)

    def test_a_kept_orderer_still_follows_the_request(self):
        request = self._internal_request(self.orderer, self.appliances)
        self._move(request, self.mover, self.contractor_team)
        request.sudo().write({"user_id": self.contractor.id})
        request.sudo().write({"stage_id": self.env.ref("maintenance.stage_5").id})
        self.assertEqual(request.stage_id, self.env.ref("maintenance.stage_5"))

        Request = self.env["maintenance.request"].with_user(self.orderer)
        for xml_id in (
            "onecore_maintenance_extension.filter_my_orders",
            "onecore_maintenance_extension.filter_ordered_by_my_department_at_others",
        ):
            with self.subTest(favorite=xml_id):
                domain = safe_eval(
                    self.env.ref(xml_id).domain, {"uid": self.orderer.id}
                )
                self.assertIn(request, Request.search(domain))

        (self.orderer_team | self.appliances).invalidate_recordset(
            ["ordered_performed_count"]
        )
        self.assertEqual(self.orderer_team.ordered_performed_count, 1)
        self.assertEqual(self.appliances.ordered_performed_count, 0)

    def test_a_return_goes_back_to_the_real_orderers_group(self):
        request = self._internal_request(self.orderer, self.appliances)
        self._move(request, self.mover, self.contractor_team)
        request.sudo().write(
            {"stage_id": self.env.ref("maintenance.stage_3").id, "user_id": self.contractor.id}
        )

        request.with_user(self.contractor).write(
            {"stage_id": self.env.ref("onecore_maintenance_extension.stage_atersand").id}
        )

        self.assertEqual(request.maintenance_team_id, self.orderer_team)
        self._assert_kept_by_orderer(request)

    def test_a_return_for_a_kept_orderer_in_no_group_goes_to_kundcenter(self):
        """The orderer is kept although they work in no resource group, so
        Återsänd has no group of theirs to hand back to."""
        groupless = create_internal_user(
            self.env, name="Lena Testsson", ad_office_location="Förvaltningsadministrationen"
        )
        request = self._internal_request(groupless, self.appliances)
        self._move(request, self.mover, self.contractor_team)
        self.assertEqual(request.owner_user_id, groupless)
        request.sudo().write(
            {"stage_id": self.env.ref("maintenance.stage_3").id, "user_id": self.contractor.id}
        )

        request.with_user(self.contractor).write(
            {"stage_id": self.env.ref("onecore_maintenance_extension.stage_atersand").id}
        )

        self.assertEqual(request.maintenance_team_id, self.kundcenter)
        self.assertEqual(request.owner_user_id, groupless)
        self.assertFalse(self._orderer_notes(request))

    def test_the_next_group_takes_over_from_one_that_took_over(self):
        """A group that only forwarded a Mina sidor ärende to the right group
        is no real orderer: the group that then orders the work takes over."""
        self._move(self.request, self.mover, self.orderer_team)
        self.assertEqual(self.request.owner_user_id, self.mover)

        self._move(self.request, self.orderer, self.contractor_team)

        self.assertEqual(self.request.maintenance_team_id, self.contractor_team)
        self.assertEqual(self.request.owner_user_id, self.orderer)
        self.assertEqual(self.request.ordering_department, "Förvaltningsadministrationen")
        self.assertEqual(len(self._orderer_notes(self.request)), 2)

    def test_a_real_orderer_is_kept_after_several_moves(self):
        request = self._internal_request(self.orderer, self.appliances)
        plumbers = create_maintenance_team(
            self.env, name="Plumber team (test)", member_ids=[(4, self.mover.id)]
        )

        self._move(request, self.mover, self.contractor_team)
        request.sudo().write({"maintenance_team_id": plumbers.id})
        self._move(request, self.mover, self.contractor_team)

        self._assert_kept_by_orderer(request)

    def test_an_orderer_waiting_for_the_backfill_is_kept(self):
        """Their unit arrives at their next SSO login. Until then the
        department is empty, and it is still their ärende."""
        pending = create_internal_user(
            self.env, name="Pia Testsson", oauth_uid="sub-pending"
        )
        request = self._internal_request(pending, self.appliances)
        self.assertFalse(request.ordering_department)

        self._move(request, self.mover, self.contractor_team)

        self.assertEqual(request.owner_user_id, pending)
        self.assertFalse(request.ordering_department)
        self.assertFalse(request.ordering_backfilled_at)
        self.assertFalse(self._orderer_notes(request))

        pending.ad_office_location = "Driftenheten"
        self.env["maintenance.request"]._cron_backfill_ordering_department()

        self.assertEqual(request.ordering_department, "Driftenheten")

    def test_an_unstamped_request_whose_orderer_has_a_unit_is_kept(self):
        request = self._internal_request(self.orderer, self.appliances)
        request.sudo().write({"ordering_department": False})

        self._move(request, self.mover, self.contractor_team)

        self.assertEqual(request.owner_user_id, self.orderer)
        self.assertFalse(request.ordering_department)
        self.assertFalse(self._orderer_notes(request))

    def test_kundcenter_ordering_in_a_key_category_is_kept(self):
        keys = self.env["maintenance.request.category"].create(
            {"name": "Key order (test)", "kundcenter_orders": True}
        )
        request = self._internal_request(
            self.kc_user, self.appliances, maintenance_request_category_id=keys.id
        )
        self.assertEqual(request.ordering_department, "Kundcenterenheten")

        self._move(request, self.mover, self.contractor_team)

        self.assertEqual(request.owner_user_id, self.kc_user)
        self.assertEqual(request.ordering_department, "Kundcenterenheten")
        self.assertFalse(self._orderer_notes(request))

    # ------------------------------------------------------------------
    # No real orderer: the mover takes over
    # ------------------------------------------------------------------
    def test_a_mediated_request_is_taken_over(self):
        request = self._internal_request(self.kc_user, self.appliances)
        self.assertEqual(request.ordering_department, "Förmedlat av Kundcenter")

        self._move(request, self.mover, self.contractor_team)

        self._assert_taken_over(request)
        self.assertIn("Förmedlat av Kundcenter", self._orderer_notes(request).body)

    def test_a_mina_sidor_request_with_an_old_stamp_is_taken_over(self):
        """Other environments still carry the stamp from before Mina sidor
        got its own value, and old rows carry none."""
        for stamp in ("Kundcenter", False):
            with self.subTest(stamp=stamp):
                request = self._mina_sidor_request(self.appliances)
                request.sudo().write({"ordering_department": stamp})

                self._move(request, self.mover, self.contractor_team)

                self._assert_taken_over(request)

    def test_a_request_without_an_orderer_is_taken_over(self):
        request = self._internal_request(self.orderer, self.appliances)
        request.sudo().write({"owner_user_id": False})

        self._move(request, self.mover, self.contractor_team)

        self._assert_taken_over(request)

    def test_an_orderer_who_can_never_get_a_department_is_replaced(self):
        """Inspection ärenden are created by the integration account, which
        has no unit and no Keycloak link. Nobody can follow those up, and
        Återsänd would send them to Kundcenter."""
        archived = create_internal_user(self.env, oauth_uid="sub-left")
        cases = {
            "no Keycloak link": (self.integration_user, lambda: None),
            "archived": (archived, archived.action_archive),
        }
        for case, (owner, after_create) in cases.items():
            with self.subTest(case=case):
                request = self._internal_request(owner, self.appliances)
                after_create()
                self.assertEqual(request.creation_origin, "internal")
                self.assertFalse(request.ordering_department)

                self._move(request, self.mover, self.contractor_team)

                self._assert_taken_over(request)

    def test_an_orderer_who_has_left_is_replaced(self):
        """Also when their department was stamped: nobody follows it up."""
        request = self._internal_request(self.orderer, self.appliances)
        self.assertEqual(request.ordering_department, "Förvaltningsadministrationen")
        self.orderer.action_archive()

        self._move(request, self.mover, self.contractor_team)

        self._assert_taken_over(request)

    def test_a_request_the_backfill_gave_up_on_is_taken_over(self):
        """The backfill gave up while the owner had no Keycloak link, and never
        comes back to the request, so a unit the owner gets later never
        reaches it."""
        owner = create_internal_user(self.env, name="Olle Testsson")
        request = self._internal_request(owner, self.appliances)
        self.env["maintenance.request"]._cron_backfill_ordering_department()
        self.assertTrue(request.ordering_backfilled_at)
        self.assertFalse(request.ordering_department)
        owner.write({"oauth_uid": "sub-linked-later", "ad_office_location": "Driftenheten"})

        self._move(request, self.mover, self.contractor_team)

        self._assert_taken_over(request)

    def test_a_duplicate_is_ordered_by_whoever_duplicates_it(self):
        request = self._internal_request(self.orderer, self.appliances)
        request.sudo().write({"ordering_backfilled_at": fields.Datetime.now()})

        duplicate = request.with_user(self.mover).copy()

        self.assertEqual(duplicate.owner_user_id, self.mover)
        self.assertEqual(duplicate.create_uid, self.mover)
        self.assertEqual(duplicate.ordering_department, "Fastighetsserviceenheten")
        self.assertFalse(duplicate.ordering_backfilled_at)

    def test_a_duplicated_mina_sidor_request_is_ordered_by_whoever_duplicates_it(self):
        """The duplicate is created here, so it is no tenant's order, and the
        next group to pass it on does not take it from its creator."""
        duplicate = self.request.with_user(self.mover).copy()

        self.assertEqual(duplicate.creation_origin, "internal")
        self.assertEqual(duplicate.owner_user_id, self.mover)
        self.assertEqual(duplicate.ordering_department, "Fastighetsserviceenheten")

        self._move(duplicate, self.mover, self.orderer_team)
        self._move(duplicate, self.orderer, self.contractor_team)

        self.assertEqual(duplicate.owner_user_id, self.mover)
        self.assertFalse(self._orderer_notes(duplicate))

    def test_an_unstamped_request_mediated_by_kundcenter_is_taken_over(self):
        """The backfill would stamp it mediated, not with the member's unit."""
        request = self._internal_request(self.kc_user, self.appliances)
        request.sudo().write({"ordering_department": False})

        self._move(request, self.mover, self.contractor_team)

        self._assert_taken_over(request)

    def test_moving_a_mix_of_requests_at_once(self):
        mina = self._mina_sidor_request(self.appliances)
        real = self._internal_request(self.orderer, self.appliances)
        mediated = self._internal_request(self.kc_user, self.appliances)

        self._move(mina | real | mediated, self.mover, self.contractor_team)

        for request in mina | real | mediated:
            self.assertEqual(request.maintenance_team_id, self.contractor_team)
        for request in mina | mediated:
            with self.subTest(request=request.id):
                self._assert_taken_over(request)
        self._assert_kept_by_orderer(real)

    def test_no_log_line_when_nothing_changes(self):
        with self.subTest(case="the mover is the real orderer"):
            request = self._internal_request(self.mover, self.appliances)

            self._move(request, self.mover, self.contractor_team)

            self.assertEqual(request.owner_user_id, self.mover)
            self.assertEqual(request.ordering_department, "Fastighetsserviceenheten")
            self.assertFalse(self._orderer_notes(request))

        with self.subTest(case="the mover already took it over"):
            colleague = create_internal_user(self.env)
            self.appliances.member_ids = [(4, colleague.id)]
            third_team = create_maintenance_team(self.env, name="Plumber Ltd (test)")
            request = self._mina_sidor_request(self.appliances)
            self._move(request, colleague, self.contractor_team)
            self.assertEqual(len(self._orderer_notes(request)), 1)

            self._move(request, colleague, third_team)

            self.assertEqual(request.maintenance_team_id, third_team)
            self.assertEqual(request.owner_user_id, colleague)
            self.assertFalse(request.ordering_department)
            self.assertEqual(len(self._orderer_notes(request)), 1)
