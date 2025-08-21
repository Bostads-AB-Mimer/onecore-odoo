from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceMaintenanceUnitModels(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_maintenance_unit_cascade_delete_when_maintenance_request_deleted(self):
        """maintenance_request_id links and cascades correctly."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        unit = self.env["maintenance.maintenance.unit"].create(
            {
                "name": self.fake.maintenance_unit_full_name(),
                "type": self.fake.maintenance_unit_type(),
                "code": self.fake.maintenance_unit_code(),
                "caption": self.fake.maintenance_unit_caption(),
                "maintenance_request_id": request.id,
            }
        )
        self.assertEqual(unit.maintenance_request_id, request)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.maintenance.unit"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
