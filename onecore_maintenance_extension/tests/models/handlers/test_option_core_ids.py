from unittest.mock import Mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import create_maintenance_request
from ....models.handlers.building_handler import BuildingHandler
from ....models.handlers.facility_handler import FacilityHandler
from ....models.handlers.property_handler import PropertyHandler
from ....models.handlers.rental_property_handler import RentalPropertyHandler

UNIT_CODE = "705T15"
UNIT_ID = "_3SB0PK5VC9K1AA"
PROPERTY_OBJECT_ID = "_3SB0PK5VC9K1IT"
FACILITY_ID = "_0HJ0WYQQ6P1XK"


@tagged("onecore")
class TestOptionCoreIds(TransactionCase):
    """Handlers keep the core ids from the search response on the options."""

    def setUp(self):
        super().setUp()
        self.request = create_maintenance_request(self.env)
        self.core_api = Mock()

    def _maintenance_unit(self):
        return {
            "id": UNIT_ID,
            "propertyObjectId": PROPERTY_OBJECT_ID,
            "code": UNIT_CODE,
            "caption": "Tvättstuga Vidtskögatan 2",
            "type": "Tvättstuga",
            "estateCode": "01503",
            "estate": "KOPPARBERGET 2",
        }

    def _rental_property(self):
        return {
            "code": "705-022-04-0201",
            "name": "Vidtskögatan 2",
            "rentalInformation": {"rentalId": "705-022-04-0201"},
            "type": {"name": "3 rum och kök"},
            "areaSize": 74,
            "entrance": "04",
            "accessibility": {"elevator": True},
            "property": {"code": "01503", "name": "KOPPARBERGET 2"},
            "building": {"code": "705-022", "name": "Vidtskögatan 2"},
        }

    def _lease(self):
        return {
            "leaseId": "705-022-04-0201/01",
            "leaseNumber": "01",
            "type": "Bostadskontrakt",
            "status": "Current",
            "leaseStartDate": "2020-01-01",
            "lastDebitDate": None,
            "contractDate": "2019-12-01",
            "approvalDate": "2019-12-01",
            "tenants": [],
        }

    def _facility(self, area_size):
        return {
            "id": FACILITY_ID,
            "propertyObjectId": "_0HJ0WYQQ6P1XL",
            "code": "705-022-00-0101",
            "name": "Lokal Vidtskögatan 2",
            "type": {"code": "LOK", "name": "Lokal"},
            "rentalInformation": {
                "rentalId": "705-022-00-0101",
                "type": {"code": "L", "name": "Lokal"},
            },
            "property": {"code": "01503", "name": "KOPPARBERGET 2"},
            "building": {"code": "705-022", "name": "Vidtskögatan 2"},
            "areaSize": area_size,
        }

    def _unit_option(self):
        return self.env["maintenance.maintenance.unit.option"].search(
            [("user_id", "=", self.env.user.id), ("code", "=", UNIT_CODE)]
        )

    def _facility_option(self):
        return self.env["maintenance.facility.option"].search(
            [("user_id", "=", self.env.user.id), ("facility_id", "=", FACILITY_ID)]
        )

    def test_rental_property_search_keeps_property_object_id(self):
        RentalPropertyHandler(self.request, self.core_api).update_form_options(
            [
                {
                    "rental_property": self._rental_property(),
                    "lease": None,
                    "maintenance_units": [self._maintenance_unit()],
                }
            ]
        )

        unit_option = self._unit_option()
        self.assertEqual(unit_option.property_object_id, PROPERTY_OBJECT_ID)
        self.assertTrue(unit_option.rental_property_option_id)

    def test_property_search_keeps_property_object_id(self):
        PropertyHandler(self.request, self.core_api).update_form_options(
            [
                {
                    "property": {"designation": "KOPPARBERGET 2", "code": "01503"},
                    "buildings": [],
                    "maintenance_units": [self._maintenance_unit()],
                }
            ]
        )

        unit_option = self._unit_option()
        self.assertEqual(unit_option.property_object_id, PROPERTY_OBJECT_ID)
        self.assertEqual(unit_option.property_option_id.code, "01503")

    def test_property_lease_search_keeps_property_object_id(self):
        PropertyHandler(
            self.request, self.core_api
        ).update_form_options_from_lease_data(
            [
                {
                    "rental_property": self._rental_property(),
                    "lease": self._lease(),
                    "maintenance_units": [self._maintenance_unit()],
                }
            ]
        )

        unit_option = self._unit_option()
        self.assertEqual(unit_option.property_object_id, PROPERTY_OBJECT_ID)
        self.assertTrue(unit_option.rental_property_option_id)

    def test_building_search_keeps_property_object_id(self):
        BuildingHandler(self.request, self.core_api).update_form_options(
            {
                "name": "Vidtskögatan 2",
                "code": "705-022",
                "maintenance_units": [self._maintenance_unit()],
                "staircases": [],
            }
        )

        unit_option = self._unit_option()
        self.assertEqual(unit_option.property_object_id, PROPERTY_OBJECT_ID)
        self.assertEqual(unit_option.building_option_id.code, "705-022")

    def test_building_lease_search_keeps_property_object_id(self):
        BuildingHandler(
            self.request, self.core_api
        ).update_form_options_from_lease_data(
            [
                {
                    "rental_property": self._rental_property(),
                    "lease": self._lease(),
                    "maintenance_units": [self._maintenance_unit()],
                }
            ]
        )

        unit_option = self._unit_option()
        self.assertEqual(unit_option.property_object_id, PROPERTY_OBJECT_ID)
        self.assertTrue(unit_option.rental_property_option_id)

    def test_facility_search_keeps_facility_id_and_area(self):
        FacilityHandler(self.request, self.core_api).update_form_options(
            [{"facility": self._facility(area_size=48.5), "lease": None}]
        )

        facility_option = self._facility_option()
        self.assertEqual(len(facility_option), 1)
        self.assertEqual(facility_option.area, "48.5")

    def test_facility_search_without_area_leaves_area_empty(self):
        FacilityHandler(self.request, self.core_api).update_form_options(
            [{"facility": self._facility(area_size=None), "lease": None}]
        )

        facility_option = self._facility_option()
        self.assertEqual(len(facility_option), 1)
        self.assertFalse(facility_option.area)
