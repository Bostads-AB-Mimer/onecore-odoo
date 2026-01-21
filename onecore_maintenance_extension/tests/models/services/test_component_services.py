# -*- coding: utf-8 -*-
"""Tests for component services (AI analysis, hierarchy, OneCore operations)."""

import json
from unittest.mock import Mock, patch, MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Import services and modules for patching (using absolute imports)
from odoo.addons.onecore_maintenance_extension.models.services.component_ai_analysis_service import (
    ComponentAIAnalysisService
)
from odoo.addons.onecore_maintenance_extension.models.services.component_hierarchy_service import (
    ComponentHierarchyService
)
from odoo.addons.onecore_maintenance_extension.models.services.component_onecore_service import (
    ComponentOneCoreService
)
from odoo.addons.onecore_maintenance_extension.models.services import (
    component_ai_analysis_service as ai_service_module
)
from odoo.addons.onecore_maintenance_extension.models.services import (
    component_hierarchy_service as hierarchy_service_module
)
from odoo.addons.onecore_maintenance_extension.models.services import (
    component_onecore_service as onecore_service_module
)
from odoo.addons.onecore_maintenance_extension.models import (
    image_utils as image_utils_module
)


# =============================================================================
# ComponentAIAnalysisService Tests
# =============================================================================

@tagged("onecore")
class TestComponentAIAnalysisService(TransactionCase):
    """Tests for ComponentAIAnalysisService."""

    def setUp(self):
        super().setUp()
        self.mock_api = Mock()
        self.mock_hierarchy_service = Mock()

    def _create_service(self):
        """Create service with mocked dependencies."""
        service = ComponentAIAnalysisService(self.env)
        # Override lazy-loaded properties with mocks
        service._api = self.mock_api
        service._hierarchy_service = self.mock_hierarchy_service
        return service

    def test_ai_analyze_images_success_with_existing_model(self):
        """Full flow: AI analysis returns data, model found in OneCore."""
        service = self._create_service()

        # Mock AI response
        mock_response = Mock()
        mock_response.json.return_value = {
            'content': {
                'model': 'Electrolux EW6F5248G4',
                'manufacturer': 'Electrolux',
                'serialNumber': 'SN12345',
                'componentCategory': 'Kök',
                'componentType': 'Vitvaror',
                'componentSubtype': 'Tvättmaskin',
                'confidence': 0.95,
            }
        }
        mock_response.raise_for_status = Mock()
        self.mock_api.request.return_value = mock_response

        # Mock OneCore model lookup
        onecore_model = {
            'modelName': 'Electrolux EW6F5248G4',
            'manufacturer': 'Electrolux',
            'currentPrice': 5000,
            'currentInstallPrice': 500,
            'subtype': {
                'id': 'subtype-123',
                'subTypeName': 'Tvättmaskin',
                'componentType': {
                    'id': 'type-456',
                    'typeName': 'Vitvaror',
                    'category': {
                        'id': 'cat-789',
                        'categoryName': 'Kök'
                    }
                }
            }
        }
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        # Call with mock image data
        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.return_value = 'data:image/jpeg;base64,/9j/4AAQ...'
            result = service.analyze_images(b'fake_image_data')

        # Verify result
        self.assertFalse(result.get('error'))
        self.assertEqual(result['form_model'], 'Electrolux EW6F5248G4')
        self.assertEqual(result['form_serial_number'], 'SN12345')
        self.assertEqual(result['form_state'], 'review')
        self.assertEqual(result['form_category_id'], 'cat-789')
        self.assertEqual(result['form_type_id'], 'type-456')
        self.assertEqual(result['form_subtype_id'], 'subtype-123')
        self.assertTrue(result['form_ai_suggested'])
        self.assertTrue(result['form_model_data_loaded'])

    def test_ai_analyze_images_success_without_model(self):
        """AI analysis succeeds but no matching OneCore model found."""
        service = self._create_service()

        # Mock AI response
        mock_response = Mock()
        mock_response.json.return_value = {
            'content': {
                'model': 'Unknown Brand Model',
                'manufacturer': 'Unknown',
                'serialNumber': 'ABC123',
                'componentCategory': 'Badrum',
                'componentType': 'Sanitet',
                'componentSubtype': 'Toalett',
                'confidence': 0.7,
            }
        }
        mock_response.raise_for_status = Mock()
        self.mock_api.request.return_value = mock_response

        # No model found in OneCore
        self.mock_api.fetch_component_models.return_value = []

        # Mock hierarchy matching
        self.mock_hierarchy_service.match_ai_values_to_hierarchy.return_value = {
            'category_id': 'cat-abc',
            'type_id': 'type-def',
            'subtype_id': 'subtype-ghi',
            'available_types_json': '[]',
            'available_subtypes_json': '[]',
        }

        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.return_value = 'data:image/jpeg;base64,/9j/4AAQ...'
            result = service.analyze_images(b'fake_image_data')

        self.assertFalse(result.get('error'))
        self.assertEqual(result['form_model'], 'Unknown Brand Model')
        self.assertEqual(result['form_state'], 'review')
        self.assertFalse(result['form_model_data_loaded'])
        self.assertTrue(result['form_ai_suggested'])

    def test_ai_analyze_images_api_error_returns_error_dict(self):
        """Returns error dict with Swedish message on API failure."""
        service = self._create_service()

        # Mock API error
        self.mock_api.request.side_effect = Exception("Connection failed")

        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.return_value = 'data:image/jpeg;base64,/9j/4AAQ...'
            result = service.analyze_images(b'fake_image_data')

        self.assertTrue(result.get('error'))
        self.assertIn('Kunde inte analysera bilderna', result['error_message'])

    def test_ai_analyze_images_with_additional_image(self):
        """Both primary and additional images are sent to API."""
        service = self._create_service()

        mock_response = Mock()
        mock_response.json.return_value = {
            'content': {'model': 'Test', 'confidence': 0.8}
        }
        mock_response.raise_for_status = Mock()
        self.mock_api.request.return_value = mock_response
        self.mock_api.fetch_component_models.return_value = []
        self.mock_hierarchy_service.match_ai_values_to_hierarchy.return_value = {
            'category_id': None, 'type_id': None, 'subtype_id': None,
            'available_types_json': '[]', 'available_subtypes_json': '[]',
        }

        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.side_effect = [
                'data:image/jpeg;base64,primary...',
                'data:image/jpeg;base64,additional...'
            ]
            service.analyze_images(b'primary', b'additional')

        # Verify API was called with both images
        call_args = self.mock_api.request.call_args
        payload = call_args[1]['json']
        self.assertIn('image', payload)
        self.assertIn('additionalImage', payload)

    def test_ai_lookup_model_found(self):
        """Returns model when found in OneCore."""
        service = self._create_service()

        onecore_model = {'modelName': 'Test Model', 'manufacturer': 'Test'}
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        result = service._lookup_existing_model('Test Model')

        self.assertEqual(result, onecore_model)
        self.mock_api.fetch_component_models.assert_called_once_with(
            'Test Model', page=1, limit=1
        )

    def test_ai_lookup_model_not_found(self):
        """Returns None when model not found."""
        service = self._create_service()

        self.mock_api.fetch_component_models.return_value = []

        result = service._lookup_existing_model('Unknown Model')

        self.assertIsNone(result)

    def test_ai_lookup_model_empty_name(self):
        """Returns None for empty model name."""
        service = self._create_service()

        result = service._lookup_existing_model('')
        self.assertIsNone(result)

        result_none = service._lookup_existing_model(None)
        self.assertIsNone(result_none)

    def test_ai_build_form_values_prefers_onecore_manufacturer(self):
        """Uses OneCore manufacturer over AI when not 'Unknown'."""
        service = self._create_service()

        ai_content = {
            'manufacturer': 'AI Detected Mfg',
            'model': 'Test'
        }
        onecore_model = {
            'manufacturer': 'Correct Manufacturer',
            'subtype': {'componentType': {'category': {}}}
        }

        result = service._extract_onecore_values(ai_content, onecore_model)

        self.assertEqual(result['form_manufacturer'], 'Correct Manufacturer')

    def test_ai_build_form_values_ai_fallback(self):
        """Uses AI manufacturer when OneCore has 'Unknown'."""
        service = self._create_service()

        ai_content = {
            'manufacturer': 'AI Detected Mfg',
            'model': 'Test'
        }
        onecore_model = {
            'manufacturer': 'Unknown',
            'subtype': {'componentType': {'category': {}}}
        }

        result = service._extract_onecore_values(ai_content, onecore_model)

        self.assertEqual(result['form_manufacturer'], 'AI Detected Mfg')


# =============================================================================
# ComponentHierarchyService Tests
# =============================================================================

@tagged("onecore")
class TestComponentHierarchyService(TransactionCase):
    """Tests for ComponentHierarchyService."""

    def setUp(self):
        super().setUp()
        self.mock_api = Mock()

    def _create_service(self):
        """Create service with mocked API."""
        service = ComponentHierarchyService(self.env)
        # Override lazy-loaded property with mock
        service._api = self.mock_api
        return service

    def test_hierarchy_load_categories_success(self):
        """Returns categories list from API."""
        service = self._create_service()

        categories = [
            {'id': 'cat-1', 'categoryName': 'Kök'},
            {'id': 'cat-2', 'categoryName': 'Badrum'},
        ]
        self.mock_api.fetch_component_categories.return_value = categories

        result = service.load_categories()

        self.assertEqual(result, categories)
        self.mock_api.fetch_component_categories.assert_called_once()

    def test_hierarchy_load_categories_api_error(self):
        """Returns empty list on API error."""
        service = self._create_service()

        self.mock_api.fetch_component_categories.side_effect = Exception("API error")

        result = service.load_categories()

        self.assertEqual(result, [])

    def test_hierarchy_load_types_for_category(self):
        """Returns types for given category_id."""
        service = self._create_service()

        types = [
            {'id': 'type-1', 'typeName': 'Vitvaror'},
            {'id': 'type-2', 'typeName': 'Sanitet'},
        ]
        self.mock_api.fetch_component_types.return_value = types

        result = service.load_types_for_category('cat-123')

        self.assertEqual(result, types)
        self.mock_api.fetch_component_types.assert_called_once_with('cat-123')

    def test_hierarchy_load_types_empty_id(self):
        """Returns empty list when no category_id provided."""
        service = self._create_service()

        result = service.load_types_for_category(None)
        self.assertEqual(result, [])

        result_empty = service.load_types_for_category('')
        self.assertEqual(result_empty, [])

    def test_hierarchy_load_subtypes_for_type(self):
        """Returns subtypes for given type_id."""
        service = self._create_service()

        subtypes = [
            {'id': 'sub-1', 'subTypeName': 'Tvättmaskin'},
            {'id': 'sub-2', 'subTypeName': 'Diskmaskin'},
        ]
        self.mock_api.fetch_component_subtypes.return_value = subtypes

        result = service.load_subtypes_for_type('type-123')

        self.assertEqual(result, subtypes)
        self.mock_api.fetch_component_subtypes.assert_called_once_with('type-123')

    def test_hierarchy_load_subtypes_empty_id(self):
        """Returns empty list when no type_id provided."""
        service = self._create_service()

        result = service.load_subtypes_for_type(None)
        self.assertEqual(result, [])

    def test_hierarchy_get_economic_data_found(self):
        """Extracts lifespan, warranty, depreciation data from subtype."""
        service = self._create_service()

        subtypes_json = json.dumps([
            {
                'id': 'sub-1',
                'depreciationPrice': 100,
                'economicLifespan': 120,
                'technicalLifespan': 180,
                'replacementIntervalMonths': 60,
            }
        ])

        result = service.get_economic_data_from_subtype('sub-1', subtypes_json)

        self.assertEqual(result['depreciation_price'], 100)
        self.assertEqual(result['economic_lifespan'], 120)
        self.assertEqual(result['technical_lifespan'], 180)
        self.assertEqual(result['replacement_interval'], 60)

    def test_hierarchy_get_economic_data_not_found(self):
        """Returns default values when subtype not in JSON."""
        service = self._create_service()

        subtypes_json = json.dumps([
            {'id': 'sub-1', 'economicLifespan': 120}
        ])

        result = service.get_economic_data_from_subtype('sub-999', subtypes_json)

        self.assertEqual(result['depreciation_price'], 0)
        self.assertEqual(result['economic_lifespan'], 0)
        self.assertEqual(result['technical_lifespan'], 0)
        self.assertEqual(result['replacement_interval'], 0)

    def test_hierarchy_get_economic_data_empty_id(self):
        """Returns defaults when no subtype_id provided."""
        service = self._create_service()

        result = service.get_economic_data_from_subtype(None, '[]')

        self.assertEqual(result['depreciation_price'], 0)
        self.assertEqual(result['economic_lifespan'], 0)

    def test_hierarchy_load_model_data_success(self):
        """Returns model with extracted hierarchy."""
        service = self._create_service()

        onecore_model = {
            'modelName': 'Test Model',
            'manufacturer': 'Test Mfg',
            'warrantyMonths': 24,
            'currentPrice': 5000,
            'subtype': {
                'id': 'sub-1',
                'subTypeName': 'Tvättmaskin',
                'componentType': {
                    'id': 'type-1',
                    'typeName': 'Vitvaror',
                    'category': {
                        'id': 'cat-1',
                        'categoryName': 'Kök'
                    }
                }
            }
        }
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        result = service.load_model_data('Test Model')

        self.assertEqual(result['category_name'], 'Kök')
        self.assertEqual(result['category_id'], 'cat-1')
        self.assertEqual(result['type_name'], 'Vitvaror')
        self.assertEqual(result['type_id'], 'type-1')
        self.assertEqual(result['subtype_name'], 'Tvättmaskin')
        self.assertEqual(result['subtype_id'], 'sub-1')
        self.assertEqual(result['manufacturer'], 'Test Mfg')

    def test_hierarchy_load_model_data_not_found(self):
        """Returns None when model not found."""
        service = self._create_service()

        self.mock_api.fetch_component_models.return_value = []

        result = service.load_model_data('Unknown Model')

        self.assertIsNone(result)

    def test_hierarchy_load_model_data_empty_name(self):
        """Returns None for empty model name."""
        service = self._create_service()

        result = service.load_model_data('')
        self.assertIsNone(result)

        result_none = service.load_model_data(None)
        self.assertIsNone(result_none)

    def test_hierarchy_match_ai_values_full_match(self):
        """All 3 levels matched successfully."""
        service = self._create_service()

        categories = [{'id': 'cat-1', 'categoryName': 'Kök'}]
        types = [{'id': 'type-1', 'typeName': 'Vitvaror'}]
        subtypes = [{'id': 'sub-1', 'subTypeName': 'Tvättmaskin'}]

        self.mock_api.fetch_component_categories.return_value = categories
        self.mock_api.fetch_component_types.return_value = types
        self.mock_api.fetch_component_subtypes.return_value = subtypes

        result = service.match_ai_values_to_hierarchy('Kök', 'Vitvaror', 'Tvättmaskin')

        self.assertEqual(result['category_id'], 'cat-1')
        self.assertEqual(result['type_id'], 'type-1')
        self.assertEqual(result['subtype_id'], 'sub-1')

    def test_hierarchy_match_ai_values_partial_match(self):
        """Returns only category_id when type not found."""
        service = self._create_service()

        categories = [{'id': 'cat-1', 'categoryName': 'Kök'}]
        types = [{'id': 'type-1', 'typeName': 'Vitvaror'}]  # Different type

        self.mock_api.fetch_component_categories.return_value = categories
        self.mock_api.fetch_component_types.return_value = types

        result = service.match_ai_values_to_hierarchy('Kök', 'Sanitet', 'Toalett')

        self.assertEqual(result['category_id'], 'cat-1')
        self.assertIsNone(result['type_id'])
        self.assertIsNone(result['subtype_id'])

    def test_hierarchy_match_ai_values_no_category(self):
        """Returns all None when no category provided."""
        service = self._create_service()

        result = service.match_ai_values_to_hierarchy(None, 'Vitvaror', 'Tvättmaskin')

        self.assertIsNone(result['category_id'])
        self.assertIsNone(result['type_id'])
        self.assertIsNone(result['subtype_id'])


# =============================================================================
# ComponentOneCoreService Tests
# =============================================================================

@tagged("onecore")
class TestComponentOneCoreService(TransactionCase):
    """Tests for ComponentOneCoreService."""

    def setUp(self):
        super().setUp()
        self.mock_api = Mock()

    def _create_service(self):
        """Create service with mocked API."""
        service = ComponentOneCoreService(self.env)
        # Override lazy-loaded property with mock
        service._api = self.mock_api
        return service

    def test_onecore_create_component_success(self):
        """Creates component via API successfully."""
        service = self._create_service()

        self.mock_api.create_component.return_value = {'id': 'comp-123'}

        form_data = {
            'model': 'Test Model',
            'subtype_id': 'sub-1',
            'serial_number': 'SN123',
            'warranty_months': 24,
            'current_price': 5000,
            'manufacturer': 'Test Mfg',
        }

        result = service.create_component(form_data, 'room-456')

        self.assertEqual(result['id'], 'comp-123')
        self.mock_api.create_component.assert_called_once()

        # Verify payload structure
        call_args = self.mock_api.create_component.call_args[0][0]
        self.assertEqual(call_args['modelName'], 'Test Model')
        self.assertEqual(call_args['componentSubtypeId'], 'sub-1')
        self.assertEqual(call_args['serialNumber'], 'SN123')
        self.assertEqual(call_args['spaceId'], 'room-456')

    def test_onecore_create_component_api_error(self):
        """Raises exception on API failure."""
        service = self._create_service()

        self.mock_api.create_component.side_effect = Exception("API error")

        form_data = {'model': 'Test', 'subtype_id': 'sub-1'}

        with self.assertRaises(Exception) as ctx:
            service.create_component(form_data, 'room-456')

        self.assertIn('API error', str(ctx.exception))

    def test_onecore_build_payload_complete(self):
        """All fields correctly mapped to API payload."""
        service = self._create_service()

        from datetime import date
        form_data = {
            'model': 'Electrolux ABC',
            'subtype_id': 'sub-123',
            'serial_number': 'SN999',
            'warranty_months': 36,
            'current_price': 8000,
            'current_install_price': 800,
            'depreciation_price': 100,
            'economic_lifespan': 120,
            'manufacturer': 'Electrolux',
            'condition': 'NEW',
            'specifications': 'Energy class A++',
            'dimensions': '60x60x85 cm',
            'additional_information': 'Front loader',
            'ncs_code': 'S 1000-N',
            'installation_date': date(2025, 1, 15),
        }

        payload = service._build_create_payload(form_data, 'room-789')

        self.assertEqual(payload['modelName'], 'Electrolux ABC')
        self.assertEqual(payload['componentSubtypeId'], 'sub-123')
        self.assertEqual(payload['serialNumber'], 'SN999')
        self.assertEqual(payload['componentWarrantyMonths'], 36)
        self.assertEqual(payload['priceAtPurchase'], 8000)
        self.assertEqual(payload['installationCost'], 800)
        self.assertEqual(payload['depreciationPriceAtPurchase'], 100)
        self.assertEqual(payload['economicLifespan'], 120)
        self.assertEqual(payload['manufacturer'], 'Electrolux')
        self.assertEqual(payload['spaceId'], 'room-789')
        self.assertEqual(payload['spaceType'], 'PropertyObject')
        self.assertEqual(payload['condition'], 'NEW')
        self.assertEqual(payload['technicalSpecification'], 'Energy class A++')
        self.assertEqual(payload['dimensions'], '60x60x85 cm')
        self.assertEqual(payload['additionalInformation'], 'Front loader')
        self.assertEqual(payload['ncsCode'], 'S 1000-N')
        self.assertIn('2025-01-15', payload['installationDate'])

    def test_onecore_build_payload_uses_today_default(self):
        """Uses today's date when installation_date not provided."""
        service = self._create_service()

        form_data = {
            'model': 'Test',
            'subtype_id': 'sub-1',
        }

        payload = service._build_create_payload(form_data, 'room-1')

        # Should have an installation date (today)
        self.assertIn('installationDate', payload)
        self.assertIsNotNone(payload['installationDate'])

    def test_onecore_load_components_for_residence(self):
        """Returns rooms, categories, and component data."""
        service = self._create_service()

        # Mock residence
        self.mock_api.fetch_residence.return_value = {'id': 'res-123'}

        # Mock rooms
        self.mock_api.fetch_rooms.return_value = [
            {'propertyObjectId': 'room-1', 'name': 'Kök'},
            {'propertyObjectId': 'room-2', 'name': 'Badrum'},
        ]

        # Mock categories
        self.mock_api.fetch_component_categories.return_value = [
            {'id': 'cat-1', 'categoryName': 'Kök'}
        ]

        # Mock components per room
        component = {
            'id': 'comp-1',
            'serialNumber': 'SN123',
            'model': {
                'modelName': 'Test Model',
                'manufacturer': 'Test Mfg',
                'subtype': {
                    'subTypeName': 'Tvättmaskin',
                    'componentType': {
                        'typeName': 'Vitvaror',
                        'category': {'categoryName': 'Kök'}
                    }
                }
            },
            'componentInstallations': [
                {'id': 'inst-1', 'installationDate': '2024-01-15T00:00:00Z'}
            ]
        }
        self.mock_api.fetch_components_by_room.return_value = [component]
        self.mock_api.fetch_component_documents.return_value = []

        rooms_json, categories_json, components = service.load_components_for_residence(
            'rental-prop-123', 'Lägenhet'
        )

        # Verify rooms
        rooms = json.loads(rooms_json)
        self.assertEqual(len(rooms), 2)
        self.assertEqual(rooms[0]['name'], 'Kök')

        # Verify categories
        categories = json.loads(categories_json)
        self.assertEqual(len(categories), 1)

        # Verify components
        self.assertEqual(len(components), 2)  # One per room
        self.assertEqual(components[0]['model'], 'Test Model')
        self.assertEqual(components[0]['serial_number'], 'SN123')

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
            (b'image1_data', 'Front view'),
            (b'image2_data', 'Side view'),
        ]

        result = service.upload_component_images('comp-123', images)

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(self.mock_api.upload_document.call_count, 2)

    def test_onecore_upload_images_partial_failure(self):
        """Handles some uploads failing."""
        service = self._create_service()

        # First succeeds, second fails
        self.mock_api.upload_document.side_effect = [
            {'id': 'doc-1'},
            Exception("Upload failed"),
        ]

        images = [
            (b'image1_data', 'Front view'),
            (b'image2_data', 'Side view'),
        ]

        result = service.upload_component_images('comp-123', images)

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['errors'][0]['caption'], 'Side view')

    def test_onecore_upload_images_no_component_id(self):
        """Returns empty result when no component_id provided."""
        service = self._create_service()

        result = service.upload_component_images(None, [(b'data', 'test')])

        self.assertEqual(result['success_count'], 0)
        self.mock_api.upload_document.assert_not_called()

    def test_onecore_search_models_success(self):
        """Returns formatted model results."""
        service = self._create_service()

        self.mock_api.fetch_component_models.return_value = [
            {'modelName': 'Model A', 'manufacturer': 'Mfg A'},
            {'modelName': 'Model B', 'manufacturer': 'Mfg B'},
        ]

        result = service.search_models('Model')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['modelName'], 'Model A')
        self.assertEqual(result[0]['label'], 'Model A (Mfg A)')

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
            'id': 'comp-1',
            'model': {'modelName': 'Test'},
            'componentInstallations': [
                {
                    'id': 'inst-1',
                    'installationDate': '2024-01-15',
                    'deinstallationDate': '2025-01-01'  # Uninstalled
                }
            ]
        }

        result = service._transform_component_data(component, 'Kök', 'room-1')

        self.assertIsNone(result)

    def test_onecore_fetch_image_urls_success(self):
        """Returns valid image URLs."""
        service = self._create_service()

        self.mock_api.fetch_component_documents.return_value = [
            {'url': 'https://example.com/img1.jpg', 'size': 1000},
            {'url': 'https://example.com/img2.jpg', 'size': 2000},
        ]

        result = service.fetch_all_component_image_urls('comp-123')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 'https://example.com/img1.jpg')

    def test_onecore_fetch_image_urls_filters_invalid(self):
        """Filters out documents with no URL or zero size."""
        service = self._create_service()

        self.mock_api.fetch_component_documents.return_value = [
            {'url': 'https://example.com/img1.jpg', 'size': 1000},
            {'url': None, 'size': 500},  # No URL
            {'url': 'https://example.com/img2.jpg', 'size': 0},  # Zero size
            {'url': 'https://example.com/img3.jpg', 'size': 800},
        ]

        result = service.fetch_all_component_image_urls('comp-123')

        self.assertEqual(len(result), 2)
        self.assertIn('https://example.com/img1.jpg', result)
        self.assertIn('https://example.com/img3.jpg', result)
