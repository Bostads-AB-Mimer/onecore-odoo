from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError
from datetime import date, timedelta
from faker import Faker
from ..fake_providers import MaintenanceProvider


class FakerMixin:
    """Mixin providing faker setup"""

    def _setup_faker(self):
        """Setup faker with Swedish locale and maintenance provider"""
        if not hasattr(self, "fake"):
            self.fake = Faker("sv_SE")
            self.fake.add_provider(MaintenanceProvider)


class UserTestMixin:
    """Mixin for creating test users"""

    def _create_internal_user(self, **kwargs):
        """Create internal user with standard groups"""
        if not hasattr(self, "fake"):
            self._setup_faker()

        defaults = {
            "name": self.fake.name(),
            "login": self.fake.email(),
            "groups_id": [
                (
                    6,
                    0,
                    [
                        self.env.ref("base.group_user").id,
                        self.env.ref("maintenance.group_equipment_manager").id,
                    ],
                )
            ],
        }
        defaults.update(kwargs)
        return self.env["res.users"].create(defaults)

    def _create_external_user(self, **kwargs):
        """Create external contractor user"""
        if not hasattr(self, "fake"):
            self._setup_faker()

        # Ensure external contractor group exists
        group_external = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor",
            raise_if_not_found=False,
        )
        if not group_external:
            group_external = self.env["res.groups"].create(
                {
                    "name": "External Contractor",
                }
            )

        defaults = {
            "name": self.fake.name(),
            "login": self.fake.email(),
            "groups_id": [(6, 0, [group_external.id])],
        }
        defaults.update(kwargs)
        return self.env["res.users"].create(defaults)


class StageTestMixin:
    """Mixin for maintenance stage lookups"""

    def _get_stage(self, stage_name):
        """Get maintenance stage by name"""
        return self.env["maintenance.stage"].search([("name", "=", stage_name)])

    def _setup_common_stages(self):
        """Setup commonly used stages"""
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.stage_tilldelad = self._get_stage("Resurs tilldelad")
        self.stage_paborjad = self._get_stage("Påbörjad")
        self.stage_vantar_varor = self._get_stage("Väntar på beställda varor")


class MaintenanceRequestTestMixin(FakerMixin):
    """Mixin providing common functionality for maintenance request tests"""

    def _create_maintenance_request(self, **kwargs):
        """Create maintenance request with minimal required fields"""
        self._setup_faker()

        defaults = {
            "name": self.fake.maintenance_request_name(),
            "maintenance_request_category_id": self.env.ref(
                "onecore_maintenance_extension.category_1"
            ).id,
            "space_caption": self.fake.space_caption(),
        }
        defaults.update(kwargs)
        return self.env["maintenance.request"].create(defaults)


@tagged("onecore")
class TestMaintenanceRequestStageTransitions(
    MaintenanceRequestTestMixin, UserTestMixin, StageTestMixin, TransactionCase
):

    def setUp(self):
        super().setUp()
        self.internal_user = self._create_internal_user()
        self._setup_common_stages()

    def test_without_assigned_resource_request_can_only_be_moved_to_avslutad(self):
        """From 'Väntar på handläggning' without user, can only move to 'Avslutad'"""
        # Create as admin to avoid external contractor restrictions
        request = self._create_maintenance_request(stage_id=self.stage_vantar.id)

        # Should NOT be able to move to other stages when no user assigned
        with self.assertRaises(UserError):
            request.write({"stage_id": self.stage_tilldelad.id})

        with self.assertRaises(UserError):
            request.write({"stage_id": self.stage_paborjad.id})

        with self.assertRaises(UserError):
            request.write({"stage_id": self.stage_vantar_varor.id})

        with self.assertRaises(UserError):
            request.write({"stage_id": self.stage_utford.id})

        # Should be able to move to Avslutad as internal user (not external contractor)
        request.with_user(self.internal_user).write(
            {"stage_id": self.stage_avslutad.id}
        )
        self.assertEqual(request.stage_id, self.stage_avslutad)


@tagged("onecore")
class TestMaintenanceRequestDueDate(MaintenanceRequestTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_faker()

    def test_due_date_with_priority_and_request_date(self):
        """Due date should be request_date + priority_expanded days if start_date is not set."""
        request_date = date.today()
        priority_days = 5
        request = self._create_maintenance_request(
            request_date=request_date, priority_expanded=str(priority_days)
        )
        expected_due_date = request_date + timedelta(days=priority_days)
        self.assertEqual(request.due_date, expected_due_date)

    def test_due_date_with_priority_and_start_date(self):
        """Due date should be start_date + priority_expanded days if start_date is set."""
        request_date = date.today()
        start_date = request_date + timedelta(days=2)
        priority_days = 5
        request = self._create_maintenance_request(
            request_date=request_date,
            start_date=start_date,
            priority_expanded=str(priority_days),
        )
        expected_due_date = start_date + timedelta(days=priority_days)
        self.assertEqual(request.due_date, expected_due_date)

    def test_due_date_with_missing_priority(self):
        """Due date should be None if priority_expanded is not set."""
        request = self._create_maintenance_request(request_date=date.today())
        self.assertFalse(request.due_date)


# @tagged("onecore")
# class TestMaintenanceRequestSearchAndOptionUpdate(
#     MaintenanceRequestTestMixin, TransactionCase
# ):
#     def setUp(self):
#         super().setUp()
#         self.fake = Faker("sv_SE")
#         self.fake.add_provider(MaintenanceProvider)
#         self.tenant = self.env["maintenance.tenant.option"].create(
#             {
#                 "user_id": self.env.user.id,
#                 "name": self.fake.tenant_full_name(),
#                 "contact_code": "T123",
#                 "contact_key": "key123",
#             }
#         )
#         self.lease = self.env["maintenance.lease.option"].create(
#             {
#                 "user_id": self.env.user.id,
#                 "name": self.fake.lease_model_name(),
#                 "lease_number": "L456",
#                 "lease_type": "TypeA",
#             }
#         )
#         self.property = self.env["maintenance.rental.property.option"].create(
#             {
#                 "user_id": self.env.user.id,
#                 "name": self.fake.rental_property_name(),
#                 "code": "P789",
#                 "property_type": "Lägenhet",
#             }
#         )
#         self.request = self._create_maintenance_request(
#             tenant_option_id=self.tenant.id,
#             lease_option_id=self.lease.id,
#             rental_property_option_id=self.property.id,
#         )

#     def test_compute_search_by_number(self):
#         """Search by number method exists and has basic functionality."""
#         # Skip test - requires network/API access, will add mock data later
#         self.skipTest("Skipping search test - requires mock API data")

#     def test_update_form_options_updates_related_fields(self):
#         """update_form_options method exists and has basic functionality."""
#         # Skip test - requires network/API access, will add mock data later
#         self.skipTest("Skipping form options test - requires mock API data")


@tagged("onecore")
class TestMaintenanceRequestExternalContractor(
    MaintenanceRequestTestMixin, UserTestMixin, StageTestMixin, TransactionCase
):
    def setUp(self):
        super().setUp()
        self.external_user = self._create_external_user()
        self.internal_user = self._create_internal_user(
            groups_id=[(6, 0, [self.env.ref("base.group_user").id])]
        )
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.request = self._create_maintenance_request()

    def test_user_is_external_contractor_true(self):
        """user_is_external_contractor should be True for external contractor."""
        self.assertTrue(
            self.request.with_user(self.external_user).user_is_external_contractor
        )

    def test_user_is_external_contractor_false(self):
        """user_is_external_contractor should be False for internal user."""
        self.assertFalse(
            self.request.with_user(self.internal_user).user_is_external_contractor
        )

    def test_restricted_external_field(self):
        """restricted_external should reflect correct restriction status."""
        restricted = self.request.with_user(self.external_user).restricted_external
        self.assertIsInstance(restricted, bool)


@tagged("onecore")
class TestMaintenanceRequestStageValidation(
    MaintenanceRequestTestMixin, UserTestMixin, StageTestMixin, TransactionCase
):
    def setUp(self):
        super().setUp()
        self.internal_user = self._create_internal_user()
        self.external_user = self._create_external_user()
        self._setup_common_stages()

    def test_external_contractor_cannot_move_from_utford_stage(self):
        """External contractors cannot move requests from 'Utförd' stage to any other stage"""
        request = self._create_maintenance_request(stage_id=self.stage_utford.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Utförd"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_vantar.id}
            )

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Utförd"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_paborjad.id}
            )

    def test_external_contractor_cannot_move_from_avslutad_stage(self):
        """External contractors cannot move requests from 'Avslutad' stage to any other stage"""
        request = self._create_maintenance_request(stage_id=self.stage_avslutad.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende från Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_vantar.id}
            )

    def test_external_contractor_cannot_move_to_avslutad_stage(self):
        """External contractors cannot move requests to 'Avslutad' stage"""
        request = self._create_maintenance_request(stage_id=self.stage_vantar.id)

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_avslutad.id}
            )

    def test_internal_user_can_move_to_allowed_stages_without_user_assignment(self):
        """Internal users can move to allowed stages ('Väntar på handläggning', 'Avslutad') without user assignment"""
        request = self._create_maintenance_request(stage_id=self.stage_tilldelad.id)

        # Should succeed for allowed stages even without user assignment
        request.with_user(self.internal_user).write({"stage_id": self.stage_vantar.id})
        self.assertEqual(request.stage_id, self.stage_vantar)

        request.with_user(self.internal_user).write(
            {"stage_id": self.stage_avslutad.id}
        )
        self.assertEqual(request.stage_id, self.stage_avslutad)

    def test_cannot_move_to_restricted_stages_without_user_assignment(self):
        """Without assigned user, can only move to 'Väntar på handläggning' or 'Avslutad'"""
        request = self._create_maintenance_request(stage_id=self.stage_vantar.id)

        # Should fail for restricted stages
        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.write({"stage_id": self.stage_tilldelad.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.write({"stage_id": self.stage_paborjad.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.write({"stage_id": self.stage_vantar_varor.id})

        with self.assertRaisesRegex(UserError, "Ingen resurs är tilldelad"):
            request.write({"stage_id": self.stage_utford.id})

    def test_user_assignment_triggers_stage_transition_to_resurs_tilldelad(self):
        """Assigning a user when in 'Väntar på handläggning' should move to 'Resurs tilldelad'"""
        request = self._create_maintenance_request(stage_id=self.stage_vantar.id)

        request.write({"user_id": self.internal_user.id})
        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_user_unassignment_triggers_stage_transition_to_vantar_pa_handlaggning(
        self,
    ):
        """Unassigning user when in 'Resurs tilldelad' should move to 'Väntar på handläggning'"""
        request = self._create_maintenance_request(
            stage_id=self.stage_tilldelad.id, user_id=self.internal_user.id
        )

        request.write({"user_id": False})
        self.assertEqual(request.stage_id, self.stage_vantar)

    def test_assigned_user_can_move_to_any_stage(self):
        """With assigned user, should be able to move to any stage"""
        request = self._create_maintenance_request(
            stage_id=self.stage_vantar.id, user_id=self.internal_user.id
        )

        # Should succeed for all stages when user is assigned
        request.write({"stage_id": self.stage_paborjad.id})
        self.assertEqual(request.stage_id, self.stage_paborjad)

        request.write({"stage_id": self.stage_vantar_varor.id})
        self.assertEqual(request.stage_id, self.stage_vantar_varor)

        request.write({"stage_id": self.stage_utford.id})
        self.assertEqual(request.stage_id, self.stage_utford)

    def test_external_contractor_restrictions_take_precedence_over_user_assignment_rules(
        self,
    ):
        """External contractor restrictions are checked before user assignment requirements"""
        # External contractors cannot move to Avslutad even without user assignment requirements
        request = self._create_maintenance_request(
            stage_id=self.stage_vantar.id
        )  # No user assigned

        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            request.with_user(self.external_user).write(
                {"stage_id": self.stage_avslutad.id}
            )


@tagged("onecore")
class TestMaintenanceRequestCreation(
    MaintenanceRequestTestMixin, UserTestMixin, StageTestMixin, TransactionCase
):
    def setUp(self):
        super().setUp()
        self.internal_user = self._create_internal_user()
        self._setup_common_stages()

    def test_create_with_user_assignment_sets_correct_stage(self):
        """Creating request with user assignment should set stage to 'Resurs tilldelad'"""
        request = self._create_maintenance_request(
            user_id=self.internal_user.id, stage_id=self.stage_vantar.id
        )

        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_create_saves_property_option_to_permanent_record(self):
        """Creating request with property_option_id should create permanent property record"""
        self._setup_faker()

        # Create a property option first
        property_designation = self.fake.property_designation()
        property_code = self.fake.property_code()
        property_option = self.env["maintenance.property.option"].create(
            {
                "user_id": self.env.user.id,
                "designation": property_designation,
                "code": property_code,
            }
        )

        request = self._create_maintenance_request(
            property_option_id=property_option.id
        )

        # Should have created a permanent property record
        self.assertTrue(request.property_id)
        self.assertEqual(request.property_id.designation, property_designation)
        self.assertEqual(request.property_id.code, property_code)

    def test_create_saves_building_option_to_permanent_record(self):
        """Creating request with building_option_id should create permanent building record"""
        self._setup_faker()

        building_name = self.fake.building_name()
        building_code = self.fake.building_code()
        building_option = self.env["maintenance.building.option"].create(
            {"user_id": self.env.user.id, "name": building_name, "code": building_code}
        )

        request = self._create_maintenance_request(
            building_option_id=building_option.id
        )

        # Should have created a permanent building record
        self.assertTrue(request.building_id)
        self.assertEqual(request.building_id.name, building_name)
        self.assertEqual(request.building_id.code, building_code)

    def test_create_saves_rental_property_option_to_permanent_record(self):
        """Creating request with rental_property_option_id should create permanent rental property record"""
        self._setup_faker()

        property_name = self.fake.rental_property_name()
        property_address = self.fake.address()
        property_code = self.fake.rental_property_code()
        rental_property_option = self.env["maintenance.rental.property.option"].create(
            {
                "user_id": self.env.user.id,
                "name": property_name,
                "address": property_address,
                "code": property_code,
                "property_type": "Apartment",
            }
        )

        request = self._create_maintenance_request(
            rental_property_option_id=rental_property_option.id
        )

        # Should have created a permanent rental property record
        self.assertTrue(request.rental_property_id)
        self.assertEqual(request.rental_property_id.name, property_name)
        self.assertEqual(request.rental_property_id.address, property_address)
        self.assertEqual(request.rental_property_id.code, property_code)

    def test_create_saves_tenant_option_to_permanent_record(self):
        """Creating request with tenant_option_id should create permanent tenant record"""
        self._setup_faker()

        tenant_name = self.fake.tenant_full_name()
        contact_code = self.fake.contact_code()
        contact_key = self.fake.contact_key()
        phone_number = self.fake.phone_number()
        email_address = self.fake.email()

        tenant_option = self.env["maintenance.tenant.option"].create(
            {
                "user_id": self.env.user.id,
                "name": tenant_name,
                "contact_code": contact_code,
                "contact_key": contact_key,
                "phone_number": phone_number,
                "email_address": email_address,
            }
        )

        # Hide from Mimer to prevent SMS sending during test
        request = self._create_maintenance_request(
            tenant_option_id=tenant_option.id, hidden_from_my_pages=True
        )

        # Should have created a permanent tenant record
        self.assertTrue(request.tenant_id)
        self.assertEqual(request.tenant_id.name, tenant_name)
        self.assertEqual(request.tenant_id.contact_code, contact_code)
        self.assertEqual(request.tenant_id.phone_number, phone_number)

    def test_create_uses_form_phone_email_over_option_values(self):
        """When creating with modified phone/email in form, should use form values over option values"""
        self._setup_faker()

        tenant_name = self.fake.tenant_full_name()
        contact_code = self.fake.contact_code()
        contact_key = self.fake.contact_key()
        original_phone = self.fake.phone_number()
        original_email = self.fake.email()
        new_phone = self.fake.phone_number()
        new_email = self.fake.email()

        tenant_option = self.env["maintenance.tenant.option"].create(
            {
                "user_id": self.env.user.id,
                "name": tenant_name,
                "contact_code": contact_code,
                "contact_key": contact_key,
                "phone_number": original_phone,
                "email_address": original_email,
            }
        )

        # Simulate form modification by passing phone/email in vals
        request_vals = {
            "name": self.fake.maintenance_request_name(),
            "maintenance_request_category_id": self.env.ref(
                "onecore_maintenance_extension.category_1"
            ).id,
            "space_caption": self.fake.space_caption(),
            "tenant_option_id": tenant_option.id,
            "phone_number": new_phone,  # Modified in form
            "email_address": new_email,  # Modified in form
            "hidden_from_my_pages": True,  # Prevent SMS sending
        }

        request = self.env["maintenance.request"].create(request_vals)

        # Should use the form values, not option values
        self.assertEqual(request.tenant_id.phone_number, new_phone)
        self.assertEqual(request.tenant_id.email_address, new_email)

    def test_create_skips_change_tracking_during_creation(self):
        """Change tracking should be skipped during record creation"""
        # Count initial notifications
        initial_message_count = self.env["mail.message"].search_count([])

        request = self._create_maintenance_request(description="Initial description")

        # Should not have created change tracking notifications during creation
        final_message_count = self.env["mail.message"].search_count([])
        # Allow for some messages (like creation notification) but not change tracking
        self.assertLess(final_message_count - initial_message_count, 3)


@tagged("onecore")
class TestMaintenanceRequestNotifications(
    MaintenanceRequestTestMixin, UserTestMixin, TransactionCase
):
    def setUp(self):
        super().setUp()
        self.internal_user = self._create_internal_user()

        from ...models.services import FieldChangeTracker
        self.change_tracker = FieldChangeTracker(self.env)

    def test_field_change_tracking_and_exclusions(self):
        """Test field change tracking and skip_fields exclusions"""
        request = self._create_maintenance_request()

        # Excluded fields should not be tracked
        excluded_changes = self.change_tracker.track_field_changes(request, {
                "stage_id": 1,
                "message_ids": [(0, 0, {"body": "test"})],
                "__last_update": "2023-01-01 12:00:00",
            }
        )
        self.assertEqual(excluded_changes, {})

        # Valid fields should be tracked
        valid_changes = self.change_tracker.track_field_changes(request, {
                "description": "New description",
                "stage_id": 1,  # Should be ignored
            }
        )
        self.assertIn(request.id, valid_changes)
        self.assertEqual(len(valid_changes[request.id]), 1)
        self.assertIn("Description", valid_changes[request.id][0])

    def test_comprehensive_field_change_tracking(self):
        """Test change tracking for different field types comprehensively"""
        request = self._create_maintenance_request(
            description="Old description",
            priority_expanded="5",
            start_date=date(2023, 1, 15),
            hidden_from_my_pages=False,
        )

        # Test multiple field changes at once
        changes = self.change_tracker.track_field_changes(request, {
                "description": "New description",
                "priority_expanded": "10",
                "start_date": date(2023, 2, 20),
                "hidden_from_my_pages": True,
                "user_id": self.internal_user.id,
            }
        )

        self.assertIn(request.id, changes)
        change_texts = changes[request.id]

        # Should have changes for all modified fields
        self.assertEqual(len(change_texts), 5)

        # Check specific formatting
        description_change = next((c for c in change_texts if "Description" in c), None)
        self.assertEqual(description_change, "<strong>Description:</strong> Uppdaterad")

        # Check selection field formatting
        priority_change = next((c for c in change_texts if "Prioritet" in c), None)
        self.assertIn("5 dagar", priority_change)
        self.assertIn("10 dagar", priority_change)
        self.assertIn("→", priority_change)

    def test_many2one_field_change_formatting(self):
        """Test Many2one field change formatting with various scenarios"""
        request = self._create_maintenance_request()

        # Test assignment from empty
        change = self.change_tracker._format_field_change(
            request._fields["user_id"], False, self.internal_user.id, "User"
        )
        self.assertIn("Inte valt", change)
        self.assertIn(self.internal_user.display_name, change)
        self.assertIn("→", change)

        # Test no change (should return None)
        no_change = self.change_tracker._format_field_change(
            request._fields["user_id"],
            self.internal_user,
            self.internal_user.id,
            "User",
        )
        self.assertIsNone(no_change)

        # Test unassignment
        change = self.change_tracker._format_field_change(
            request._fields["user_id"], self.internal_user, False, "User"
        )
        self.assertIn(self.internal_user.display_name, change)
        self.assertIn("Inte valt", change)
        self.assertIn("→", change)

    def test_selection_field_change_formatting(self):
        """Test Selection field change formatting"""
        request = self._create_maintenance_request()

        # Test priority change
        change = self.change_tracker._format_field_change(
            request._fields["priority_expanded"], "5", "10", "Priority"
        )
        self.assertIn("5 dagar", change)
        self.assertIn("10 dagar", change)
        self.assertIn("→", change)

        # Test from empty
        change = self.change_tracker._format_field_change(
            request._fields["priority_expanded"], False, "7", "Priority"
        )
        self.assertIn("Inte satt", change)
        self.assertIn("7 dagar", change)

    def test_date_field_change_formatting(self):
        """Test Date field change formatting with edge cases"""
        request = self._create_maintenance_request()
        field_obj = request._fields["start_date"]

        # Test normal date change
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), date(2023, 2, 20), "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("2023-02-20", change)
        self.assertIn("→", change)

        # Test string date input
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), "2023-02-20", "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("2023-02-20", change)

        # Test empty to date
        change = self.change_tracker._format_field_change(
            field_obj, False, date(2023, 2, 20), "Start Date"
        )
        self.assertIn("Inte satt", change)
        self.assertIn("2023-02-20", change)

        # Test invalid string handling
        change = self.change_tracker._format_field_change(
            field_obj, date(2023, 1, 15), "invalid-date", "Start Date"
        )
        self.assertIn("2023-01-15", change)
        self.assertIn("invalid-date", change)

    def test_change_notification_posting(self):
        """Test that change notifications are properly posted as messages"""
        request = self._create_maintenance_request(description="Initial description")

        # Count messages before update
        initial_count = len(request.message_ids)

        # Update with change tracking enabled (clear creating_records context)
        request.with_context(creating_records=False).write(
            {"description": "Updated description", "priority_expanded": "7"}
        )

        # Refresh to get latest messages
        request.invalidate_recordset()

        # Should have posted a notification message
        self.assertGreater(len(request.message_ids), initial_count)

        # Check the latest message
        latest_message = request.message_ids.sorted("id", reverse=True)[0]
        self.assertEqual(latest_message.message_type, "notification")
        self.assertIn("Description", latest_message.body)
        self.assertIn("Prioritet", latest_message.body)

    def test_no_notification_when_no_tracked_changes(self):
        """Test that no notification is posted when only excluded fields change"""
        request = self._create_maintenance_request()

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
        request1 = self._create_maintenance_request(description="Request 1")
        request2 = self._create_maintenance_request(description="Request 2")

        requests = request1 | request2

        # Update both records
        changes = self.change_tracker.track_field_changes(requests, {"priority_expanded": "7"})

        # Should track changes for both records
        self.assertIn(request1.id, changes)
        self.assertIn(request2.id, changes)
        self.assertEqual(len(changes[request1.id]), 1)
        self.assertEqual(len(changes[request2.id]), 1)


@tagged("onecore")
class TestMaintenanceRequestFormState(MaintenanceRequestTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_faker()

        self.property = self.env["maintenance.property"].create(
            {
                "designation": self.fake.property_designation(),
                "code": self.fake.property_code(),
            }
        )

        self.property_option = self.env["maintenance.property.option"].create(
            {
                "designation": self.fake.property_designation(),
                "code": self.fake.property_code(),
            }
        )

        self.building = self.env["maintenance.building"].create(
            {"name": self.fake.building_name(), "code": self.fake.building_code()}
        )

        self.building_option = self.env["maintenance.building.option"].create(
            {"name": self.fake.building_name(), "code": self.fake.building_code()}
        )

    def test_form_state_parking_space(self):
        """Form state should be 'parking-space' when space_caption is 'Bilplats'"""
        request = self._create_maintenance_request(space_caption="Bilplats")
        self.assertEqual(request.form_state, "parking-space")

    def test_form_state_property_with_property_id(self):
        """Form state should be 'property' when space_caption is 'Fastighet' and property_id is set"""
        request = self._create_maintenance_request(
            space_caption="Fastighet", property_id=self.property.id
        )
        self.assertEqual(request.form_state, "property")

    def test_form_state_property_with_property_option_id(self):
        """Form state should be 'property' when space_caption is 'Fastighet' and property_option_id is set"""
        request = self._create_maintenance_request(
            space_caption="Fastighet", property_option_id=self.property_option.id
        )
        self.assertEqual(request.form_state, "property")

    def test_form_state_property_without_property_fields(self):
        """Form state should not be 'property' when space_caption is 'Fastighet' but no property fields are set"""
        request = self._create_maintenance_request(space_caption="Fastighet")
        self.assertNotEqual(request.form_state, "property")
        self.assertEqual(request.form_state, "rental-property")  # Should fallback

    def test_form_state_building_with_building_id(self):
        """Form state should be 'building' when space_caption is building-related and building_id is set"""
        building_space_captions = ["Byggnad", "Uppgång", "Vind", "Källare", "Cykelförråd", "Gården/Utomhus", "Övrigt"]

        for space_caption in building_space_captions:
            with self.subTest(space_caption=space_caption):
                request = self._create_maintenance_request(
                    space_caption=space_caption, building_id=self.building.id
                )
                self.assertEqual(request.form_state, "building")

    def test_form_state_building_with_building_option_id(self):
        """Form state should be 'building' when space_caption is building-related and building_option_id is set"""
        request = self._create_maintenance_request(
            space_caption="Byggnad", building_option_id=self.building_option.id
        )
        self.assertEqual(request.form_state, "building")

    def test_form_state_building_without_building_fields(self):
        """Form state should not be 'building' when space_caption is building-related but no building fields are set"""
        request = self._create_maintenance_request(space_caption="Byggnad")
        self.assertNotEqual(request.form_state, "building")
        self.assertEqual(request.form_state, "rental-property")  # Should fallback

    def test_form_state_maintenance_unit(self):
        """Form state should be 'maintenance-unit' for maintenance unit space captions"""
        maintenance_unit_captions = ["Tvättstuga", "Miljöbod", "Lekplats"]

        for space_caption in maintenance_unit_captions:
            with self.subTest(space_caption=space_caption):
                request = self._create_maintenance_request(space_caption=space_caption)
                self.assertEqual(request.form_state, "maintenance-unit")

    def test_form_state_rental_property(self):
        """Form state should be 'rental-property' for rental property space captions"""
        rental_property_captions = ["Lägenhet", "Lokal"]

        for space_caption in rental_property_captions:
            with self.subTest(space_caption=space_caption):
                request = self._create_maintenance_request(space_caption=space_caption)
                self.assertEqual(request.form_state, "rental-property")

    def test_form_state_fallback(self):
        """Form state should default to 'rental-property' when no specific conditions are met"""
        # Test a space_caption that exists but doesn't have special handling in form state logic
        # From the form state logic, any space_caption not explicitly handled should fallback to "rental-property"
        request = self._create_maintenance_request(space_caption="Lägenhet")
        self.assertEqual(request.form_state, "rental-property")

        # Test another case - space_caption that would be "building" but without building fields
        request_no_building = self._create_maintenance_request(space_caption="Övrigt")
        self.assertEqual(request_no_building.form_state, "rental-property")


@tagged("onecore")
class TestMaintenanceRequestUtilityMethods(
    MaintenanceRequestTestMixin, UserTestMixin, TransactionCase
):
    def setUp(self):
        super().setUp()
        self.internal_user = self._create_internal_user()

        from ...models.services import FieldChangeTracker
        from ...models.utils.helpers import get_tenant_name, get_main_phone_number
        self.change_tracker = FieldChangeTracker(self.env)
        self.get_tenant_name = get_tenant_name
        self.get_main_phone_number = get_main_phone_number

    def test_get_tenant_name_with_first_last_name(self):
        """_get_tenant_name should construct name from firstName and lastName"""
        self._setup_faker()

        first_name = self.fake.first_name()
        last_name = self.fake.last_name()
        full_name = self.fake.tenant_full_name()

        tenant_data = {
            "firstName": first_name,
            "lastName": last_name,
            "fullName": full_name,
        }

        name = self.get_tenant_name(tenant_data)
        self.assertEqual(name, f"{first_name} {last_name}")

    def test_get_tenant_name_with_full_name_only(self):
        """_get_tenant_name should use fullName when firstName/lastName not available"""
        self._setup_faker()

        full_name = self.fake.tenant_full_name()
        tenant_data = {"fullName": full_name}

        name = self.get_tenant_name(tenant_data)
        self.assertEqual(name, full_name)

    def test_get_tenant_name_with_empty_data(self):
        """_get_tenant_name should return empty string for empty data"""
        tenant_data = {}

        name = self.get_tenant_name(tenant_data)
        self.assertEqual(name, "")

    def test_get_main_phone_number_finds_main_number(self):
        """_get_main_phone_number should find the phone number marked as main"""
        self._setup_faker()

        phone1 = self.fake.phone_number()
        phone2 = self.fake.phone_number()
        phone3 = self.fake.phone_number()

        tenant_data = {
            "phoneNumbers": [
                {"phoneNumber": phone1, "isMainNumber": 0},
                {"phoneNumber": phone2, "isMainNumber": 1},
                {"phoneNumber": phone3, "isMainNumber": 0},
            ]
        }

        phone = self.get_main_phone_number(tenant_data)
        self.assertEqual(phone, phone2)

    def test_get_main_phone_number_no_main_number(self):
        """_get_main_phone_number should return None when no main number exists"""
        self._setup_faker()

        phone1 = self.fake.phone_number()
        phone2 = self.fake.phone_number()

        tenant_data = {
            "phoneNumbers": [
                {"phoneNumber": phone1, "isMainNumber": 0},
                {"phoneNumber": phone2, "isMainNumber": 0},
            ]
        }

        phone = self.get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_get_main_phone_number_empty_phone_numbers(self):
        """_get_main_phone_number should return None for empty phoneNumbers"""
        tenant_data = {"phoneNumbers": []}

        phone = self.get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_get_main_phone_number_no_phone_numbers_key(self):
        """_get_main_phone_number should return None when phoneNumbers key missing"""
        tenant_data = {}

        phone = self.get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_maintenance_team_domain_computation(self):
        """_compute_maintenance_team_domain should set correct user domain"""
        self._setup_faker()

        # Create maintenance team with specific members
        team_name = self.fake.company()
        team = self.env["maintenance.team"].create(
            {"name": team_name, "member_ids": [(6, 0, [self.internal_user.id])]}
        )

        request = self._create_maintenance_request(maintenance_team_id=team.id)

        # Should have correct domain
        expected_domain = [("id", "in", [self.internal_user.id])]
        self.assertEqual(request.maintenance_team_domain, expected_domain)


# @tagged("onecore")
# class TestMaintenanceRequestContractUpdating(
#     MaintenanceRequestTestMixin, TransactionCase
# ):
#     def setUp(self):
#         super().setUp()
#         self._setup_faker()

#         # Create rental property without lease/contract
#         self.rental_property = self.env["maintenance.rental.property"].create(
#             {
#                 "name": self.fake.rental_property_name(),
#                 "address": self.fake.address(),
#                 "code": self.fake.rental_property_code(),
#                 "property_type": "Apartment",
#             }
#         )

#     def test_request_without_contract_gets_updated_with_new_lease_data(self):
#         """Requests without contracts should be updated when new lease data is found"""
#         # Create request with rental property but no lease/contract
#         request = self._create_maintenance_request(
#             rental_property_id=self.rental_property.id
#         )

#         # Initially should have no lease
#         self.assertFalse(request.lease_id)
#         self.assertFalse(request.recently_added_tenant)
#         self.assertTrue(request.empty_tenant)  # Should be flagged as empty

#         # Generate fake lease and tenant data
#         lease_id = self.fake.lease_id()
#         lease_number = self.fake.lease_number()
#         lease_type = self.fake.lease_type()
#         start_date = self.fake.date_between(start_date="-1y", end_date="today")
#         end_date = self.fake.date_between(start_date="today", end_date="+1y")
#         contract_date = self.fake.date_between(start_date="-2y", end_date="-1y")
#         approval_date = self.fake.date_between_dates(
#             date_start=contract_date, date_end=start_date
#         )

#         tenant_contact_code = self.fake.contact_code()
#         tenant_first_name = self.fake.first_name()
#         tenant_last_name = self.fake.last_name()
#         tenant_phone = self.fake.phone_number()
#         tenant_email = self.fake.email()

#         # Mock the API response with new lease data
#         mock_property_data = {
#             "leases": [
#                 {
#                     "leaseId": lease_id,
#                     "leaseNumber": lease_number,
#                     "type": lease_type,
#                     "leaseStartDate": start_date.isoformat(),
#                     "lastDebitDate": end_date.isoformat(),
#                     "contractDate": contract_date.isoformat(),
#                     "approvalDate": approval_date.isoformat(),
#                     "tenants": [
#                         {
#                             "contactCode": tenant_contact_code,
#                             "firstName": tenant_first_name,
#                             "lastName": tenant_last_name,
#                             "phoneNumbers": [
#                                 {"phoneNumber": tenant_phone, "isMainNumber": 1}
#                             ],
#                             "emailAddress": tenant_email,
#                         }
#                     ],
#                 }
#             ]
#         }

#         # Mock the fetch_property_data method to return our test data
#         with self.patch_fetch_property_data(mock_property_data):
#             # Trigger the compute method that updates contracts
#             request._compute_empty_tenant()

#         # Should now have lease data
#         self.assertTrue(request.lease_id)
#         self.assertEqual(request.lease_id.lease_number, lease_number)
#         self.assertEqual(request.lease_id.lease_type, lease_type)

#         # Should have tenant data
#         self.assertTrue(request.tenant_id)
#         self.assertEqual(
#             request.tenant_id.name, f"{tenant_first_name} {tenant_last_name}"
#         )
#         self.assertEqual(request.tenant_id.contact_code, tenant_contact_code)
#         self.assertEqual(request.tenant_id.phone_number, tenant_phone)

#         # Should be flagged as recently updated
#         self.assertTrue(request.recently_added_tenant)
#         self.assertFalse(request.empty_tenant)

#     def test_request_with_existing_contract_not_updated(self):
#         """Requests that already have contracts should not be updated"""
#         # Generate fake existing lease data
#         existing_lease_id = self.fake.lease_id()
#         existing_lease_number = self.fake.lease_number()
#         existing_lease_type = self.fake.lease_type()

#         # Create lease first
#         existing_lease = self.env["maintenance.lease"].create(
#             {
#                 "lease_id": existing_lease_id,
#                 "name": existing_lease_id,
#                 "lease_number": existing_lease_number,
#                 "lease_type": existing_lease_type,
#             }
#         )

#         # Create request with existing lease
#         request = self._create_maintenance_request(
#             rental_property_id=self.rental_property.id, lease_id=existing_lease.id
#         )

#         # Should not be empty tenant since it has a lease
#         self.assertFalse(request.empty_tenant)
#         self.assertFalse(request.recently_added_tenant)

#         # Generate fake new lease data (different from existing)
#         new_lease_id = self.fake.lease_id()
#         new_lease_number = self.fake.lease_number()
#         new_lease_type = self.fake.lease_type()

#         # Mock API with different lease data
#         mock_property_data = {
#             "leases": [
#                 {
#                     "leaseId": new_lease_id,
#                     "leaseNumber": new_lease_number,
#                     "type": new_lease_type,
#                     "tenants": [],
#                 }
#             ]
#         }

#         with self.patch_fetch_property_data(mock_property_data):
#             request._compute_empty_tenant()

#         # Should still have original lease (not updated)
#         self.assertEqual(request.lease_id.lease_number, existing_lease_number)
#         self.assertEqual(request.lease_id.lease_type, existing_lease_type)
#         self.assertFalse(request.recently_added_tenant)

#     def test_request_without_rental_property_not_updated(self):
#         """Requests without rental property should not trigger contract updating"""
#         # Create request without rental property
#         request = self._create_maintenance_request()

#         self.assertFalse(request.rental_property_id)
#         self.assertFalse(request.lease_id)

#         # Trigger compute - should not attempt API call
#         request._compute_empty_tenant()

#         # Should remain unchanged
#         self.assertFalse(request.lease_id)
#         self.assertFalse(request.recently_added_tenant)

#     def test_api_response_with_no_leases_handled_gracefully(self):
#         """API responses with no lease data should be handled gracefully"""
#         request = self._create_maintenance_request(
#             rental_property_id=self.rental_property.id
#         )

#         # Mock API response with no leases
#         mock_property_data = {"leases": []}

#         with self.patch_fetch_property_data(mock_property_data):
#             request._compute_empty_tenant()

#         # Should remain unchanged
#         self.assertFalse(request.lease_id)
#         self.assertFalse(request.recently_added_tenant)
#         self.assertTrue(request.empty_tenant)

#     def test_api_response_with_multiple_leases_uses_first_lease(self):
#         """When multiple leases are returned, should use the first one"""
#         request = self._create_maintenance_request(
#             rental_property_id=self.rental_property.id
#         )

#         # Generate fake data for multiple leases
#         first_lease_id = self.fake.lease_id()
#         first_lease_number = self.fake.lease_number()
#         first_lease_type = self.fake.lease_type()

#         second_lease_id = self.fake.lease_id()
#         second_lease_number = self.fake.lease_number()
#         second_lease_type = self.fake.lease_type()

#         # Mock API response with multiple leases
#         mock_property_data = {
#             "leases": [
#                 {
#                     "leaseId": first_lease_id,
#                     "leaseNumber": first_lease_number,
#                     "type": first_lease_type,
#                     "tenants": [],
#                 },
#                 {
#                     "leaseId": second_lease_id,
#                     "leaseNumber": second_lease_number,
#                     "type": second_lease_type,
#                     "tenants": [],
#                 },
#             ]
#         }

#         with self.patch_fetch_property_data(mock_property_data):
#             request._compute_empty_tenant()

#         # Should use the first lease
#         self.assertTrue(request.lease_id)
#         self.assertEqual(request.lease_id.lease_number, first_lease_number)
#         self.assertEqual(request.lease_id.lease_type, first_lease_type)
#         self.assertTrue(request.recently_added_tenant)

#     def patch_fetch_property_data(self, mock_data):
#         """Context manager to mock the fetch_property_data method"""
#         import unittest.mock

#         return unittest.mock.patch.object(
#             self.env["maintenance.request"],
#             "fetch_property_data",
#             return_value=mock_data,
#         )
