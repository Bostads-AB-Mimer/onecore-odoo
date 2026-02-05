from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import create_maintenance_request, create_property


@tagged("onecore")
class TestMaintenanceProperty(TransactionCase):
    def test_property_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_property(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.property"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
