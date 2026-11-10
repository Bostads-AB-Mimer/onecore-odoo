# -*- coding: utf-8 -*-
"""A contract number search returns the contract whatever its type. When the
chosen Utrymme holds another kind of object, the form warns and names the
right Utrymme instead of crashing or listing an empty object."""
from unittest.mock import Mock, patch

from odoo.addons.onecore_api import core_api
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import create_internal_user

ONCHANGE_LOGGER = "odoo.tests.form.onchange"


def _lease(rental_id, lease_type, lease_number="03"):
    return {
        "leaseId": f"{rental_id}/{lease_number}",
        "leaseNumber": lease_number,
        "rentalPropertyId": rental_id,
        "type": lease_type,
        "leaseStartDate": "2026-01-01",
        "status": "PreliminaryTerminated",
        "tenants": [
            {
                "contactCode": "P226686",
                "contactKey": "K-P226686",
                "firstName": "Maja",
                "lastName": "Lund",
                "nationalRegistrationNumber": "200001011234",
                "isTenant": True,
            }
        ],
    }


def _residence(rental_id):
    return {
        "code": rental_id[-4:],
        "name": f"Adress {rental_id}",
        "type": {"name": "Lägenhet"},
        "areaSize": 60,
        "entrance": "A",
        "accessibility": {"elevator": False},
        "property": {"code": "705", "name": "Fastighet"},
        "building": {"code": "705-010", "name": "Byggnad"},
        "rentalInformation": {"rentalId": rental_id},
    }


def _parking_space(rental_id):
    return {
        "parkingSpace": {
            "name": f"P {rental_id}",
            "code": rental_id[-4:],
            "parkingSpaceType": {"name": "Kallgarage med el", "code": "KG"},
            "parkingNumber": rental_id,
        },
        "propertyCode": "924",
        "propertyName": "Fastighet",
        "address": {"streetAddress": "Gatan 1", "postalCode": "72340", "city": "Västerås"},
    }


def _facility(rental_id):
    return {
        "name": f"Lokal {rental_id}",
        "code": rental_id[-4:],
        "type": {"name": "Butikslokal", "code": "BUTIK"},
        "area": 120,
        "building": {"code": "705-030", "name": "Byggnad"},
        "property": {"code": "705", "name": "Fastighet"},
        "rentalInformation": {"type": {"name": "Kommersiell lokal, moms"}},
    }


PARKING_ID = "924-715-00-0005"
RESIDENCE_ID = "705-010-04-0101"
FACILITY_ID = "705-030-00-0101"


def _parking_item():
    return core_api.build_form_item(
        _lease(PARKING_ID, "P-Platskontrakt"), "parking", _parking_space(PARKING_ID)
    )


def _residence_item():
    return core_api.build_form_item(
        _lease(RESIDENCE_ID, "Bostadskontrakt"), "residence", _residence(RESIDENCE_ID)
    )


def _facility_item():
    return core_api.build_form_item(
        _lease(FACILITY_ID, "Lokalkontrakt"), "facility", _facility(FACILITY_ID)
    )


@tagged("onecore")
class TestWrongSpaceContractSearch(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user_env = self.env(user=create_internal_user(self.env))

    def _search(self, space_caption, lease_id, work_order_data):
        """Search a contract number through the form, as the browser does."""
        Request = self.user_env["maintenance.request"]
        api = Mock()
        api.fetch_form_data.return_value = work_order_data
        with patch.object(type(Request), "get_core_api", return_value=api):
            form = Form(Request)
            form.name = "Test"
            form.space_caption = space_caption
            form.search_type = "leaseId"
            form.search_value = lease_id
        return form

    def _assert_wrong_space(self, space_caption, lease_id, item, expected_message):
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as logs:
            form = self._search(space_caption, lease_id, [item])
        self.assertEqual(logs.records[0].getMessage(), f"Fel utrymme {expected_message}")
        self.assertFalse(form.lease_option_id)
        self.assertFalse(form.tenant_option_id)
        self.assertFalse(form.rental_property_option_id)
        self.assertFalse(form.parking_space_option_id)
        self.assertFalse(form.facility_option_id)
        return form

    def test_parking_contract_under_lagenhet_names_bilplats(self):
        self._assert_wrong_space(
            "Lägenhet",
            f"{PARKING_ID}/03",
            _parking_item(),
            f"Kontrakt {PARKING_ID}/03 (P-Platskontrakt) hör till "
            "Utrymme Bilplats. Välj Bilplats och sök igen.",
        )

    def test_parking_contract_under_tvattstuga_names_bilplats(self):
        self._assert_wrong_space(
            "Tvättstuga",
            f"{PARKING_ID}/03",
            _parking_item(),
            f"Kontrakt {PARKING_ID}/03 (P-Platskontrakt) hör till "
            "Utrymme Bilplats. Välj Bilplats och sök igen.",
        )

    def test_parking_contract_under_byggnad_names_bilplats(self):
        self._assert_wrong_space(
            "Byggnad",
            f"{PARKING_ID}/03",
            _parking_item(),
            f"Kontrakt {PARKING_ID}/03 (P-Platskontrakt) hör till "
            "Utrymme Bilplats. Välj Bilplats och sök igen.",
        )

    def test_parking_contract_under_fastighet_names_bilplats(self):
        self._assert_wrong_space(
            "Fastighet",
            f"{PARKING_ID}/03",
            _parking_item(),
            f"Kontrakt {PARKING_ID}/03 (P-Platskontrakt) hör till "
            "Utrymme Bilplats. Välj Bilplats och sök igen.",
        )

    def test_residence_contract_under_bilplats_names_lagenhet(self):
        self._assert_wrong_space(
            "Bilplats",
            f"{RESIDENCE_ID}/03",
            _residence_item(),
            f"Kontrakt {RESIDENCE_ID}/03 (Bostadskontrakt) hör till "
            "Utrymme Lägenhet. Välj Lägenhet och sök igen.",
        )

    def test_facility_contract_under_bilplats_names_lokal(self):
        self._assert_wrong_space(
            "Bilplats",
            f"{FACILITY_ID}/03",
            _facility_item(),
            f"Kontrakt {FACILITY_ID}/03 (Lokalkontrakt) hör till "
            "Utrymme Lokal. Välj Lokal och sök igen.",
        )

    def test_parking_contract_under_lokal_names_bilplats(self):
        self._assert_wrong_space(
            "Lokal",
            f"{PARKING_ID}/03",
            _parking_item(),
            f"Kontrakt {PARKING_ID}/03 (P-Platskontrakt) hör till "
            "Utrymme Bilplats. Välj Bilplats och sök igen.",
        )

    def test_parking_contract_under_bilplats_fills_the_form(self):
        form = self._search("Bilplats", f"{PARKING_ID}/03", [_parking_item()])

        self.assertEqual(form.lease_option_id.lease_id, f"{PARKING_ID}/03")
        self.assertEqual(form.parking_space_option_id.rental_id, PARKING_ID)
        self.assertEqual(form.tenant_option_id.contact_code, "P226686")

    def test_residence_contract_under_lagenhet_fills_the_form(self):
        form = self._search("Lägenhet", f"{RESIDENCE_ID}/03", [_residence_item()])

        self.assertEqual(form.lease_option_id.lease_id, f"{RESIDENCE_ID}/03")
        self.assertEqual(form.rental_property_option_id.rental_id, RESIDENCE_ID)
        self.assertEqual(form.tenant_option_id.contact_code, "P226686")

    def test_facility_contract_under_lokal_fills_the_form(self):
        form = self._search("Lokal", f"{FACILITY_ID}/03", [_facility_item()])

        self.assertEqual(form.lease_option_id.lease_id, f"{FACILITY_ID}/03")
        self.assertEqual(form.facility_option_id.rental_id, FACILITY_ID)
        self.assertEqual(form.tenant_option_id.contact_code, "P226686")
