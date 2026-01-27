# -*- coding: utf-8 -*-
"""Tests for ComponentOneCoreService."""

import json
from datetime import date
from unittest.mock import Mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services.component_onecore_service import (
    ComponentOneCoreService,
)
from odoo.addons.onecore_maintenance_extension.tests.utils.test_utils import setup_faker


@tagged("onecore")
class TestComponentOneCoreService(TransactionCase):
    """Tests for ComponentOneCoreService."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.mock_api = Mock()

    def _create_service(self):
        """Create service with mocked API."""
        service = ComponentOneCoreService(self.env)
        service._api = self.mock_api
        return service

    def test_onecore_create_component_success(self):
        """Creates component via API successfully."""
        service = self._create_service()

        comp_id = self.fake.component_instance_id()
        self.mock_api.create_component.return_value = {'id': comp_id}

        form_data = self.fake.component_form_data()
        room_id = self.fake.component_room_id()

        result = service.create_component(form_data, room_id)

        self.assertEqual(result['id'], comp_id)
        self.mock_api.create_component.assert_called_once()

        call_args = self.mock_api.create_component.call_args[0][0]
        self.assertEqual(call_args['modelName'], form_data['model'])
        self.assertEqual(call_args['componentSubtypeId'], form_data['subtype_id'])
        self.assertEqual(call_args['serialNumber'], form_data['serial_number'])
        self.assertEqual(call_args['spaceId'], room_id)

    def test_onecore_create_component_api_error(self):
        """Raises exception on API failure."""
        service = self._create_service()

        self.mock_api.create_component.side_effect = Exception("API error")

        form_data = self.fake.component_form_data()

        with self.assertRaises(Exception) as ctx:
            service.create_component(form_data, self.fake.component_room_id())

        self.assertIn('API error', str(ctx.exception))

    def test_onecore_build_payload_complete(self):
        """All fields correctly mapped to API payload."""
        service = self._create_service()

        form_data = self.fake.component_form_data(
            installation_date=date(2025, 1, 15),
        )
        room_id = self.fake.component_room_id()

        payload = service._build_create_payload(form_data, room_id)

        self.assertEqual(payload['modelName'], form_data['model'])
        self.assertEqual(payload['componentSubtypeId'], form_data['subtype_id'])
        self.assertEqual(payload['serialNumber'], form_data['serial_number'])
        self.assertEqual(payload['componentWarrantyMonths'], form_data['warranty_months'])
        self.assertEqual(payload['priceAtPurchase'], form_data['current_price'])
        self.assertEqual(payload['installationCost'], form_data['current_install_price'])
        self.assertEqual(payload['depreciationPriceAtPurchase'], form_data['depreciation_price'])
        self.assertEqual(payload['economicLifespan'], form_data['economic_lifespan'])
        self.assertEqual(payload['manufacturer'], form_data['manufacturer'])
        self.assertEqual(payload['spaceId'], room_id)
        self.assertEqual(payload['spaceType'], 'PropertyObject')
        self.assertEqual(payload['condition'], form_data['condition'])
        self.assertEqual(payload['technicalSpecification'], form_data['specifications'])
        self.assertEqual(payload['dimensions'], form_data['dimensions'])
        self.assertEqual(payload['ncsCode'], form_data['ncs_code'])
        self.assertIn('2025-01-15', payload['installationDate'])

    def test_onecore_build_payload_uses_today_default(self):
        """Uses today's date when installation_date not provided."""
        service = self._create_service()

        form_data = self.fake.component_form_data()

        payload = service._build_create_payload(form_data, self.fake.component_room_id())

        self.assertIn('installationDate', payload)
        self.assertIsNotNone(payload['installationDate'])

    def test_onecore_load_components_for_residence(self):
        """Returns rooms, categories, and component data."""
        service = self._create_service()

        room_1_id = self.fake.component_room_id()
        room_2_id = self.fake.component_room_id()
        serial = self.fake.component_serial_number()
        model_name = self.fake.component_model_name()
        manufacturer = self.fake.component_manufacturer()

        self.mock_api.fetch_residence.return_value = {'id': 'res-123'}

        self.mock_api.fetch_rooms.return_value = [
            {'propertyObjectId': room_1_id, 'name': 'Kök'},
            {'propertyObjectId': room_2_id, 'name': 'Badrum'},
        ]

        cat_id = self.fake.component_category_id()
        self.mock_api.fetch_component_categories.return_value = [
            {'id': cat_id, 'categoryName': 'Kök'}
        ]

        component = {
            'id': self.fake.component_instance_id(),
            'serialNumber': serial,
            'model': {
                'modelName': model_name,
                'manufacturer': manufacturer,
                'subtype': {
                    'subTypeName': self.fake.component_subtype_name(),
                    'componentType': {
                        'typeName': self.fake.component_type_name(),
                        'category': {'categoryName': self.fake.component_category_name()}
                    }
                }
            },
            'componentInstallations': [
                {
                    'id': self.fake.component_installation_id(),
                    'installationDate': '2024-01-15T00:00:00Z',
                }
            ]
        }
        self.mock_api.fetch_components_by_room.return_value = [component]
        self.mock_api.fetch_component_documents.return_value = []

        rooms_json, categories_json, components = service.load_components_for_residence(
            'rental-prop-123', 'Lägenhet'
        )

        rooms = json.loads(rooms_json)
        self.assertEqual(len(rooms), 2)
        self.assertEqual(rooms[0]['name'], 'Kök')

        categories = json.loads(categories_json)
        self.assertEqual(len(categories), 1)

        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]['model'], model_name)
        self.assertEqual(components[0]['serial_number'], serial)

    def test_onecore_load_components_non_apartment(self):
        """Returns empty for non-apartment space_caption."""
        service = self._create_service()

        rooms_json, categories_json, components = service.load_components_for_residence(
            'rental-prop-123', 'Bilplats'
        )

        self.assertEqual(rooms_json, '[]')
        self.assertEqual(categories_json, '[]')
        self.assertEqual(components, [])

    def test_onecore_load_components_no_rental_id(self):
        """Returns empty when no rental_property_id provided."""
        service = self._create_service()

        rooms_json, categories_json, components = service.load_components_for_residence(
            None, 'Lägenhet'
        )

        self.assertEqual(rooms_json, '[]')
        self.assertEqual(categories_json, '[]')
        self.assertEqual(components, [])

    def test_onecore_load_components_no_rooms(self):
        """Returns empty when no rooms found."""
        service = self._create_service()

        self.mock_api.fetch_residence.return_value = {'id': 'res-123'}
        self.mock_api.fetch_rooms.return_value = []

        rooms_json, categories_json, components = service.load_components_for_residence(
            'rental-prop-123', 'Lägenhet'
        )

        self.assertEqual(rooms_json, '[]')
        self.assertEqual(categories_json, '[]')
        self.assertEqual(components, [])

    def test_onecore_upload_images_success(self):
        """Uploads images to component successfully."""
        service = self._create_service()

        self.mock_api.upload_document.return_value = {'id': 'doc-1'}

        images = [
            (b'image1_data', self.fake.sentence()),
            (b'image2_data', self.fake.sentence()),
        ]

        comp_id = self.fake.component_instance_id()
        result = service.upload_component_images(comp_id, images)

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(self.mock_api.upload_document.call_count, 2)

    def test_onecore_upload_images_partial_failure(self):
        """Handles some uploads failing."""
        service = self._create_service()

        caption_fail = self.fake.sentence()

        self.mock_api.upload_document.side_effect = [
            {'id': 'doc-1'},
            Exception("Upload failed"),
        ]

        images = [
            (b'image1_data', self.fake.sentence()),
            (b'image2_data', caption_fail),
        ]

        result = service.upload_component_images(
            self.fake.component_instance_id(), images
        )

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['errors'][0]['caption'], caption_fail)

    def test_onecore_upload_images_no_component_id(self):
        """Returns empty result when no component_id provided."""
        service = self._create_service()

        result = service.upload_component_images(None, [(b'data', 'test')])

        self.assertEqual(result['success_count'], 0)
        self.mock_api.upload_document.assert_not_called()

    def test_onecore_search_models_success(self):
        """Returns formatted model results."""
        service = self._create_service()

        model_a = self.fake.component_model_name()
        mfg_a = self.fake.component_manufacturer()
        model_b = self.fake.component_model_name()
        mfg_b = self.fake.component_manufacturer()

        self.mock_api.fetch_component_models.return_value = [
            {'modelName': model_a, 'manufacturer': mfg_a},
            {'modelName': model_b, 'manufacturer': mfg_b},
        ]

        result = service.search_models('Model')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['modelName'], model_a)
        self.assertEqual(result[0]['label'], f'{model_a} ({mfg_a})')

    def test_onecore_search_models_min_length(self):
        """Returns empty for search text < 2 chars."""
        service = self._create_service()

        result = service.search_models('M')
        self.assertEqual(result, [])

        result_empty = service.search_models('')
        self.assertEqual(result_empty, [])

    def test_onecore_transform_skips_uninstalled(self):
        """Filters out components with deinstallationDate."""
        service = self._create_service()

        component = {
            'id': self.fake.component_instance_id(),
            'model': {'modelName': self.fake.component_model_name()},
            'componentInstallations': [
                {
                    'id': self.fake.component_installation_id(),
                    'installationDate': '2024-01-15',
                    'deinstallationDate': '2025-01-01',
                }
            ]
        }

        result = service._transform_component_data(
            component, self.fake.component_category_name(), self.fake.component_room_id()
        )

        self.assertIsNone(result)

    def test_onecore_fetch_image_urls_success(self):
        """Returns valid image URLs."""
        service = self._create_service()

        url_1 = self.fake.image_url()
        url_2 = self.fake.image_url()

        self.mock_api.fetch_component_documents.return_value = [
            {'url': url_1, 'size': 1000},
            {'url': url_2, 'size': 2000},
        ]

        result = service.fetch_all_component_image_urls(
            self.fake.component_instance_id()
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], url_1)

    def test_onecore_fetch_image_urls_filters_invalid(self):
        """Filters out documents with no URL or zero size."""
        service = self._create_service()

        url_valid_1 = self.fake.image_url()
        url_valid_2 = self.fake.image_url()

        self.mock_api.fetch_component_documents.return_value = [
            {'url': url_valid_1, 'size': 1000},
            {'url': None, 'size': 500},
            {'url': self.fake.image_url(), 'size': 0},
            {'url': url_valid_2, 'size': 800},
        ]

        result = service.fetch_all_component_image_urls(
            self.fake.component_instance_id()
        )

        self.assertEqual(len(result), 2)
        self.assertIn(url_valid_1, result)
        self.assertIn(url_valid_2, result)
