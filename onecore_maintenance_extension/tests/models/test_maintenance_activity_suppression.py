from datetime import datetime
from odoo.tests.common import TransactionCase


class TestMaintenanceActivitySuppression(TransactionCase):
    """Test that automatic maintenance activity creation is completely suppressed.

    This suppresses the 'maintenance.mail_act_maintenance_request' activity type
    that would normally be created for scheduled maintenance requests.
    """

    def setUp(self):
        super().setUp()
        self.MaintenanceRequest = self.env["maintenance.request"]
        self.MaintenanceTeam = self.env["maintenance.team"]
        self.MaintenanceCategory = self.env["maintenance.request.category"]

        # Create test team and category
        self.test_team = self.MaintenanceTeam.create({"name": "Test Team"})
        self.test_category = self.MaintenanceCategory.create(
            {"name": "Test Category", "category_type": "repair"}
        )
        self.test_user = self.env["res.users"].create(
            {
                "name": "Test User",
                "login": "testuser",
            }
        )

    def _create_test_request(self, **kwargs):
        """Helper to create a test maintenance request with required fields."""
        vals = {
            "name": "Test Request",
            "maintenance_team_id": self.test_team.id,
            "maintenance_request_category_id": self.test_category.id,
            "space_caption": "Lägenhet",
        }
        vals.update(kwargs)
        return self.MaintenanceRequest.create(vals)

    def test_no_activity_on_create_with_schedule_date(self):
        """Verify no activity is created when creating request with schedule_date"""
        request = self._create_test_request(
            schedule_date=datetime(2026, 3, 1, 10, 0, 0),
        )
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No activities should be created automatically for schedule_date",
        )

    def test_no_activity_on_schedule_date_update(self):
        """Verify no activity is created when updating only schedule_date"""
        request = self._create_test_request()
        request.write({"schedule_date": datetime(2026, 3, 1, 10, 0, 0)})
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No activities should be created when only schedule_date changes",
        )

    def test_no_activity_on_user_change_with_schedule_date(self):
        """Verify no automatic activity is created when changing user_id"""
        request = self._create_test_request(
            schedule_date=datetime(2026, 3, 1, 10, 0, 0),
        )
        # Changing user_id should NOT create automatic maintenance activity
        request.write({"user_id": self.test_user.id})
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No automatic maintenance activities should be created",
        )

    def test_existing_activities_preserved(self):
        """Verify existing manually created activities remain untouched"""
        request = self._create_test_request()

        # Manually create an activity
        activity = self.env["mail.activity"].create(
            {
                "res_id": request.id,
                "res_model_id": self.env["ir.model"]._get("maintenance.request").id,
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "summary": "Manual Activity",
                "user_id": self.test_user.id,
            }
        )

        # Trigger schedule_date change (should not affect manual activity)
        request.write({"schedule_date": datetime(2026, 3, 1, 10, 0, 0)})

        # Verify manual activity still exists
        self.assertEqual(len(request.activity_ids), 1)
        self.assertEqual(request.activity_ids[0].id, activity.id)
        self.assertEqual(request.activity_ids[0].summary, "Manual Activity")

    def test_manual_activity_creation_still_works(self):
        """Verify that manual activity creation is not affected"""
        request = self._create_test_request(
            schedule_date=datetime(2026, 3, 1, 10, 0, 0),
        )

        # Manually schedule an activity
        request.activity_schedule(
            "mail.mail_activity_data_todo",
            summary="Manual Todo",
            user_id=self.test_user.id,
        )

        self.assertEqual(len(request.activity_ids), 1)
        self.assertEqual(request.activity_ids[0].summary, "Manual Todo")

    def test_no_activity_on_schedule_date_change_only(self):
        """Verify changing schedule_date value doesn't create activity"""
        request = self._create_test_request(
            schedule_date=datetime(2026, 3, 1, 10, 0, 0),
        )
        # Change schedule_date to a different date
        request.write({"schedule_date": datetime(2026, 4, 1, 10, 0, 0)})
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No activities should be created when schedule_date value changes",
        )

    def test_no_activity_on_user_and_schedule_date_together(self):
        """Verify no automatic activity when both user_id and schedule_date change"""
        request = self._create_test_request()
        # Changing both should NOT create automatic maintenance activity
        request.write(
            {
                "user_id": self.test_user.id,
                "schedule_date": datetime(2026, 3, 1, 10, 0, 0),
            }
        )
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No automatic maintenance activities should be created",
        )

    def test_no_activity_on_create_with_user_and_schedule_date(self):
        """Verify no automatic activity when creating with user and schedule_date"""
        request = self._create_test_request(
            user_id=self.test_user.id,
            schedule_date=datetime(2026, 3, 1, 10, 0, 0),
        )
        self.assertEqual(
            len(request.activity_ids),
            0,
            "No automatic maintenance activities should be created",
        )
