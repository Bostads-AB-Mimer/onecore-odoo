from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceEquipmentManagerSecurity(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)
        
        self.equipment_manager_group = self.env.ref(
            "maintenance.group_equipment_manager"
        )
        
        self.equipment_manager_user = self.env["res.users"].create(
            {
                "name": "Equipment Manager",
                "login": "equipment.manager@test.com",
                "groups_id": [(6, 0, [self.equipment_manager_group.id])],
            }
        )
        
        self.basic_user = self.env["res.users"].create(
            {
                "name": "Basic User",
                "login": "basic@test.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    def test_equipment_manager_group_membership(self):
        """Test that equipment manager user correctly belongs to equipment manager group."""
        # Equipment manager should be in the equipment manager group
        self.assertTrue(
            self.equipment_manager_user.has_group(
                "maintenance.group_equipment_manager"
            )
        )
        
        # Basic user should not be in the equipment manager group
        self.assertFalse(
            self.basic_user.has_group(
                "maintenance.group_equipment_manager"
            )
        )

    def test_equipment_manager_full_access_maintenance_request(self):
        """Equipment managers should have full CRUD access to maintenance requests."""
        # Create
        request = self.env["maintenance.request"].with_user(self.equipment_manager_user).create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        
        # Read
        self.assertTrue(request.name)
        
        # Write
        new_name = self.fake.maintenance_request_name()
        request.write({"name": new_name})
        self.assertEqual(request.name, new_name)
        
        # Delete
        request.unlink()
        self.assertFalse(request.exists())

    def test_equipment_manager_can_access_config_parameters(self):
        """Equipment managers should have read access to system config parameters."""
        # This tests the access_ir_config_parameter_system_equipment_manager rule
        config_param = self.env["ir.config_parameter"].sudo().create({
            "key": "test.parameter",
            "value": "test_value"
        })
        
        # Equipment manager should be able to read config parameters
        param_as_manager = config_param.with_user(self.equipment_manager_user)
        self.assertEqual(param_as_manager.value, "test_value")
        
        # Equipment manager should NOT be able to write/create/delete config parameters
        # (according to CSV: perm_read=1, perm_write=0, perm_create=0, perm_unlink=0)
        with self.assertRaises(Exception):
            param_as_manager.write({"value": "should_not_work"})

    def test_equipment_manager_can_access_all_models(self):
        """Equipment managers should have full access to all maintenance models."""
        # Create a maintenance request first for cascade models
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        
        # Test option models
        option_models = [
            "maintenance.rental.property.option",
            "maintenance.property.option", 
            "maintenance.building.option",
            "maintenance.maintenance.unit.option",
            "maintenance.tenant.option",
            "maintenance.lease.option",
        ]
        
        for model_name in option_models:
            with self.subTest(model=model_name):
                # Create
                record = self.env[model_name].with_user(self.equipment_manager_user).create(
                    {"name": f"Test {model_name}"}
                )
                
                # Read
                self.assertTrue(record.name)
                
                # Write
                record.write({"name": f"Updated {model_name}"})
                self.assertEqual(record.name, f"Updated {model_name}")
                
                # Delete
                record.unlink()
                self.assertFalse(record.exists())

        # Test main models with cascade relationships
        models_data = [
            ("maintenance.rental.property", {"name": self.fake.rental_property_name(), "property_type": self.fake.building_type()}),
            ("maintenance.property", {"name": self.fake.property_designation()}),
            ("maintenance.building", {"name": self.fake.building_name(), "building_type": self.fake.building_type()}),
            ("maintenance.maintenance.unit", {"name": self.fake.maintenance_unit_name()}),
            ("maintenance.tenant", {"name": self.fake.tenant_full_name(), "contact_code": self.fake.tenant_contact_code(), "contact_key": self.fake.tenant_contact_key()}),
            ("maintenance.lease", {"name": self.fake.lease_model_name()}),
        ]
        
        for model_name, data in models_data:
            with self.subTest(model=model_name):
                data["maintenance_request_id"] = request.id
                
                # Create
                record = self.env[model_name].with_user(self.equipment_manager_user).create(data)
                
                # Read
                self.assertTrue(record.name)
                
                # Write
                record.write({"name": f"Updated {record.name}"})
                self.assertTrue(record.name.startswith("Updated"))
                
                # Delete
                record.unlink()
                self.assertFalse(record.exists())

        # Test maintenance request category
        category = self.env["maintenance.request.category"].with_user(self.equipment_manager_user).create(
            {"name": self.fake.category_name()}
        )
        
        # Read
        self.assertTrue(category.name)
        
        # Write
        new_name = self.fake.category_name()
        category.write({"name": new_name})
        self.assertEqual(category.name, new_name)
        
        # Delete
        category.unlink()
        self.assertFalse(category.exists())

    def test_equipment_manager_ui_access(self):
        """Test that equipment managers have access to UI elements restricted from external users."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )
        
        # Equipment manager should NOT be external contractor
        request_as_manager = request.with_user(self.equipment_manager_user)
        self.assertFalse(request_as_manager.user_is_external_contractor)
        self.assertFalse(request_as_manager.restricted_external)
        
        # This means they should have access to all UI elements
        # (no readonly="user_is_external_contractor" restrictions)
        # and can see elements like the "Öppna tidrapport" button