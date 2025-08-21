from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceBasicUserSecurity(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

        self.basic_user = self.env["res.users"].create(
            {
                "name": "Basic User",
                "login": "basic@test.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )


    def test_basic_user_has_full_crud_access_to_all_maintenance_models(self):
        """Basic users should have full CRUD access to all maintenance models."""
        # Test maintenance request (main model)
        request = self.env["maintenance.request"].with_user(self.basic_user).create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        
        # Test maintenance request category
        category = self.env["maintenance.request.category"].with_user(self.basic_user).create(
            {"name": self.fake.category_name()}
        )

        # Test all models (option + cascade + category)
        all_models_data = [
            # Option models
            ("maintenance.rental.property.option", {"name": f"Test Option"}),
            ("maintenance.property.option", {"name": f"Test Option"}),
            ("maintenance.building.option", {"name": f"Test Option"}),
            ("maintenance.maintenance.unit.option", {"name": f"Test Option"}),
            ("maintenance.tenant.option", {"name": f"Test Option"}),
            ("maintenance.lease.option", {"name": f"Test Option"}),
            
            # Cascade models
            (
                "maintenance.rental.property",
                {
                    "name": self.fake.rental_property_name(),
                    "property_type": self.fake.building_type(),
                    "maintenance_request_id": request.id,
                },
            ),
            (
                "maintenance.property", 
                {
                    "name": self.fake.property_designation(),
                    "maintenance_request_id": request.id,
                }
            ),
            (
                "maintenance.building",
                {
                    "name": self.fake.building_name(),
                    "building_type": self.fake.building_type(),
                    "maintenance_request_id": request.id,
                },
            ),
            (
                "maintenance.maintenance.unit",
                {
                    "name": self.fake.maintenance_unit_name(),
                    "maintenance_request_id": request.id,
                }
            ),
            (
                "maintenance.tenant",
                {
                    "name": self.fake.tenant_full_name(),
                    "contact_code": self.fake.tenant_contact_code(),
                    "contact_key": self.fake.tenant_contact_key(),
                    "maintenance_request_id": request.id,
                },
            ),
            (
                "maintenance.lease", 
                {
                    "name": self.fake.lease_model_name(),
                    "maintenance_request_id": request.id,
                }
            ),
        ]

        for model_name, data in all_models_data:
            with self.subTest(model=model_name):
                # Create
                record = self.env[model_name].with_user(self.basic_user).create(data)

                # Read
                self.assertTrue(record.name)

                # Write
                record.write({"name": f"Updated {record.name}"})
                self.assertTrue(record.name.startswith("Updated"))

                # Delete
                record.unlink()
                self.assertFalse(record.exists())

        # Clean up main records
        request.unlink()
        category.unlink()
        self.assertFalse(request.exists())
        self.assertFalse(category.exists())
