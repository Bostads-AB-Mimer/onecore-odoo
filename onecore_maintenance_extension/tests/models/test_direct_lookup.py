from unittest.mock import MagicMock, patch

import requests

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.handlers.rental_property_handler import RentalPropertyHandler
from ...models.services.direct_lookup_service import (
    DirectLookupService,
    LookupFailed,
)
from ..utils.test_utils import create_maintenance_request


def _http_error(status_code):
    """A requests.HTTPError as OneCore's client raises it (via raise_for_status)."""
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} error", response=response)


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


RES_LEASE = _lease("216-034-03-0101/01", "216-034-03-0101", "Bostadskontrakt", "P005468")
PARK_LEASE = _lease("216-704-00-0034/01", "216-704-00-0034", "P-Platskontrakt", "P005468")
RESIDENCE = _residence("216-034-03-0101", "RES-001")
PARKING = _parking("216-704-00-0034", "0034")


@tagged("onecore")
class TestLoadObjectContracts(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_returns_linked_object_lease_tenant(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE]
        self.core_api.fetch_residence.return_value = RESIDENCE

        result = self.service.load_object_contracts(request, "216-034-03-0101")

        # One lease call and one object call — the contract type tells us the kind.
        self.core_api.fetch_leases_unfiltered.assert_called_once_with(
            "rentalObjectId", "216-034-03-0101"
        )
        self.core_api.fetch_residence.assert_called_once_with("216-034-03-0101")
        self.core_api.fetch_parking_space.assert_not_called()
        self.core_api.fetch_facility.assert_not_called()
        leases = result["lease_options"]
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases.rental_property_option_id.code, "RES-001")
        tenant = self.env["maintenance.tenant.option"].search(
            [("lease_option_id", "=", leases.id)]
        )
        self.assertEqual(tenant.contact_code, "P005468")

    def test_object_fetched_once_for_several_contracts(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        upcoming = dict(RES_LEASE, leaseId="216-034-03-0101/02", status="Upcoming")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE, upcoming]
        self.core_api.fetch_residence.return_value = RESIDENCE

        result = self.service.load_object_contracts(request, "216-034-03-0101")

        self.assertEqual(len(result["lease_options"]), 2)
        self.core_api.fetch_residence.assert_called_once_with("216-034-03-0101")

    def test_vacant_object_returns_object_without_contract(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = []
        self.core_api.fetch_residence.return_value = RESIDENCE
        result = self.service.load_object_contracts(request, "216-034-03-0101")
        self.assertFalse(result["lease_options"])
        self.assertEqual(result["object_option"].code, "RES-001")

    def test_vacant_parking_object_resolves_after_residence_miss(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = []
        self.core_api.fetch_residence.side_effect = _http_error(404)
        self.core_api.fetch_parking_space.return_value = PARKING
        result = self.service.load_object_contracts(request, "216-704-00-0034")
        self.assertEqual(result["object_option"].code, "0034")

    def test_not_found_returns_none(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = []
        self.core_api.fetch_residence.return_value = None
        self.core_api.fetch_parking_space.return_value = None
        self.core_api.fetch_facility.return_value = None
        self.assertIsNone(self.service.load_object_contracts(request, "000"))

    def test_missing_object_is_reported_as_not_found(self):
        # OneCore answering 404 for every kind means "no such objektnummer".
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.side_effect = _http_error(404)
        self.core_api.fetch_residence.side_effect = _http_error(404)
        self.core_api.fetch_parking_space.side_effect = _http_error(404)
        self.core_api.fetch_facility.side_effect = _http_error(404)
        self.assertIsNone(self.service.load_object_contracts(request, "000"))

    def test_failed_lookup_raises_instead_of_reporting_not_found(self):
        # A broken call must NOT look like a wrong objektnummer.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.side_effect = _http_error(500)
        with self.assertRaises(LookupFailed):
            self.service.load_object_contracts(request, "216-034-03-0101")

    def test_failed_object_fetch_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = []
        self.core_api.fetch_residence.side_effect = requests.ConnectionError("boom")
        self.core_api.fetch_parking_space.side_effect = requests.ConnectionError("boom")
        self.core_api.fetch_facility.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(LookupFailed):
            self.service.load_object_contracts(request, "216-034-03-0101")

    def test_unusable_payload_raises_instead_of_500(self):
        # A contract whose object payload is missing fields must not blow up as an
        # unhandled error after the existing options have been deleted.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE]
        self.core_api.fetch_residence.return_value = {"code": "RES-001"}  # partial
        with self.assertRaises(LookupFailed):
            self.service.load_object_contracts(request, "216-034-03-0101")

    def test_payload_failing_at_the_db_leaves_the_transaction_usable(self):
        # The option fields are ``required=True``, which Odoo enforces as NOT NULL:
        # a partial payload therefore fails *after* the INSERT was issued, leaving
        # the transaction aborted. Swallowing that exception is not enough — every
        # later query would raise InFailedSqlTransaction instead of the plain
        # Swedish message the guard exists to produce.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE]
        self.core_api.fetch_residence.return_value = RESIDENCE

        def _create_without_required_fields(items):
            self.env["maintenance.rental.property.option"].create(
                {"user_id": self.env.uid}
            )

        with patch.object(
            RentalPropertyHandler,
            "update_form_options",
            side_effect=_create_without_required_fields,
        ):
            with self.assertRaises(LookupFailed):
                self.service.load_object_contracts(request, "216-034-03-0101")

        # Still usable: the caller has to be able to report the failure and go on.
        self.assertFalse(
            self.env["maintenance.lease.option"].search(
                [("user_id", "=", self.env.user.id)]
            )
        )

    def test_resolves_object_of_a_different_kind(self):
        # On a Lägenhet request, entering a parking objektnummer still resolves
        # (the contract type decides the kind, not the request's space type).
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [PARK_LEASE]
        self.core_api.fetch_parking_space.return_value = PARKING

        result = self.service.load_object_contracts(request, "216-704-00-0034")

        leases = result["lease_options"]
        self.assertEqual(len(leases), 1)
        self.assertTrue(leases.parking_space_option_id)
        self.core_api.fetch_residence.assert_not_called()


@tagged("onecore")
class TestLoadContactContracts(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_returns_all_contract_types(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE, PARK_LEASE]
        self.core_api.fetch_residence.return_value = RESIDENCE
        self.core_api.fetch_parking_space.return_value = PARKING

        result = self.service.load_contact_contracts(request, "P005468")

        self.core_api.fetch_leases_unfiltered.assert_called_once_with(
            "contactCode", "P005468"
        )
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
        self.core_api.fetch_leases_unfiltered.return_value = []
        self.assertIsNone(self.service.load_contact_contracts(request, "P000000"))

    def test_one_unreachable_object_still_offers_the_others(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.return_value = [RES_LEASE, PARK_LEASE]
        self.core_api.fetch_residence.return_value = RESIDENCE
        self.core_api.fetch_parking_space.side_effect = _http_error(500)

        result = self.service.load_contact_contracts(request, "P005468")

        self.assertEqual(len(result["lease_options"]), 1)
        self.assertTrue(result["lease_options"].rental_property_option_id)

    def test_failed_contact_lookup_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_leases_unfiltered.side_effect = _http_error(503)
        with self.assertRaises(LookupFailed):
            self.service.load_contact_contracts(request, "P005468")
