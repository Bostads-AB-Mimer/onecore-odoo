from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..test_utils import create_maintenance_request, create_facility


@tagged("onecore")
class TestMaintenanceFacility(TransactionCase):
    def test_facility_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_facility(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.facility"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )