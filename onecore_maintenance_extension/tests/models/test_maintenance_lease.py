from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceLease(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_lease_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        self.env["maintenance.lease"].create(
            {
                "name": self.fake.lease_model_name(),
                "lease_number": self.fake.lease_number(),
                "lease_type": self.fake.lease_type(),
                "maintenance_request_id": request.id,
            }
        )
        request.unlink()
        self.assertFalse(
            self.env["maintenance.lease"].search([("maintenance_request_id", "=", request.id)])
        )
