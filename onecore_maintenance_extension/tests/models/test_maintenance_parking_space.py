from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..test_utils import create_maintenance_request, create_parking_space


@tagged("onecore")
class TestMaintenanceParkingSpace(TransactionCase):
    def test_parking_space_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_parking_space(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.parking.space"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
