from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import create_maintenance_request, create_building


@tagged("onecore")
class TestMaintenanceBuilding(TransactionCase):
    def test_building_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_building(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.building"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
