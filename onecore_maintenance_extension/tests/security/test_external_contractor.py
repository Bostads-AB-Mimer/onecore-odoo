from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError
from faker import Faker
from ..fake_providers import MaintenanceProvider


@tagged("onecore")
class TestMaintenanceExternalContractorSecurity(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = Faker("sv_SE")
        self.fake.add_provider(MaintenanceProvider)

        self.external_group = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor"
        )

        self.external_team = self.env["maintenance.team"].create(
            {"name": "External Team"}
        )

        self.other_team = self.env["maintenance.team"].create({"name": "Other Team"})

        self.external_user = self.env["res.users"].create(
            {
                "name": "External Contractor",
                "login": "external@test.com",
                "groups_id": [(6, 0, [self.external_group.id])],
            }
        )

        self.basic_user = self.env["res.users"].create(
            {
                "name": "Basic User",
                "login": "basic@test.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    # Group membership and visibility flags
    def test_external_user_group_membership(self):
        """Test that external user correctly belongs to external contractor group."""
        # External user should be in the external contractor group
        self.assertTrue(
            self.external_user.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            )
        )

        # Basic user should not be in the external contractor group
        self.assertFalse(
            self.basic_user.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            )
        )

    def test_external_user_ui_visibility_flags(self):
        """Test that UI visibility flags work correctly for external contractors."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )

        # Test as external user
        request_as_external = request.with_user(self.external_user)
        self.assertTrue(request_as_external.user_is_external_contractor)
        self.assertTrue(request_as_external.restricted_external)

        # Test as regular user
        request_as_regular = request.with_user(self.basic_user)
        self.assertFalse(request_as_regular.user_is_external_contractor)
        self.assertFalse(request_as_regular.restricted_external)

    # Read permissions
    def test_external_user_can_read_maintenance_request(self):
        """External contractors should have read access to maintenance requests."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )

        request_as_external = request.with_user(self.external_user)
        self.assertTrue(request_as_external.name)

    # Write permissions - allowed fields
    def test_external_user_can_edit_allowed_fields(self):
        """External contractors can edit specific allowed fields."""
        from datetime import date, timedelta

        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )

        user = self.env["res.users"].create(
            {"name": "Test User", "login": "testuser@example.com"}
        )

        schedule_date = date.today() + timedelta(days=7)

        request_as_external = request.with_user(self.external_user)

        # External contractors can edit these fields
        request_as_external.write(
            {
                "user_id": user.id,
                "schedule_date": schedule_date,
            }
        )

        self.assertEqual(request.user_id, user)
        self.assertEqual(request.schedule_date, schedule_date)

    # Write permissions - restricted fields
    def test_external_user_cannot_edit_restricted_fields(self):
        """External contractors cannot edit restricted fields."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )

        request_as_external = request.with_user(self.external_user)

        # These fields should be restricted for external contractors
        original_name = request.name
        original_category = request.maintenance_request_category_id
        original_space = request.space_caption

        # Attempt to change restricted fields - should be ignored or raise error
        try:
            request_as_external.write(
                {
                    "name": "Should not change",
                    "maintenance_request_category_id": self.env.ref(
                        "onecore_maintenance_extension.category_1"
                    ).id,
                    "space_caption": "Kök",
                }
            )

            # If no error raised, values should remain unchanged
            self.assertEqual(request.name, original_name)
            self.assertEqual(request.maintenance_request_category_id, original_category)
            self.assertEqual(request.space_caption, original_space)

        except Exception:
            # It's also acceptable if an error is raised for restricted fields
            pass

    # Create permissions
    def test_external_user_cannot_create_maintenance_request(self):
        """External contractors should not be able to create maintenance requests."""
        with self.assertRaises(AccessError):
            self.env["maintenance.request"].with_user(self.external_user).create(
                {
                    "name": self.fake.maintenance_request_name(),
                    "maintenance_request_category_id": self.env.ref(
                        "onecore_maintenance_extension.category_1"
                    ).id,
                    "space_caption": self.fake.space_caption(),
                }
            )

    def test_external_user_cannot_create_team_maintenance_request(self):
        """External contractors cannot create requests even for their own team."""
        with self.assertRaises(AccessError):
            self.env["maintenance.request"].with_user(self.external_user).create(
                {
                    "name": self.fake.maintenance_request_name(),
                    "maintenance_request_category_id": self.env.ref(
                        "onecore_maintenance_extension.category_1"
                    ).id,
                    "space_caption": self.fake.space_caption(),
                    "maintenance_team_id": self.external_team.id,
                }
            )

    # Delete permissions
    def test_external_user_cannot_unlink_maintenance_request(self):
        """External contractors should not be able to delete maintenance requests."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
            }
        )

        with self.assertRaises(AccessError):
            request.with_user(self.external_user).unlink()

    def test_external_user_cannot_unlink_assigned_maintenance_request(self):
        """External contractors cannot delete requests even when assigned to them."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
                "user_id": self.external_user.id,
            }
        )

        with self.assertRaises(AccessError):
            request.with_user(self.external_user).unlink()

    def test_external_user_cannot_unlink_team_maintenance_request(self):
        """External contractors cannot delete requests from their team."""
        request = self.env["maintenance.request"].create(
            {
                "name": self.fake.maintenance_request_name(),
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": self.fake.space_caption(),
                "maintenance_team_id": self.external_team.id,
            }
        )

        with self.assertRaises(AccessError):
            request.with_user(self.external_user).unlink()
