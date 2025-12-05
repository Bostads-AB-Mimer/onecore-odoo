from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...test_utils import (
    setup_faker,
    create_maintenance_request,
    create_property_option,
    create_building_option,
    create_rental_property_option,
    create_tenant_option,
)


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
            "tenant_option_id": tenant_option.id,
            "phone_number": new_phone,
            "email_address": new_email,
            "hidden_from_my_pages": True,
        }

        request = self.env["maintenance.request"].create(request_vals)

        self.assertEqual(request.tenant_id.phone_number, new_phone)
        self.assertEqual(request.tenant_id.email_address, new_email)
