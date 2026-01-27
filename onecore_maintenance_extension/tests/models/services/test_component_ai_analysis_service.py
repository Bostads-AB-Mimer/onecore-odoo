# -*- coding: utf-8 -*-
"""Tests for ComponentAIAnalysisService."""

from unittest.mock import Mock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services.component_ai_analysis_service import (
    ComponentAIAnalysisService,
)
from odoo.addons.onecore_maintenance_extension.models.services import (
    component_ai_analysis_service as ai_service_module,
)
from odoo.addons.onecore_maintenance_extension.tests.test_utils import setup_faker


@tagged("onecore")
class TestComponentAIAnalysisService(TransactionCase):
    """Tests for ComponentAIAnalysisService."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.mock_api = Mock()
        self.mock_hierarchy_service = Mock()

    def _create_service(self):
        """Create service with mocked dependencies."""
        service = ComponentAIAnalysisService(self.env)
        service._api = self.mock_api
        service._hierarchy_service = self.mock_hierarchy_service
        return service

    def test_ai_analyze_images_success_with_existing_model(self):
        """Full flow: AI analysis returns data, model found in OneCore."""
        service = self._create_service()

        ai_content = self.fake.ai_analysis_response()

        mock_response = Mock()
        mock_response.json.return_value = {'content': ai_content}
        mock_response.raise_for_status = Mock()
        self.mock_api.request.return_value = mock_response

        onecore_model = self.fake.onecore_model_response()
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.return_value = 'data:image/jpeg;base64,/9j/4AAQ...'
            result = service.analyze_images(b'fake_image_data')

        self.assertFalse(result.get('error'))
        self.assertEqual(result['form_model'], ai_content['model'])
        self.assertEqual(result['form_serial_number'], ai_content['serialNumber'])
        self.assertEqual(result['form_state'], 'review')
        self.assertEqual(
            result['form_category_id'],
            onecore_model['subtype']['componentType']['category']['id'],
        )
        self.assertEqual(
            result['form_type_id'],
            onecore_model['subtype']['componentType']['id'],
        )
        self.assertEqual(
            result['form_subtype_id'],
            onecore_model['subtype']['id'],
        )
        self.assertTrue(result['form_ai_suggested'])
        self.assertTrue(result['form_model_data_loaded'])

    def test_ai_analyze_images_success_without_model(self):
        """AI analysis succeeds but no matching OneCore model found."""
        service = self._create_service()

        ai_content = self.fake.ai_analysis_response()

        mock_response = Mock()
        mock_response.json.return_value = {'content': ai_content}
        mock_response.raise_for_status = Mock()
        self.mock_api.request.return_value = mock_response

        self.mock_api.fetch_component_models.return_value = []

        self.mock_hierarchy_service.match_ai_values_to_hierarchy.return_value = {
            'category_id': self.fake.component_category_id(),
            'type_id': self.fake.component_type_id(),
            'subtype_id': self.fake.component_subtype_id(),
            'available_types_json': '[]',
            'available_subtypes_json': '[]',
        }

        with patch.object(
            ai_service_module, 'image_to_data_url'
        ) as mock_img:
            mock_img.return_value = 'data:image/jpeg;base64,/9j/4AAQ...'
            result = service.analyze_images(b'fake_image_data')

        self.assertFalse(result.get('error'))
        self.assertEqual(result['form_model'], ai_content['model'])
        self.assertEqual(result['form_state'], 'review')
        self.assertFalse(result['form_model_data_loaded'])
        self.assertTrue(result['form_ai_suggested'])

    def test_ai_analyze_images_api_error_returns_error_dict(self):
        """Returns error dict with Swedish message on API failure."""
        service = self._create_service()

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

        ai_content = self.fake.ai_analysis_response()

        mock_response = Mock()
        mock_response.json.return_value = {'content': ai_content}
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
                'data:image/jpeg;base64,additional...',
            ]
            service.analyze_images(b'primary', b'additional')

        call_args = self.mock_api.request.call_args
        payload = call_args[1]['json']
        self.assertIn('image', payload)
        self.assertIn('additionalImage', payload)

    def test_ai_lookup_model_found(self):
        """Returns model when found in OneCore."""
        service = self._create_service()

        model_name = self.fake.component_model_name()
        onecore_model = self.fake.onecore_model_response(modelName=model_name)
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        result = service._lookup_existing_model(model_name)

        self.assertEqual(result, onecore_model)
        self.mock_api.fetch_component_models.assert_called_once_with(
            model_name, page=1, limit=1
        )

    def test_ai_lookup_model_not_found(self):
        """Returns None when model not found."""
        service = self._create_service()

        self.mock_api.fetch_component_models.return_value = []

        result = service._lookup_existing_model(self.fake.component_model_name())

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

        correct_manufacturer = self.fake.component_manufacturer()

        ai_content = {
            'manufacturer': 'AI Detected Mfg',
            'model': self.fake.component_model_name(),
        }
        onecore_model = {
            'manufacturer': correct_manufacturer,
            'subtype': {'componentType': {'category': {}}},
        }

        result = service._extract_onecore_values(ai_content, onecore_model)

        self.assertEqual(result['form_manufacturer'], correct_manufacturer)

    def test_ai_build_form_values_ai_fallback(self):
        """Uses AI manufacturer when OneCore has 'Unknown'."""
        service = self._create_service()

        ai_manufacturer = self.fake.component_manufacturer()

        ai_content = {
            'manufacturer': ai_manufacturer,
            'model': self.fake.component_model_name(),
        }
        onecore_model = {
            'manufacturer': 'Unknown',
            'subtype': {'componentType': {'category': {}}},
        }

        result = service._extract_onecore_values(ai_content, onecore_model)

        self.assertEqual(result['form_manufacturer'], ai_manufacturer)
