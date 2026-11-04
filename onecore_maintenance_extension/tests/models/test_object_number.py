"""Tests for Objektsnummer: OneCore's rentalId shown on the form for a lokal
and bilplats, whose Kod is only the last part of it, and found by the search
view's Hyresobjekt field for a lägenhet, lokal and bilplats alike.

The domain is read from the search view's arch and filled in the way the web
client does (search_model.js _getFieldDomain: self is the typed text). Run as
an internal user: root is an external contractor in tests.
"""
from lxml import etree
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval

from ..utils.test_utils import (
    create_facility,
    create_internal_user,
    create_maintenance_request,
    create_parking_space,
    create_rental_property,
)

RESIDENCE_NUMBER = "705-022-04-0201"
FACILITY_NUMBER = "211-625-00-0003"
PARKING_NUMBER = "705-021-99-0003"


@tagged("onecore")
class TestObjectNumber(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user = create_internal_user(self.env)

        self.residence = self._request("Lägenhet")
        self.residence.write(
            {
                "rental_property_id": create_rental_property(
                    self.env,
                    maintenance_request_id=self.residence.id,
                    name=RESIDENCE_NUMBER,
                    rental_property_id=RESIDENCE_NUMBER,
                ).id
            }
        )
        self.facility = self._request("Lokal")
        self.facility.write(
            {
                "facility_id": create_facility(
                    self.env,
                    maintenance_request_id=self.facility.id,
                    code="0003",
                    type_name="Förråd",
                    rental_property_id=FACILITY_NUMBER,
                ).id
            }
        )
        self.parking = self._request("Bilplats")
        self.parking.write(
            {
                "parking_space_id": create_parking_space(
                    self.env,
                    maintenance_request_id=self.parking.id,
                    code="0003",
                    rental_property_id=PARKING_NUMBER,
                ).id
            }
        )
        # Saved before the create path copied the rentalId (1.0.118).
        self.old_facility = self._request("Lokal")
        self.old_facility.write(
            {
                "facility_id": create_facility(
                    self.env, maintenance_request_id=self.old_facility.id
                ).id
            }
        )
        self.no_object = self._request("Tvättstuga")

        self.requests = (
            self.residence
            | self.facility
            | self.parking
            | self.old_facility
            | self.no_object
        )

        arch = etree.fromstring(
            self.env["maintenance.request"]
            .with_user(self.user)
            .get_view(view_type="search")["arch"]
        )
        (self.field,) = arch.xpath("//field[@string='Hyresobjekt']")

    def _request(self, space_caption):
        created = create_maintenance_request(
            self.env(user=self.user), space_caption=space_caption
        )
        # Re-browsed: the recordset from create() carries creating_records.
        return self.env["maintenance.request"].with_user(self.user).browse(created.id)

    def _search(self, text):
        """The requests of this test the Hyresobjekt field finds for ``text``."""
        domain = safe_eval(self.field.get("filter_domain"), {"self": text})
        return (
            self.env["maintenance.request"]
            .with_user(self.user)
            .search([("id", "in", self.requests.ids)] + domain)
        )

    def test_form_shows_the_object_number_of_lokal_and_bilplats(self):
        self.assertEqual(self.facility.facility_object_number, FACILITY_NUMBER)
        self.assertEqual(self.parking.parking_space_object_number, PARKING_NUMBER)

    def test_object_number_is_empty_on_old_lokal(self):
        self.assertFalse(self.old_facility.facility_object_number)

    def test_search_finds_each_kind_by_its_object_number(self):
        for request, number in (
            (self.residence, RESIDENCE_NUMBER),
            (self.facility, FACILITY_NUMBER),
            (self.parking, PARKING_NUMBER),
        ):
            with self.subTest(number=number):
                self.assertEqual(self._search(number), request)

    def test_search_matches_part_of_the_object_number(self):
        self.assertEqual(self._search("211-625"), self.facility)
        self.assertEqual(self._search("705-02"), self.residence | self.parking)

    def test_search_does_not_match_on_kod(self):
        """Kod 0003 is the end of both the förråd's and the bilplats's number:
        searching the förråd's full number must not find the bilplats."""
        self.assertEqual(self._search(FACILITY_NUMBER), self.facility)
