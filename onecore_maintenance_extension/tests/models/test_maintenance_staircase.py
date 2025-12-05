from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..test_utils import create_maintenance_request, create_staircase


@tagged("onecore")
class TestMaintenanceStaircase(TransactionCase):
    def test_staircase_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_staircase(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.staircase"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
