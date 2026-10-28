# -*- coding: utf-8 -*-
"""A customer with leases on several parking spaces or facilities: the search
preselects the active lease and its object, not the first object listed, and
the form's onchanges keep it that way."""
from unittest.mock import Mock, patch

from odoo.addons.onecore_api import core_api
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import create_internal_user


def _lease(rental_id, lease_id, lease_type, status):
    """A lease with its status by name and no lastDebitDate."""
    return {
        "leaseId": lease_id,
        "leaseNumber": lease_id.split("/")[-1],
        "rentalPropertyId": rental_id,
        "type": lease_type,
        "leaseStartDate": "2026-09-25",
        "status": status,
        "tenants": [
            {
                "contactCode": "P100001",
                "contactKey": "K-P100001",
                "firstName": "Maja",
                "lastName": "Lund",
                "nationalRegistrationNumber": "200001011234",
                "isTenant": True,
            }
        ],
    }


def _parking_space(rental_id):
    return {
        "parkingSpace": {
            "name": f"P {rental_id}",
            "code": rental_id[-4:],
            "parkingSpaceType": {"name": "Kallgarage med el", "code": "KG"},
            "parkingNumber": rental_id,
        },
        "propertyCode": "206",
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


@tagged("onecore")
class TestObjectFollowsActiveLease(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user_env = self.env(user=create_internal_user(self.env))

    def _search(self, space_caption, work_order_data):
        """Search a customer number through the form, as the browser does."""
        Request = self.user_env["maintenance.request"]
        api = Mock()
        api.fetch_form_data.return_value = work_order_data
        with patch.object(type(Request), "get_core_api", return_value=api):
            form = Form(Request)
            form.name = "Test"
            form.space_caption = space_caption
            form.search_type = "contactCode"
            form.search_value = "P100001"
        return form

    def test_parking_space_follows_the_active_lease(self):
        """Ej skickat listed first, Preliminärt uppsagt second: the
        preliminarily terminated lease and its parking space are preselected."""
        form = self._search(
            "Bilplats",
            [
                core_api.build_form_item(
                    _lease("406-932-00-0003", "406-932-00-0003/09", "P-Platskontrakt", "NotSent"),
                    "parking",
                    _parking_space("406-932-00-0003"),
                ),
                core_api.build_form_item(
                    _lease(
                        "206-703-00-0008", "206-703-00-0008/03",
                        "P-Platskontrakt", "PreliminaryTerminated",
                    ),
                    "parking",
                    _parking_space("206-703-00-0008"),
                ),
            ],
        )

        self.assertEqual(form.lease_option_id.lease_id, "206-703-00-0008/03")
        self.assertEqual(form.parking_space_option_id.rental_id, "206-703-00-0008")

    def test_facility_follows_the_active_lease(self):
        """Ej skickat listed first, Gällande second: the current lease and its
        facility are preselected."""
        form = self._search(
            "Lokal",
            [
                core_api.build_form_item(
                    _lease("705-030-00-0102", "705-030-00-0102/02", "Lokalkontrakt", "NotSent"),
                    "facility",
                    _facility("705-030-00-0102"),
                ),
                core_api.build_form_item(
                    _lease("705-030-00-0101", "705-030-00-0101/16", "Lokalkontrakt", "Current"),
                    "facility",
                    _facility("705-030-00-0101"),
                ),
            ],
        )

        self.assertEqual(form.lease_option_id.lease_id, "705-030-00-0101/16")
        self.assertEqual(form.facility_option_id.rental_id, "705-030-00-0101")
