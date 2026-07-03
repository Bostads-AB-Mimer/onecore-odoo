from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.services.direct_lookup_service import DirectLookupService
from ..utils.test_utils import create_maintenance_request


def _residence(rental_id, code):
    return {
        "rentalInformation": {"rentalId": rental_id},
        "name": f"Gatan {code}",
        "code": code,
        "type": {"name": "4 rum och kök"},
        "areaSize": 96,
        "entrance": "03",
        "accessibility": {"elevator": False},
        "property": {"code": "P-1", "name": "Klädnypan 3"},
        "building": {"code": "B-1", "name": "Byggnaden"},
    }


def _parking(rental_id, code):
    return {
        "parkingSpace": {
            "name": f"P {code}",
            "code": code,
            "parkingSpaceType": {"name": "Parkeringsplats utan el", "code": "PP"},
            "parkingNumber": code,
        },
        "propertyCode": "P-1",
        "propertyName": "Klädnypan 3",
        "address": {
            "streetAddress": "Håkantorpsgatan 117",
            "postalCode": "72340",
            "city": "Västerås",
        },
    }


def _tenant(contact_code):
    return {
        "contactCode": contact_code,
        "contactKey": "K-" + contact_code,
        "firstName": "Sven",
        "lastName": "Olofsson",
        "nationalRegistrationNumber": "194903073015",
        "emailAddress": "sven@example.com",
        "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
        "isTenant": True,
        "specialAttention": False,
    }


def _lease(lease_id, rental_id, lease_type, contact_code):
    return {
        "leaseId": lease_id,
        "leaseNumber": lease_id.split("/")[-1],
        "type": lease_type,
        "status": "Current",
        "leaseStartDate": "1977-06-01",
        "lastDebitDate": False,
        "contractDate": "1977-05-01",
        "approvalDate": "1977-05-15",
        "rentalPropertyId": rental_id,
        "tenants": [_tenant(contact_code)],
    }


def _item(lease, residence=None, parking=None):
    return {
        "lease": lease,
        "rental_property": residence,
        "parking_space": parking,
        "facility": None,
        "maintenance_units": [],
    }


RES_LEASE = _lease("216-034-03-0101/01", "216-034-03-0101", "Bostadskontrakt", "P005468")
PARK_LEASE = _lease("216-704-00-0034/01", "216-704-00-0034", "P-Platskontrakt", "P005468")
WORK_ORDER = [_item(RES_LEASE, residence=_residence("216-034-03-0101", "RES-001"))]
VACANT = [_item(None, residence=_residence("216-034-03-0101", "RES-001"))]


@tagged("onecore")
class TestLoadObjectContracts(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_returns_linked_object_lease_tenant(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_form_data.return_value = WORK_ORDER

        result = self.service.load_object_contracts(request, "216-034-03-0101")

        self.core_api.fetch_form_data.assert_called_once_with(
            "rentalObjectId", "216-034-03-0101", "Lägenhet"
        )
        leases = result["lease_options"]
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases.rental_property_option_id.code, "RES-001")
        tenant = self.env["maintenance.tenant.option"].search(
            [("lease_option_id", "=", leases.id)]
        )
        self.assertEqual(tenant.contact_code, "P005468")

    def test_vacant_object_returns_object_without_contract(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_form_data.return_value = VACANT
        result = self.service.load_object_contracts(request, "216-034-03-0101")
        self.assertFalse(result["lease_options"])
        self.assertEqual(result["object_option"].code, "RES-001")

    def test_not_found_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_form_data.return_value = None
        self.assertIsNone(self.service.load_object_contracts(request, "000"))

    def test_resolves_object_of_a_different_kind(self):
        # On a Lägenhet request, entering a parking objektnummer still resolves
        # (the lookup probes object kinds, not the request's space type).
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        park_wo = [_item(PARK_LEASE, parking=_parking("216-704-00-0034", "0034"))]

        def fake(identifier, value, space):
            return park_wo if space == "Bilplats" else None

        self.core_api.fetch_form_data.side_effect = fake
        result = self.service.load_object_contracts(request, "216-704-00-0034")
        leases = result["lease_options"]
        self.assertEqual(len(leases), 1)
        self.assertTrue(leases.parking_space_option_id)


@tagged("onecore")
class TestLoadContactContracts(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_returns_all_contract_types(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_contact_leases.return_value = [RES_LEASE, PARK_LEASE]
        self.core_api.fetch_residence.return_value = _residence(
            "216-034-03-0101", "RES-001"
        )
        self.core_api.fetch_parking_space.return_value = _parking(
            "216-704-00-0034", "0034"
        )

        result = self.service.load_contact_contracts(request, "P005468")

        leases = result["lease_options"]
        self.assertEqual(len(leases), 2)
        # One contract is linked to a residence object, the other to a parking object.
        kinds = {
            bool(l.rental_property_option_id) and "residence"
            or bool(l.parking_space_option_id) and "parking"
            for l in leases
        }
        self.assertEqual(kinds, {"residence", "parking"})

    def test_unknown_contact_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_contact_leases.return_value = []
        self.assertIsNone(self.service.load_contact_contracts(request, "P000000"))
