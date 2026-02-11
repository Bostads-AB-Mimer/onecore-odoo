from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError
from datetime import date

from ...utils.test_utils import create_internal_user, create_maintenance_request


class StageTestMixin:
    """Mixin for maintenance stage lookups"""

    def _get_stage(self, stage_name):
        """Get maintenance stage by name"""
        return self.env["maintenance.stage"].search([("name", "=", stage_name)])

    def _setup_common_stages(self):
        """Setup commonly used stage references"""
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.stage_tilldelad = self._get_stage("Resurs tilldelad")
        self.stage_paborjad = self._get_stage("Påbörjad")
        self.stage_vantar_varor = self._get_stage("Väntar på beställda varor")


@tagged("onecore")
class TestMaintenanceStageManager(StageTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self._setup_common_stages()

    def test_stage_transitions_without_user_assignment(self):
        """Without assigned user, can only move to 'Väntar på handläggning' or 'Avslutad'"""
        request = create_maintenance_request(self.env, stage_id=self.stage_vantar.id)

        # Should fail for restricted stages (run as internal user to avoid external contractor checks)
        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.with_user(self.internal_user).write({"stage_id": self.stage_tilldelad.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.with_user(self.internal_user).write({"stage_id": self.stage_paborjad.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.with_user(self.internal_user).write({"stage_id": self.stage_vantar_varor.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.with_user(self.internal_user).write({"stage_id": self.stage_utford.id})

        request.with_user(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        self.assertEqual(request.stage_id, self.stage_avslutad)

        request.with_user(self.internal_user).write({"stage_id": self.stage_vantar.id})
        self.assertEqual(request.stage_id, self.stage_vantar)

    def test_initial_user_assignment_sets_request_stage_to_resurs_tilldelad(self):
        """Creating request with user assignment should set stage to 'Resurs tilldelad'"""
        request = create_maintenance_request(
            self.env, user_id=self.internal_user.id, stage_id=self.stage_vantar.id
        )

        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_user_assignment_triggers_request_stage_transition_to_resurs_tilldelad(self):
        """Assigning a user when in 'Väntar på handläggning' should move to 'Resurs tilldelad'"""
        request = create_maintenance_request(self.env, stage_id=self.stage_vantar.id)

        request.write({"user_id": self.internal_user.id})
        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_user_unassignment_triggers_request_stage_transition_to_vantar_pa_handlaggning(self):
        """Unassigning user when in 'Resurs tilldelad' should move to 'Väntar på handläggning'"""
        request = create_maintenance_request(
            self.env, stage_id=self.stage_tilldelad.id, user_id=self.internal_user.id
        )

        request.write({"user_id": False})
        self.assertEqual(request.stage_id, self.stage_vantar)

    def test_assigned_user_can_move_request_to_any_stage(self):
        """With assigned user, should be able to move to any stage"""
        request = create_maintenance_request(
            self.env, stage_id=self.stage_vantar.id, user_id=self.internal_user.id
        )
        request.write({"stage_id": self.stage_paborjad.id})
        self.assertEqual(request.stage_id, self.stage_paborjad)

        request.write({"stage_id": self.stage_vantar_varor.id})
        self.assertEqual(request.stage_id, self.stage_vantar_varor)

        request.write({"stage_id": self.stage_utford.id})
        self.assertEqual(request.stage_id, self.stage_utford)


@tagged("onecore")
class TestFieldChangeTracker(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)

        from ....models.services import FieldChangeTracker

        self.change_tracker = FieldChangeTracker(self.env)

    def test_field_change_tracking(self):
        """Test change tracking for different field types"""
        request = create_maintenance_request(
            self.env,
            description="Old description",
            priority_expanded="5",
            start_date=date(2023, 1, 15),
            hidden_from_my_pages=False,
        )

        # Test multiple field changes at once
        changes = self.change_tracker.track_field_changes(
            request,
            {
                "description": "New description",
                "priority_expanded": "10",
                "start_date": date(2023, 2, 20),
                "hidden_from_my_pages": True,
            },
        )

        # Should have tracked all changes
        self.assertIn(request.id, changes)
        self.assertEqual(len(changes[request.id]), 4)

        # Check that all field labels are present
        change_texts = changes[request.id]
        self.assertTrue(any("Description" in c for c in change_texts))
        self.assertTrue(any("Prioritet" in c for c in change_texts))
        self.assertTrue(any("Startdatum" in c for c in change_texts))
        self.assertTrue(any("Dold från Mimer.nu" in c for c in change_texts))

        # Check selection field formatting
        priority_change = next((c for c in change_texts if "Prioritet" in c), None)
        self.assertIn("5 dagar", priority_change)
        self.assertIn("10 dagar", priority_change)
        self.assertIn("→", priority_change)

    def test_many2one_field_change_formatting(self):
        """Test Many2one field change formatting with various scenarios"""
        request = create_maintenance_request(self.env)

        # Test assignment from empty
        change = self.change_tracker._format_field_change(
            request._fields["user_id"], False, self.internal_user.id, "User"
        )
        self.assertIn("Inte valt", change)
        self.assertIn(self.internal_user.display_name, change)
        self.assertIn("→", change)

        # Test change between two users
        other_user = create_internal_user(self.env)
        change = self.change_tracker._format_field_change(
            request._fields["user_id"],
            self.internal_user,
            other_user.id,
            "User",
        )
        self.assertIn(self.internal_user.display_name, change)
        self.assertIn(other_user.display_name, change)
        self.assertIn("→", change)

        # Test clearing a field
        change = self.change_tracker._format_field_change(
            request._fields["user_id"], self.internal_user, False, "User"
        )
        self.assertIn(self.internal_user.display_name, change)
        self.assertIn("Inte valt", change)
        self.assertIn("→", change)

    def test_selection_field_change_formatting(self):
        """Test Selection field change formatting"""
        request = create_maintenance_request(self.env)

        # Test priority change
        change = self.change_tracker._format_field_change(
            request._fields["priority_expanded"], "5", "10", "Priority"
        )
        self.assertIn("5 dagar", change)
        self.assertIn("10 dagar", change)
        self.assertIn("→", change)

        # Test setting from empty
        change = self.change_tracker._format_field_change(
            request._fields["priority_expanded"], False, "7", "Priority"
        )
        self.assertIn("Inte satt", change)
        self.assertIn("7 dagar", change)

    def test_date_field_change_formatting(self):
        """Test Date field change formatting with edge cases"""
        request = create_maintenance_request(self.env)
        field_obj = request._fields["start_date"]

        # Test normal date change
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), date(2023, 2, 20), "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("2023-02-20", change)
        self.assertIn("→", change)

        # Test setting date from empty
        change = self.change_tracker._format_field_change(
            field_obj, False, date(2023, 3, 15), "Start Date"
        )
        self.assertIn("Inte satt", change)
        self.assertIn("2023-03-15", change)

        # Test clearing date
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), False, "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("Inte satt", change)

        # Test string date value (edge case)
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), "invalid-date", "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("invalid-date", change)

    def test_change_notification_posting(self):
        """Test that change notifications are properly posted as messages"""
        request = create_maintenance_request(self.env, description="Initial description")

        # Count messages before update
        initial_count = len(request.message_ids)

        # Update with change tracking enabled (clear creating_records context)
        request.with_context(creating_records=False).write(
            {"description": "Updated description", "priority_expanded": "7"}
        )

        # Should have posted a new message
        self.assertGreater(len(request.message_ids), initial_count)

        # Check the latest message
        latest_message = request.message_ids.sorted("id", reverse=True)[0]
        self.assertEqual(latest_message.message_type, "notification")
        self.assertIn("Description", latest_message.body)
        self.assertIn("Prioritet", latest_message.body)

    def test_no_notification_when_no_tracked_changes(self):
        """Test that no notification is posted when only excluded fields change"""
        request = create_maintenance_request(self.env)

        # Count messages before update
        initial_count = len(request.message_ids)

        # Update only excluded fields
        request.with_context(creating_records=False).write(
            {"stage_id": request.stage_id.id}  # Same value, no real change
        )

        # Should not have posted any new messages
        self.assertEqual(len(request.message_ids), initial_count)

    def test_multiple_records_change_tracking(self):
        """Test change tracking works correctly for multiple records"""
        request1 = create_maintenance_request(self.env, description="Request 1")
        request2 = create_maintenance_request(self.env, description="Request 2")

        requests = request1 | request2

        # Update both records
        changes = self.change_tracker.track_field_changes(
            requests, {"priority_expanded": "7"}
        )

        # Should track changes for both records
        self.assertIn(request1.id, changes)
        self.assertIn(request2.id, changes)
        self.assertEqual(len(changes[request1.id]), 1)
        self.assertEqual(len(changes[request2.id]), 1)

    def test_create_skips_change_tracking_during_creation(self):
        """Change tracking should be skipped during record creation"""
        # Count initial notifications
        initial_message_count = self.env["mail.message"].search_count([])

        request = create_maintenance_request(self.env, description="Initial description")

        # Should not have created change tracking notifications during creation
        final_message_count = self.env["mail.message"].search_count([])
        # Allow for some messages (like creation notification) but not change tracking
        self.assertLess(final_message_count - initial_message_count, 3)
