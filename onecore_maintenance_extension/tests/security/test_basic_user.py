from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError

from ..utils.test_utils import create_maintenance_request


@tagged("onecore")
class TestMaintenanceBasicUserSecurity(TransactionCase):
    def setUp(self):
        super().setUp()

        self.basic_user_with_maintenance_permissions = self.env["res.users"].create(
            {
                "name": "Basic User With Permissions",
                "login": "basic_with_perms@test.com",
                "email": "basic_with_perms@test.com",
                "groups_id": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("maintenance.group_equipment_manager").id,
                ])],
            }
        )

        self.basic_user_without_maintenance_permissions = self.env["res.users"].create(
            {
                "name": "Basic User Without Permissions",
                "login": "basic_no_perms@test.com",
                "email": "basic_no_perms@test.com",
                "groups_id": [(6, 0, [
                    self.env.ref("base.group_user").id,
                ])],
            }
        )

    def test_basic_user_with_permissions_can_create_maintenance_records(self):
        """Basic users with maintenance permissions should be able to create maintenance records"""
        basic_user_env = self.env(user=self.basic_user_with_maintenance_permissions)

        request = create_maintenance_request(basic_user_env)
        self.assertTrue(request.exists())

    def test_basic_user_without_permissions_cannot_create_maintenance_records(self):
        """Basic users without maintenance permissions should not be able to create maintenance records"""
        unprivileged_env = self.env(user=self.basic_user_without_maintenance_permissions)

        with self.assertRaises(AccessError):
            create_maintenance_request(unprivileged_env)

    def test_basic_user_with_permissions_can_read_maintenance_records(self):
        """Basic users with maintenance permissions should be able to read maintenance records"""
        request = create_maintenance_request(self.env)

        basic_user_env = self.env(user=self.basic_user_with_maintenance_permissions)
        request_as_user = basic_user_env["maintenance.request"].browse(request.id)
        self.assertEqual(request_as_user.id, request.id)

    def test_basic_user_without_permissions_cannot_read_maintenance_records(self):
        """Basic users without maintenance permissions should not be able to read maintenance records"""
        request = create_maintenance_request(self.env)

        unprivileged_env = self.env(user=self.basic_user_without_maintenance_permissions)
        with self.assertRaises(AccessError):
            unprivileged_env["maintenance.request"].browse(request.id).name

    def test_basic_user_with_permissions_can_update_maintenance_records(self):
        """Basic users with maintenance permissions should be able to update maintenance records"""
        request = create_maintenance_request(self.env)

        basic_user_env = self.env(user=self.basic_user_with_maintenance_permissions)
        request_as_user = basic_user_env["maintenance.request"].browse(request.id)
        request_as_user.write({"name": "Updated by basic user with permissions"})
        self.assertEqual(request_as_user.name, "Updated by basic user with permissions")

    def test_basic_user_without_permissions_cannot_update_maintenance_records(self):
        """Basic users without maintenance permissions should not be able to update maintenance records"""
        request = create_maintenance_request(self.env)

        unprivileged_env = self.env(user=self.basic_user_without_maintenance_permissions)
        request_as_unprivileged = unprivileged_env["maintenance.request"].browse(request.id)
        with self.assertRaises(AccessError):
            request_as_unprivileged.write({"name": "Unauthorized update"})

    def test_basic_user_with_permissions_can_delete_maintenance_records(self):
        """Basic users with maintenance permissions should be able to delete maintenance records"""
        request = create_maintenance_request(self.env)

        basic_user_env = self.env(user=self.basic_user_with_maintenance_permissions)
        request_as_user = basic_user_env["maintenance.request"].browse(request.id)
        request_as_user.unlink()
        self.assertFalse(request_as_user.exists())

    def test_basic_user_without_permissions_cannot_delete_maintenance_records(self):
        """Basic users without equipment manager group should not be able to delete maintenance records"""
        request = create_maintenance_request(self.env)

        unprivileged_env = self.env(user=self.basic_user_without_maintenance_permissions)
        request_as_unprivileged = unprivileged_env["maintenance.request"].browse(request.id)
        with self.assertRaises(AccessError):
            request_as_unprivileged.unlink()

    def test_basic_user_ui_visibility_flags(self):
        """Basic users with maintenance permissions should have correct UI visibility flags set"""
        request = create_maintenance_request(self.env)

        basic_user_env = self.env(user=self.basic_user_with_maintenance_permissions)
        request_as_basic_user = basic_user_env["maintenance.request"].search([('id', '=', request.id)])
        self.assertFalse(request_as_basic_user.user_is_external_contractor)
