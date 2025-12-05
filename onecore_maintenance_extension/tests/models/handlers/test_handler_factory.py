# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from unittest.mock import Mock

from ...test_utils import setup_faker, create_maintenance_request
from ....models.handlers.handler_factory import HandlerFactory
from ....models.handlers.rental_property_handler import RentalPropertyHandler
from ....models.handlers.parking_space_handler import ParkingSpaceHandler
from ....models.handlers.property_handler import PropertyHandler
from ....models.handlers.building_handler import BuildingHandler
from ....models.handlers.facility_handler import FacilityHandler


@tagged("onecore")
class TestHandlerFactory(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.maintenance_request = create_maintenance_request(self.env)
        self.core_api = Mock()

    def test_get_handler_property_handler_with_property_name(self):
        """Test that PropertyHandler is returned for propertyName search types."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "propertyName", "Fastighet"
        )
        self.assertIsInstance(handler, PropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "propertyName", "Byggnad"
        )
        self.assertIsInstance(handler, PropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "propertyName", "Tvättstuga"
        )
        self.assertIsInstance(handler, PropertyHandler)

    def test_get_handler_building_handler_with_building_code(self):
        """Test that BuildingHandler is returned for buildingCode search types."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "buildingCode", "Byggnad"
        )
        self.assertIsInstance(handler, BuildingHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "buildingCode", "Uppgång"
        )
        self.assertIsInstance(handler, BuildingHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "buildingCode", "Källare"
        )
        self.assertIsInstance(handler, BuildingHandler)

    def test_get_handler_rental_property_handler_with_pnr(self):
        """Test that RentalPropertyHandler is returned for pnr with apartment types."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Lägenhet"
        )
        self.assertIsInstance(handler, RentalPropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Tvättstuga"
        )
        self.assertIsInstance(handler, RentalPropertyHandler)

    def test_get_handler_building_handler_with_pnr(self):
        """Test that BuildingHandler is returned for pnr with building types."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Byggnad"
        )
        self.assertIsInstance(handler, BuildingHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Vind"
        )
        self.assertIsInstance(handler, BuildingHandler)

    def test_get_handler_property_handler_with_pnr(self):
        """Test that PropertyHandler is returned for pnr with property types."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Fastighet"
        )
        self.assertIsInstance(handler, PropertyHandler)

    def test_get_handler_facility_handler_with_pnr(self):
        """Test that FacilityHandler is returned for pnr with Lokal."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Lokal"
        )
        self.assertIsInstance(handler, FacilityHandler)

    def test_get_handler_parking_space_handler_with_pnr(self):
        """Test that ParkingSpaceHandler is returned for pnr with Bilplats."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Bilplats"
        )
        self.assertIsInstance(handler, ParkingSpaceHandler)

    def test_get_handler_with_contact_code(self):
        """Test that correct handlers are returned for contactCode search type."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "contactCode", "Lägenhet"
        )
        self.assertIsInstance(handler, RentalPropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "contactCode", "Lokal"
        )
        self.assertIsInstance(handler, FacilityHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "contactCode", "Bilplats"
        )
        self.assertIsInstance(handler, ParkingSpaceHandler)

    def test_get_handler_with_lease_id(self):
        """Test that correct handlers are returned for leaseId search type."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "leaseId", "Lägenhet"
        )
        self.assertIsInstance(handler, RentalPropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "leaseId", "Byggnad"
        )
        self.assertIsInstance(handler, BuildingHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "leaseId", "Fastighet"
        )
        self.assertIsInstance(handler, PropertyHandler)

    def test_get_handler_with_rental_object_id(self):
        """Test that correct handlers are returned for rentalObjectId search type."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "rentalObjectId", "Lägenhet"
        )
        self.assertIsInstance(handler, RentalPropertyHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "rentalObjectId", "Lokal"
        )
        self.assertIsInstance(handler, FacilityHandler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "rentalObjectId", "Bilplats"
        )
        self.assertIsInstance(handler, ParkingSpaceHandler)

    def test_get_handler_unsupported_combination(self):
        """Test that None is returned for unsupported combinations."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request,
            self.core_api,
            "unsupported_type",
            "Lägenhet",
        )
        self.assertIsNone(handler)

        handler = HandlerFactory.get_handler(
            self.maintenance_request,
            self.core_api,
            "pnr",
            "UnsupportedSpaceType",
        )
        self.assertIsNone(handler)

    def test_is_combination_supported(self):
        """Test that is_combination_supported correctly identifies supported combinations."""
        self.assertTrue(
            HandlerFactory.is_combination_supported("pnr", "Lägenhet")
        )
        self.assertTrue(
            HandlerFactory.is_combination_supported("buildingCode", "Byggnad")
        )
        self.assertTrue(
            HandlerFactory.is_combination_supported("propertyName", "Fastighet")
        )
        self.assertFalse(
            HandlerFactory.is_combination_supported("invalid", "Lägenhet")
        )
        self.assertFalse(
            HandlerFactory.is_combination_supported("pnr", "InvalidType")
        )

    def test_get_supported_combinations(self):
        """Test that get_supported_combinations returns all valid combinations."""
        combinations = HandlerFactory.get_supported_combinations()

        self.assertIsInstance(combinations, list)
        self.assertGreater(len(combinations), 0)

        # Check that some expected combinations are present
        self.assertIn(("pnr", "Lägenhet"), combinations)
        self.assertIn(("buildingCode", "Byggnad"), combinations)
        self.assertIn(("propertyName", "Fastighet"), combinations)
        self.assertIn(("leaseId", "Lokal"), combinations)
        self.assertIn(("contactCode", "Bilplats"), combinations)

    def test_handler_matrix_completeness(self):
        """Test that the HANDLER_MATRIX contains expected entries."""
        matrix = HandlerFactory.HANDLER_MATRIX

        # Check that all search types are covered
        search_types = {
            "propertyName",
            "buildingCode",
            "pnr",
            "contactCode",
            "leaseId",
            "rentalObjectId",
        }

        space_captions = {
            "Fastighet",
            "Byggnad",
            "Lägenhet",
            "Lokal",
            "Bilplats",
            "Uppgång",
            "Vind",
            "Källare",
            "Cykelförråd",
            "Gården/Utomhus",
            "Övrigt",
            "Tvättstuga",
            "Miljöbod",
            "Lekplats",
        }

        matrix_search_types = {key[0] for key in matrix.keys()}
        matrix_space_captions = {key[1] for key in matrix.keys()}

        # Verify all expected search types are in the matrix
        self.assertEqual(matrix_search_types, search_types)

        # Verify all expected space captions are in the matrix
        self.assertEqual(matrix_space_captions, space_captions)

    def test_handler_returns_correct_instances(self):
        """Test that handlers are instantiated with correct parameters."""
        handler = HandlerFactory.get_handler(
            self.maintenance_request, self.core_api, "pnr", "Lägenhet"
        )

        # Check that handler has the right attributes from BaseMaintenanceHandler
        self.assertEqual(handler.record, self.maintenance_request)
        self.assertEqual(handler.core_api, self.core_api)
