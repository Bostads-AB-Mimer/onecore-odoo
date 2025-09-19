from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceFacility(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_facility_cascade_delete_when_maintenance_request_deleted(self):
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
        self.env["maintenance.facility"].create(
            {
                "name": self.fake.facility_name(),
                "code": self.fake.facility_code(),
                "type_name": self.fake.facility_type_name(),
                "type_code": self.fake.facility_type_code(),
                "rental_type": self.fake.facility_rental_type(),
                "area": self.fake.facility_area(),
                "building_code": self.fake.building_code(),
                "building_name": self.fake.building_name(),
                "property_code": self.fake.property_code(),
                "property_name": self.fake.building_name(),
                "maintenance_request_id": request.id,
            }
        )
        request.unlink()
        self.assertFalse(
            self.env["maintenance.facility"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )