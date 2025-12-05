from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..test_utils import setup_faker, create_maintenance_request


@tagged("onecore")
class TestMaintenanceTeam(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.team = self.env["maintenance.team"].create({"name": self.fake.team_name()})
        self.first_stage = self.env["maintenance.stage"].search(
            [], order="sequence", limit=1
        )
        self.second_stage = self.env["maintenance.stage"].search(
            [], order="sequence", limit=1, offset=1
        )

    def test_first_column_request_count_no_requests(self):
        """Should be zero if no requests in first column."""
        self.team._compute_first_column_request_count()
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
        self.team._compute_first_column_request_count()
        self.assertEqual(self.team.first_column_request_count, 2)
