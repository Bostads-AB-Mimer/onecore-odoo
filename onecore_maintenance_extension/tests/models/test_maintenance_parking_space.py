from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceParkingSpace(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_parking_space_cascade_delete_when_maintenance_request_deleted(self):
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
        self.env["maintenance.parking.space"].create(
            {
                "name": self.fake.parking_space_name(),
                "code": self.fake.parking_space_code(),
                "type_name": "Standard",
                "type_code": "STD",
                "number": str(self.fake.random_int(1, 999)),
                "property_code": self.fake.property_code(),
                "property_name": self.fake.building_name(),
                "address": self.fake.address(),
                "postal_code": self.fake.postcode(),
                "city": self.fake.city(),
                "maintenance_request_id": request.id,
            }
        )
        request.unlink()
        self.assertFalse(
            self.env["maintenance.parking.space"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
