from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import setup_faker


@tagged("onecore")
class TestMaintenanceRequestCategory(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_maintenance_request_category_default_values(self):
        """Test category default values."""
        category = self.env["maintenance.request.category"].create(
            {"name": self.fake.category_name()}
        )
        self.assertTrue(category.active)
        self.assertEqual(category.color, 0)
