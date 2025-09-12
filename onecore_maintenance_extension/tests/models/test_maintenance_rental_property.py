from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceRentalPropertyModels(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_rental_property_option_user_id_defaults_to_current_user(self):
        """user_id should default to current user."""
        property_option = self.env["maintenance.rental.property.option"].create(
            {
                "name": self.fake.rental_property_name(),
                "property_type": self.fake.building_type(),
            }
        )
        self.assertEqual(property_option.user_id, self.env.user)

    def test_rental_property_cascade_delete_when_maintenance_request_deleted(self):
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
        self.env["maintenance.rental.property"].create(
            {
                "name": self.fake.rental_property_name(),
                "property_type": self.fake.building_type(),
                "maintenance_request_id": request.id,
            }
        )
        request.unlink()
        self.assertFalse(
            self.env["maintenance.rental.property"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
