from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.services.direct_lookup_service import DirectLookupService
from ..utils.test_utils import create_maintenance_request

RESIDENCE = {
    "rentalInformation": {"rentalId": "123-456-789"},
    "name": "Testgatan 1",
    "code": "RES-001",
    "type": {"name": "Lägenhet"},
    "areaSize": 65,
    "entrance": "A",
    "accessibility": {"elevator": True},
    "property": {"code": "P-1", "name": "Fastigheten"},
    "building": {"code": "B-1", "name": "Byggnaden"},
}

CONTACT_LEASES = [
    {
        "leaseId": "406-028-02-0101/08",
        "leaseNumber": "08",
        "type": "Bostadskontrakt",
        "status": "Current",
        "leaseStartDate": "2024-10-01",
        "lastDebitDate": False,
        "contractDate": "2024-09-01",
        "approvalDate": "2024-09-15",
        "tenants": [
            {
                "contactCode": "P123456",
                "contactKey": "K1",
                "firstName": "Anna",
                "lastName": "Andersson",
                "nationalRegistrationNumber": "199001011234",
                "emailAddress": "anna@example.com",
                "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
                "isTenant": True,
                "specialAttention": False,
            }
        ]
    }
]


@tagged("onecore")
class TestCreateRentalObjectOption(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_residence_returns_option(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_residence.return_value = RESIDENCE

        option = self.service.create_rental_object_option(request, "123-456-789")

        self.core_api.fetch_residence.assert_called_once_with("123-456-789")
        self.assertTrue(option)
        self.assertEqual(option._name, "maintenance.rental.property.option")
        self.assertEqual(option.code, "RES-001")
        self.assertEqual(option.address, "Testgatan 1")
        self.assertEqual(option.building, "Byggnaden")

    def test_missing_residence_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_residence.return_value = None
        self.assertIsNone(self.service.create_rental_object_option(request, "000"))

    def test_non_rentalid_space_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Byggnad")
        self.assertIsNone(self.service.create_rental_object_option(request, "x"))
        self.core_api.fetch_residence.assert_not_called()


@tagged("onecore")
class TestCreateTenantOption(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_contact_code_returns_option(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_contact_leases.return_value = CONTACT_LEASES
        option = self.service.create_tenant_option(request, "P123456")
        self.core_api.fetch_contact_leases.assert_called_once_with("P123456")
        self.assertTrue(option)
        self.assertEqual(option._name, "maintenance.tenant.option")
        self.assertEqual(option.name, "Anna Andersson")
        self.assertEqual(option.contact_code, "P123456")
        self.assertEqual(option.phone_number, "0700000000")
        # The contact's active contract is linked so confirm can attach it.
        self.assertTrue(option.lease_option_id)
        self.assertEqual(option.lease_option_id.lease_type, "Bostadskontrakt")

    def test_unknown_contact_code_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_contact_leases.return_value = []
        self.assertIsNone(self.service.create_tenant_option(request, "P999999"))
