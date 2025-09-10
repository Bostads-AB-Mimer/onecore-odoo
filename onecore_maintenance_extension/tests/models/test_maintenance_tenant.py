from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceTenantModels(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

    def test_tenant_cascade_delete_when_maintenance_request_deleted(self):
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
        self.env["maintenance.tenant"].create(
            {
                "name": self.fake.tenant_full_name(),
                "contact_code": self.fake.tenant_contact_code(),
                "contact_key": self.fake.tenant_contact_key(),
                "maintenance_request_id": request.id,
            }
        )
        request.unlink()
        self.assertFalse(
            self.env["maintenance.tenant"].search(
                [("maintenance_request_id", "=", request.id)]
            )
        )
