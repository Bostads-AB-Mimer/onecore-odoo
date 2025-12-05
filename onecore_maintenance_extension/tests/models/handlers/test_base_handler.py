# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo import exceptions
from unittest.mock import Mock

from ...test_utils import (
    setup_faker,
    create_test_user,
    create_maintenance_request,
    create_property_option,
    create_building_option,
    create_staircase_option,
    create_rental_property_option,
    create_parking_space_option,
    create_facility_option,
)
from ....models.handlers.base_handler import BaseMaintenanceHandler


@tagged("onecore")
class TestBaseMaintenanceHandler(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

        # Create a real maintenance request
        self.maintenance_request = create_maintenance_request(self.env)

        # Core API can still be mocked as it's an external dependency
        self.core_api = Mock()
        self.handler = BaseMaintenanceHandler(
            self.maintenance_request, self.core_api
        )

    def test_initialization(self):
        """Test that handler initializes with correct attributes."""
        self.assertEqual(self.handler.record, self.maintenance_request)
        self.assertEqual(self.handler.env, self.maintenance_request.env)
        self.assertEqual(self.handler.core_api, self.core_api)

    def test_handle_search_not_implemented(self):
        """Test that handle_search raises NotImplementedError."""
        with self.assertRaises(NotImplementedError) as context:
            self.handler.handle_search("pnr", self.fake.pystr(), "Lägenhet")

        self.assertIn(
            "Subclasses must implement handle_search method",
            str(context.exception),
        )

    def test_update_form_options_not_implemented(self):
        """Test that update_form_options raises NotImplementedError."""
        with self.assertRaises(NotImplementedError) as context:
            self.handler.update_form_options({})

        self.assertIn(
            "Subclasses must implement update_form_options method",
            str(context.exception),
        )

    def test_delete_options(self):
        """Test that _delete_options deletes all user options."""
        # Create test data
        property_option = create_property_option(self.env)
        building_option = create_building_option(self.env)
        staircase_option = create_staircase_option(self.env)

        # Verify records exist
        self.assertTrue(property_option.exists())
        self.assertTrue(building_option.exists())
        self.assertTrue(staircase_option.exists())

        # Call delete options
        self.handler._delete_options()

        # Verify all records are deleted
        self.assertFalse(property_option.exists())
        self.assertFalse(building_option.exists())
        self.assertFalse(staircase_option.exists())

    def test_delete_options_only_deletes_current_user(self):
        """Test that _delete_options only deletes current user's options."""
        # Create options for current user
        property_option_current = create_property_option(self.env)

        # Create a different user and their options
        other_user = create_test_user(self.env)
        property_option_other = create_property_option(
            self.env, user_id=other_user.id
        )

        # Call delete options
        self.handler._delete_options()

        # Verify only current user's options are deleted
        self.assertFalse(property_option_current.exists())
        self.assertTrue(property_option_other.exists())

        # Cleanup
        property_option_other.unlink()
        other_user.unlink()

    def test_create_lease_option_with_rental_property(self):
        """Test creating a lease option with rental property association."""
        # Create a rental property option first
        rental_property_option = create_rental_property_option(self.env)

        lease_data = {
            "leaseId": self.fake.lease_id(),
            "leaseNumber": self.fake.lease_number(),
            "type": self.fake.lease_type(),
            "leaseStartDate": self.fake.date(),
            "lastDebitDate": self.fake.date(),
            "contractDate": self.fake.date(),
            "approvalDate": self.fake.date(),
        }

        lease_option = self.handler._create_lease_option(
            lease_data, rental_property_option_id=rental_property_option.id
        )

        self.assertEqual(lease_option.name, lease_data["leaseId"])
        self.assertEqual(lease_option.lease_number, lease_data["leaseNumber"])
        self.assertEqual(lease_option.lease_type, lease_data["type"])
        self.assertEqual(lease_option.rental_property_option_id.id, rental_property_option.id)
        self.assertEqual(lease_option.user_id, self.env.user)

    def test_create_lease_option_with_parking_space(self):
        """Test creating a lease option with parking space association."""
        # Create a parking space option first
        parking_space_option = create_parking_space_option(self.env)

        lease_data = {
            "leaseId": self.fake.lease_id(),
            "leaseNumber": self.fake.lease_number(),
            "type": self.fake.lease_type(),
            "leaseStartDate": self.fake.date(),
            "lastDebitDate": self.fake.date(),
            "contractDate": self.fake.date(),
            "approvalDate": self.fake.date(),
        }

        lease_option = self.handler._create_lease_option(
            lease_data, parking_space_option_id=parking_space_option.id
        )

        self.assertEqual(lease_option.parking_space_option_id.id, parking_space_option.id)
        self.assertFalse(lease_option.rental_property_option_id)
        self.assertFalse(lease_option.facility_option_id)

    def test_create_lease_option_with_facility(self):
        """Test creating a lease option with facility association."""
        # Create a facility option first
        facility_option = create_facility_option(self.env)

        lease_data = {
            "leaseId": self.fake.lease_id(),
            "leaseNumber": self.fake.lease_number(),
            "type": self.fake.lease_type(),
            "leaseStartDate": self.fake.date(),
            "lastDebitDate": self.fake.date(),
            "contractDate": self.fake.date(),
            "approvalDate": self.fake.date(),
        }

        lease_option = self.handler._create_lease_option(
            lease_data, facility_option_id=facility_option.id
        )

        self.assertEqual(lease_option.facility_option_id.id, facility_option.id)
        self.assertFalse(lease_option.rental_property_option_id)
        self.assertFalse(lease_option.parking_space_option_id)

    def test_create_tenant_options_creates_new_tenant(self):
        """Test creating tenant options for new tenants."""
        tenants = [
            {
                "contactCode": self.fake.contact_code(),
                "contactKey": self.fake.contact_key(),
                "firstName": self.fake.first_name(),
                "lastName": self.fake.last_name(),
                "nationalRegistrationNumber": self.fake.ssn(),
                "emailAddress": self.fake.email(),
                "phoneNumbers": [
                    {"phoneNumber": self.fake.phone_number(), "isMainNumber": 1}
                ],
                "isTenant": True,
                "specialAttention": self.fake.text(max_nb_chars=50),
            }
        ]

        self.handler._create_tenant_options(tenants)

        tenant_option = self.env["maintenance.tenant.option"].search(
            [("contact_code", "=", tenants[0]["contactCode"])]
        )

        self.assertTrue(tenant_option.exists())
        expected_name = f"{tenants[0]['firstName']} {tenants[0]['lastName']}"
        self.assertEqual(tenant_option.name, expected_name)
        self.assertEqual(tenant_option.contact_code, tenants[0]["contactCode"])
        self.assertEqual(tenant_option.email_address, tenants[0]["emailAddress"])
        self.assertEqual(tenant_option.phone_number, tenants[0]["phoneNumbers"][0]["phoneNumber"])
        self.assertTrue(tenant_option.is_tenant)

    def test_create_tenant_options_skips_existing_tenant(self):
        """Test that existing tenants are not duplicated."""
        contact_code = self.fake.contact_code()

        # Create an existing tenant
        existing_tenant = self.env["maintenance.tenant.option"].create(
            {
                "user_id": self.env.user.id,
                "name": self.fake.name(),
                "contact_code": contact_code,
                "contact_key": self.fake.contact_key(),
                "is_tenant": True,
            }
        )

        tenants = [
            {
                "contactCode": contact_code,
                "contactKey": self.fake.contact_key(),
                "firstName": self.fake.first_name(),
                "lastName": self.fake.last_name(),
                "isTenant": True,
            }
        ]

        # Get count before
        tenant_count_before = self.env["maintenance.tenant.option"].search_count(
            [("contact_code", "=", contact_code)]
        )

        self.handler._create_tenant_options(tenants)

        # Get count after
        tenant_count_after = self.env["maintenance.tenant.option"].search_count(
            [("contact_code", "=", contact_code)]
        )

        # Verify no duplicate was created
        self.assertEqual(tenant_count_before, tenant_count_after)

    def test_create_tenant_options_with_full_name(self):
        """Test creating tenant options when only fullName is provided."""
        full_name = self.fake.name()
        contact_code = self.fake.contact_code()

        tenants = [
            {
                "contactCode": contact_code,
                "contactKey": self.fake.contact_key(),
                "fullName": full_name,
                "phoneNumbers": [],
                "isTenant": True,
            }
        ]

        self.handler._create_tenant_options(tenants)

        tenant_option = self.env["maintenance.tenant.option"].search(
            [("contact_code", "=", contact_code)]
        )

        self.assertTrue(tenant_option.exists())
        self.assertEqual(tenant_option.name, full_name)

    def test_create_tenant_options_without_phone_number(self):
        """Test creating tenant options when no main phone number exists."""
        contact_code = self.fake.contact_code()

        tenants = [
            {
                "contactCode": contact_code,
                "contactKey": self.fake.contact_key(),
                "firstName": self.fake.first_name(),
                "lastName": self.fake.last_name(),
                "phoneNumbers": [
                    {"phoneNumber": self.fake.phone_number(), "isMainNumber": 0}
                ],
                "isTenant": True,
            }
        ]

        self.handler._create_tenant_options(tenants)

        tenant_option = self.env["maintenance.tenant.option"].search(
            [("contact_code", "=", contact_code)]
        )

        self.assertTrue(tenant_option.exists())
        self.assertFalse(tenant_option.phone_number)

    def test_create_tenant_options_multiple_tenants(self):
        """Test creating options for multiple tenants at once."""
        contact_code_1 = self.fake.contact_code()
        contact_code_2 = self.fake.contact_code()
        first_name_1 = self.fake.first_name()
        last_name_1 = self.fake.last_name()
        first_name_2 = self.fake.first_name()
        last_name_2 = self.fake.last_name()

        tenants = [
            {
                "contactCode": contact_code_1,
                "contactKey": self.fake.contact_key(),
                "firstName": first_name_1,
                "lastName": last_name_1,
                "phoneNumbers": [],
                "isTenant": True,
            },
            {
                "contactCode": contact_code_2,
                "contactKey": self.fake.contact_key(),
                "firstName": first_name_2,
                "lastName": last_name_2,
                "phoneNumbers": [],
                "isTenant": True,
            },
        ]

        self.handler._create_tenant_options(tenants)

        tenant_one = self.env["maintenance.tenant.option"].search(
            [("contact_code", "=", contact_code_1)]
        )
        tenant_two = self.env["maintenance.tenant.option"].search(
            [("contact_code", "=", contact_code_2)]
        )

        self.assertTrue(tenant_one.exists())
        self.assertTrue(tenant_two.exists())
        self.assertEqual(tenant_one.name, f"{first_name_1} {last_name_1}")
        self.assertEqual(tenant_two.name, f"{first_name_2} {last_name_2}")

    def test_raise_no_results_error(self):
        """Test that _raise_no_results_error raises UserError with correct message."""
        search_value = self.fake.building_name()

        with self.assertRaises(exceptions.UserError) as context:
            self.handler._raise_no_results_error(search_value)

        # Check that the error message contains the search value
        self.assertIn(search_value, str(context.exception))

    def test_raise_no_results_error_with_different_values(self):
        """Test _raise_no_results_error with various search values."""
        test_values = [
            self.fake.building_code(),
            self.fake.property_code(),
            self.fake.lease_number(),
        ]

        for value in test_values:
            with self.assertRaises(exceptions.UserError) as context:
                self.handler._raise_no_results_error(value)

            self.assertIn(value, str(context.exception))

    def test_return_no_results_warning(self):
        """Test that _return_no_results_warning returns correct warning dict."""
        search_value = self.fake.building_name()

        result = self.handler._return_no_results_warning(search_value)

        self.assertIn("warning", result)
        self.assertIn("title", result["warning"])
        self.assertIn("message", result["warning"])
        self.assertIn(search_value, result["warning"]["message"])
