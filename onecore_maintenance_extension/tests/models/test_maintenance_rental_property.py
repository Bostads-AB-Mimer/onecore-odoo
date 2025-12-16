from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..test_utils import setup_faker, create_maintenance_request, create_rental_property


@tagged("onecore")
class TestMaintenanceRentalPropertyModels(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

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
        request = create_maintenance_request(self.env)
        create_rental_property(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.rental.property"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
