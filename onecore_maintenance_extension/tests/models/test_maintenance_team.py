from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
    setup_faker,
)


@tagged("onecore")
class TestMaintenanceTeam(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.team = self.env["maintenance.team"].create({"name": self.fake.team_name()})
        self.first_stage = self.env.ref("maintenance.stage_0")
        self.second_stage = self.env.ref("maintenance.stage_1")

    def test_first_column_request_count_no_requests(self):
        """Should be zero if no requests in first column."""
        self.team._compute_queue_request_counts()
        self.assertEqual(self.team.first_column_request_count, 0)

    def test_first_column_request_count_with_requests(self):
        """Should count only requests in first column for this team."""
        # Create requests in both stages
        create_maintenance_request(
            self.env,
            maintenance_team_id=self.team.id,
            stage_id=self.first_stage.id,
        )
        create_maintenance_request(
            self.env,
            maintenance_team_id=self.team.id,
            stage_id=self.second_stage.id,
        )
        create_maintenance_request(
            self.env,
            maintenance_team_id=self.team.id,
            stage_id=self.first_stage.id,
        )
        self.team._compute_queue_request_counts()
        self.assertEqual(self.team.first_column_request_count, 2)


QUEUE_FIELDS = {
    "waiting": "first_column_request_count",
    "active": "active_request_count",
    "performed": "performed_request_count",
    "returned": "returned_request_count",
    "new_info": "new_info_request_count",
}
ORDERED_FIELDS = {
    "active": "ordered_active_count",
    "performed": "ordered_performed_count",
    "new_info": "ordered_new_info_count",
}


@tagged("onecore")
class TestMaintenanceTeamCard(TransactionCase):
    """The numbers on the resource group card and the lists they open.

    Two teams whose people belong to two departments, and requests ordered
    by each department sitting with each team, across the stages.
    """

    def setUp(self):
        super().setUp()
        # Department names no other data in the database carries, so the
        # Bevakning numbers see only this test's requests.
        self.vast_user = create_internal_user(
            self.env, ad_office_location="Testavdelning Väst"
        )
        self.ost_user = create_internal_user(
            self.env, ad_office_location="Testavdelning Öst"
        )
        self.vast = create_maintenance_team(
            self.env, name="Väst (test)", member_ids=[(4, self.vast_user.id)]
        )
        self.ost = create_maintenance_team(
            self.env, name="Öst (test)", member_ids=[(4, self.ost_user.id)]
        )
        # A contractor's queue: no members with a department, orders nothing.
        self.contractor = create_maintenance_team(self.env, name="Entreprenör (test)")
        self.viewer = create_internal_user(self.env)

        self.vast_waiting_at_vast = self._request(self.vast_user, self.vast, "stage_0")
        self.vast_active_at_ost = self._request(self.vast_user, self.ost, "stage_1")
        self.vast_waiting_at_ost = self._request(self.vast_user, self.ost, "stage_0")
        self.vast_performed_at_ost = self._request(self.vast_user, self.ost, "stage_5")
        self.vast_closed_at_ost = self._request(self.vast_user, self.ost, "stage_6")
        self.ost_message_at_vast = self._request(self.ost_user, self.vast, "stage_4")
        # Returned by Väst: Återsänd hands it back to the orderer's team.
        self.ost_returned = self._request(
            self.ost_user, self.vast, "onecore_maintenance_extension.stage_atersand"
        )
        self.vast_new_tenant_at_vast = self._request(self.vast_user, self.vast, "stage_3")
        self.vast_archived_at_ost = self._request(self.vast_user, self.ost, "stage_3")
        self.vast_new_info_at_contractor = self._request(
            self.vast_user, self.contractor, "stage_1"
        )

        Request = self.env["maintenance.request"]
        Request.browse(self.ost_message_at_vast.id).last_customer_message_at = (
            "2026-09-30 08:00:00"
        )
        Request.browse(self.vast_new_tenant_at_vast.id).recently_added_tenant = True
        Request.browse(self.vast_new_info_at_contractor.id).recently_added_tenant = True
        Request.browse(self.vast_archived_at_ost.id).archive = True
        self.env.invalidate_all()

    def _request(self, orderer, team, stage_xml_id):
        """A request ordered by ``orderer`` (who stamps its department),
        sitting with ``team`` in the given stage."""
        if "." not in stage_xml_id:
            stage_xml_id = f"maintenance.{stage_xml_id}"
        request = create_maintenance_request(
            self.env(user=orderer), maintenance_team_id=team.id
        )
        if stage_xml_id != "maintenance.stage_0":
            # Past Väntar a request needs an assigned resource, and the
            # assignment itself moves it to Resurs tilldelad. Re-browsed: the
            # recordset from create() carries creating_records.
            request = self.env["maintenance.request"].browse(request.id)
            request.with_user(self.viewer).write({"user_id": self.viewer.id})
            request.with_user(self.viewer).write(
                {"stage_id": self.env.ref(stage_xml_id).id}
            )
        return request

    def _counts(self, team, fields):
        team = team.with_user(self.viewer)
        return {bucket: team[field] for bucket, field in fields.items()}

    def _opened(self, team, method, bucket):
        action = getattr(
            team.with_user(self.viewer).with_context(request_bucket=bucket), method
        )()
        return self.env["maintenance.request"].with_user(self.viewer).search(
            action["domain"]
        )

    def test_queue_counts(self):
        self.assertEqual(
            self._counts(self.vast, QUEUE_FIELDS),
            {"waiting": 1, "active": 2, "performed": 0, "returned": 0, "new_info": 2},
        )
        self.assertEqual(
            self._counts(self.ost, QUEUE_FIELDS),
            {"waiting": 1, "active": 1, "performed": 1, "returned": 1, "new_info": 0},
        )

    def test_ordered_counts_leave_out_what_sits_with_the_team(self):
        """Bevakning is what the team's people ordered from someone else;
        what sits with the team is already in its own queue."""
        self.assertEqual(
            self._counts(self.vast, ORDERED_FIELDS),
            {"active": 3, "performed": 1, "new_info": 1},
        )
        self.assertEqual(
            self._counts(self.ost, ORDERED_FIELDS),
            {"active": 1, "performed": 0, "new_info": 1},
        )

    def test_returned_request_is_in_the_orderers_queue_not_in_bevakning(self):
        """A returned order is back with the team that ordered it: theirs to
        handle again, and no longer an order out with someone else."""
        self.assertEqual(self.ost_returned.maintenance_team_id, self.ost)
        self.assertEqual(
            self._opened(self.ost, "action_open_queue_requests", "returned"),
            self.ost_returned,
        )
        self.assertNotIn(
            self.ost_returned,
            self._opened(self.ost, "action_open_ordered_requests", "active"),
        )

    def test_team_without_departments_counts_no_orders(self):
        self.assertEqual(
            self._counts(self.contractor, ORDERED_FIELDS),
            {"active": 0, "performed": 0, "new_info": 0},
        )
        self.assertEqual(self._counts(self.contractor, QUEUE_FIELDS)["new_info"], 1)

    def test_every_number_opens_the_requests_it_counts(self):
        for team in self.vast | self.ost | self.contractor:
            for method, fields in (
                ("action_open_queue_requests", QUEUE_FIELDS),
                ("action_open_ordered_requests", ORDERED_FIELDS),
            ):
                for bucket, field in fields.items():
                    with self.subTest(team=team.name, method=method, bucket=bucket):
                        self.assertEqual(
                            len(self._opened(team, method, bucket)),
                            team.with_user(self.viewer)[field],
                        )

    def test_opened_lists_hold_the_expected_requests(self):
        self.assertEqual(
            self._opened(self.vast, "action_open_queue_requests", "new_info"),
            self.ost_message_at_vast | self.vast_new_tenant_at_vast,
        )
        self.assertEqual(
            self._opened(self.vast, "action_open_ordered_requests", "active"),
            self.vast_active_at_ost
            | self.vast_waiting_at_ost
            | self.vast_new_info_at_contractor,
        )

    def test_queue_action_creates_requests_for_the_team(self):
        action = self.vast.with_context(
            request_bucket="waiting"
        ).action_open_queue_requests()
        self.assertEqual(
            action["context"], {"default_maintenance_team_id": self.vast.id}
        )

    def test_opened_list_is_titled_after_the_number(self):
        """The breadcrumb reads display_name first, so both must be set."""
        action = self.vast.with_context(
            request_bucket="active"
        ).action_open_ordered_requests()
        self.assertEqual(action["display_name"], "Väst (test): Beställda, aktiva")
        self.assertEqual(action["name"], action["display_name"])

    def test_unknown_bucket_is_refused(self):
        with self.assertRaises(ValueError):
            self.vast.with_context(request_bucket="returned").action_open_ordered_requests()

    def test_query_count_does_not_grow_with_the_number_of_teams(self):
        def queries(teams):
            teams = teams.with_user(self.viewer)
            self.env.invalidate_all()
            start = self.cr.sql_log_count
            for team in teams:
                for field in (*QUEUE_FIELDS.values(), *ORDERED_FIELDS.values()):
                    team[field]
            return self.cr.sql_log_count - start

        more = self.contractor
        for number in range(4):
            user = create_internal_user(
                self.env, ad_office_location=f"Testavdelning {number}"
            )
            more |= create_maintenance_team(self.env, member_ids=[(4, user.id)])
        few = self.vast | self.ost | self.contractor
        queries(few)  # warm the ormcaches (xml-ids, stages)
        self.assertEqual(queries(few), queries(few | more))
