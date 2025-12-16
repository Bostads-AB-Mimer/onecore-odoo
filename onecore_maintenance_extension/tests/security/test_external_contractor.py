from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError
from datetime import date, timedelta

from ..test_utils import create_maintenance_request


@tagged("onecore")
class TestMaintenanceExternalContractorSecurity(TransactionCase):
    def setUp(self):
        super().setUp()

        self.external_team = self.env["maintenance.team"].create(
            {"name": "External Contractor Team"}
        )

        self.other_team = self.env["maintenance.team"].create(
            {"name": "Other Team"}
        )

        self.external_contractor = self.env["res.users"].create(
            {
                "name": "External Contractor",
                "login": "external@test.com",
                "email": "external@test.com",
                "groups_id": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("onecore_maintenance_extension.group_external_contractor").id,
                ])],
            }
        )

        # Assign external contractor to their team
        self.external_team.write({"member_ids": [(4, self.external_contractor.id)]})

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

    def test_external_contractor_cannot_create_maintenance_records(self):
        """External contractors should not be able to create maintenance records"""
        external_contractor_env = self.env(user=self.external_contractor)

        with self.assertRaises(AccessError):
            create_maintenance_request(external_contractor_env)

    def test_external_contractor_can_read_records_assigned_to_their_team(self):
        """External contractors should be able to read records assigned to their team"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.external_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)
        self.assertEqual(request_as_external_contractor.id, request.id)
        self.assertTrue(request_as_external_contractor.name)

    def test_external_contractor_cannot_read_records_assigned_to_other_teams(self):
        """External contractors should not be able to read records assigned to other teams"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.other_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        with self.assertRaises(AccessError):
            external_contractor_env["maintenance.request"].browse(request.id).name

    def test_external_contractor_cannot_read_records_without_team_assignment(self):
        """External contractors should not be able to read records without team assignment"""
        request = create_maintenance_request(self.env)

        external_contractor_env = self.env(user=self.external_contractor)
        with self.assertRaises(AccessError):
            external_contractor_env["maintenance.request"].browse(request.id).name

    def test_external_contractor_can_update_allowed_fields_on_team_records(self):
        """External contractors should be able to update allowed fields on their team's records"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.external_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        schedule_date = date.today() + timedelta(days=7)
        request_as_external_contractor.write({
            "user_id": self.external_contractor.id,
            "schedule_date": schedule_date,
        })

        self.assertEqual(request.user_id, self.external_contractor)
        self.assertEqual(request.schedule_date.date(), schedule_date)

    def test_external_contractor_cannot_update_records_assigned_to_other_teams(self):
        """External contractors should not be able to update records assigned to other teams"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.other_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.write({"user_id": self.external_contractor.id})

    def test_external_contractor_cannot_update_records_without_team_assignment(self):
        """External contractors should not be able to update records without team assignment"""
        request = create_maintenance_request(self.env)

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.write({"user_id": self.external_contractor.id})

    def test_external_contractor_cannot_delete_maintenance_records(self):
        """External contractors should not be able to delete maintenance records"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.external_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.unlink()

    def test_external_contractor_cannot_delete_records_assigned_to_them(self):
        """External contractors cannot delete records even when assigned to them"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.external_team.id,
            user_id=self.external_contractor.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.unlink()

    def test_external_contractor_cannot_delete_records_assigned_to_other_teams(self):
        """External contractors cannot delete records assigned to other teams"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.other_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.unlink()

    def test_external_contractor_cannot_delete_records_without_team_assignment(self):
        """External contractors cannot delete records without team assignment"""
        request = create_maintenance_request(self.env)

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].browse(request.id)

        with self.assertRaises(AccessError):
            request_as_external_contractor.unlink()

    def test_external_contractor_has_correct_group_membership(self):
        """Verify external contractor is in the correct group"""
        self.assertTrue(
            self.external_contractor.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            )
        )
        self.assertFalse(
            self.basic_user_with_maintenance_permissions.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            )
        )

    def test_external_contractor_ui_visibility_flags(self):
        """External contractors should have correct UI visibility flags set"""
        request = create_maintenance_request(
            self.env,
            maintenance_team_id=self.external_team.id
        )

        external_contractor_env = self.env(user=self.external_contractor)
        request_as_external_contractor = external_contractor_env["maintenance.request"].search([('id', '=', request.id)])
        self.assertTrue(request_as_external_contractor.user_is_external_contractor)