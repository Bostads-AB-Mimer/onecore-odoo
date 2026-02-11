from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import create_maintenance_request, create_maintenance_unit


@tagged("onecore")
class TestMaintenanceMaintenanceUnitModels(TransactionCase):
    def test_maintenance_unit_cascade_delete_when_maintenance_request_deleted(self):
        """maintenance_request_id links and cascades correctly."""
        request = create_maintenance_request(self.env)
        unit = create_maintenance_unit(self.env, maintenance_request_id=request.id)
        self.assertEqual(unit.maintenance_request_id, request)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.maintenance.unit"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
