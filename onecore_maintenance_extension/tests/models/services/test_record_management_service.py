from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...utils.test_utils import (
    setup_faker,
    create_maintenance_request,
    create_property_option,
    create_building_option,
    create_rental_property_option,
    create_parking_space_option,
    create_facility_option,
    create_tenant_option,
    create_lease_option,
)

CORE_API_PATH = "odoo.addons.onecore_api.core_api.CoreApi"


def _lease_payload(tenants, lease_id="216-034-03-0101/01"):
    return {
        "leaseId": lease_id,
        "leaseNumber": lease_id.split("/")[-1],
        "type": "Bostadskontrakt",
        "leaseStartDate": "1977-06-01",
        "lastDebitDate": False,
        "contractDate": "1977-05-01",
        "approvalDate": "1977-05-15",
        "rentalPropertyId": "216-034-03-0101",
        "tenants": tenants,
    }


def _tenant_payload(contact_code="P005468", first="Sven", last="Olofsson"):
    return {
        "contactCode": contact_code,
        "contactKey": "K-" + contact_code,
        "firstName": first,
        "lastName": last,
        "nationalRegistrationNumber": "194903073015",
        "emailAddress": "t@example.com",
        "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
        "isTenant": True,
    }


@tagged("onecore")
class TestRecordManagementService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_save_property_option_to_permanent_record(self):
        """Creating request with property_option_id should create permanent property record"""
        property_option = create_property_option(self.env)

        request = create_maintenance_request(
            self.env, property_option_id=property_option.id
        )

        self.assertTrue(request.property_id)
        self.assertEqual(request.property_id.designation, property_option.designation)
        self.assertEqual(request.property_id.code, property_option.code)

    def test_save_building_option_to_permanent_record(self):
        """Creating request with building_option_id should create permanent building record"""
        building_option = create_building_option(self.env)

        request = create_maintenance_request(
            self.env, building_option_id=building_option.id
        )

        self.assertTrue(request.building_id)
        self.assertEqual(request.building_id.name, building_option.name)
        self.assertEqual(request.building_id.code, building_option.code)

    def test_save_rental_property_option_to_permanent_record(self):
        """Creating request with rental_property_option_id should create permanent rental property record"""
        rental_property_option = create_rental_property_option(self.env)

        request = create_maintenance_request(
            self.env, rental_property_option_id=rental_property_option.id
        )

        self.assertTrue(request.rental_property_id)
        self.assertEqual(
            request.rental_property_id.name, rental_property_option.name
        )
        self.assertEqual(
            request.rental_property_id.address, rental_property_option.address
        )
        self.assertEqual(request.rental_property_id.code, rental_property_option.code)

    def test_save_parking_space_option_to_permanent_record(self):
        """Creating request with parking_space_option_id should create permanent parking space record"""
        parking_space_option = create_parking_space_option(
            self.env, rental_id="705-022-04-0201"
        )

        request = create_maintenance_request(
            self.env,
            space_caption="Bilplats",
            parking_space_option_id=parking_space_option.id,
        )

        self.assertTrue(request.parking_space_id)
        self.assertEqual(request.parking_space_id.name, parking_space_option.name)
        self.assertEqual(request.parking_space_id.code, parking_space_option.code)

    def test_save_parking_space_persists_the_rental_id(self):
        """The flag syncs resolve the object through rental_property_id, and the
        option's name is a display name - so rental_id has to be carried over."""
        parking_space_option = create_parking_space_option(
            self.env, rental_id="705-022-04-0201"
        )

        request = create_maintenance_request(
            self.env,
            space_caption="Bilplats",
            parking_space_option_id=parking_space_option.id,
        )

        self.assertEqual(request.parking_space_id.rental_property_id, "705-022-04-0201")

    def test_save_facility_option_to_permanent_record(self):
        """Creating request with facility_option_id should create permanent facility record"""
        facility_option = create_facility_option(self.env, rental_id="705-022-04-0301")

        request = create_maintenance_request(
            self.env,
            space_caption="Lokal",
            facility_option_id=facility_option.id,
        )

        self.assertTrue(request.facility_id)
        self.assertEqual(request.facility_id.name, facility_option.name)
        self.assertEqual(request.facility_id.code, facility_option.code)

    def test_save_facility_persists_the_rental_id(self):
        """See test_save_parking_space_persists_the_rental_id."""
        facility_option = create_facility_option(self.env, rental_id="705-022-04-0301")

        request = create_maintenance_request(
            self.env,
            space_caption="Lokal",
            facility_option_id=facility_option.id,
        )

        self.assertEqual(request.facility_id.rental_property_id, "705-022-04-0301")

    def test_save_tenant_option_to_permanent_record(self):
        """Creating request with tenant_option_id should create permanent tenant record"""
        tenant_option = create_tenant_option(self.env)

        request = create_maintenance_request(
            self.env, tenant_option_id=tenant_option.id, hidden_from_my_pages=True
        )

        self.assertTrue(request.tenant_id)
        self.assertEqual(request.tenant_id.name, tenant_option.name)
        self.assertEqual(request.tenant_id.contact_code, tenant_option.contact_code)
        self.assertEqual(request.tenant_id.phone_number, tenant_option.phone_number)

    def test_save_tenant_option_persists_name_without_status_label(self):
        """The lease-status label is a dropdown-only decoration on display_name,
        so the persisted tenant name and SMS source stay free of it."""
        lease_option = create_lease_option(self.env, lease_status=0)  # "Gällande"
        tenant_option = create_tenant_option(
            self.env, name="David Lindblom", lease_option_id=lease_option.id
        )
        # The dropdown shows the status, but the stored name does not.
        self.assertEqual(tenant_option.display_name, "David Lindblom (Gällande)")

        request = create_maintenance_request(
            self.env, tenant_option_id=tenant_option.id, hidden_from_my_pages=True
        )

        self.assertEqual(request.tenant_id.name, "David Lindblom")
        self.assertEqual(request.tenant_name, "David Lindblom")

    def test_save_tenant_uses_form_phone_email_over_option_values(self):
        """When creating with modified phone/email in form, should use form values over option values"""
        new_phone = self.fake.phone_number()
        new_email = self.fake.email()

        tenant_option = create_tenant_option(self.env)

        # Simulate form modification by passing phone/email in vals
        request_vals = {
            "name": self.fake.maintenance_request_name(),
            "maintenance_request_category_id": self.env.ref(
                "onecore_maintenance_extension.category_1"
            ).id,
            "space_caption": self.fake.space_caption(),
            "priority_expanded": "7",
            "tenant_option_id": tenant_option.id,
            "phone_number": new_phone,
            "email_address": new_email,
            "hidden_from_my_pages": True,
        }

        request = self.env["maintenance.request"].create(request_vals)

        self.assertEqual(request.tenant_id.phone_number, new_phone)
        self.assertEqual(request.tenant_id.email_address, new_email)


@tagged("onecore")
class TestEmptyTenantAutoRefetchHidesFromMyPages(TransactionCase):
    """A request created on a vacant Lägenhet has no tenant. When OneCore
    later reports a lease for it, the passive on-read refetch
    (_compute_empty_tenant -> handle_empty_tenant_logic ->
    _create_missing_lease_and_tenant -> _create_tenant) back-fills a tenant.
    That new tenant must not gain visibility into a case raised before they
    lived there (MIM-1953)."""

    def test_newly_discovered_tenant_hides_request_from_my_pages(self):
        rental_property_option = create_rental_property_option(self.env)
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_option_id=rental_property_option.id,
        )
        self.assertFalse(request.lease_id)
        self.assertFalse(request.hidden_from_my_pages)

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_form_data.return_value = [
                {"lease": _lease_payload([_tenant_payload()])}
            ]
            request.invalidate_recordset()
            _ = request.empty_tenant  # triggers _compute_empty_tenant

        self.assertTrue(request.lease_id)
        self.assertTrue(request.tenant_id)
        self.assertTrue(request.recently_added_tenant)
        self.assertTrue(request.hidden_from_my_pages)
