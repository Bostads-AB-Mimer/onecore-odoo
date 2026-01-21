"""Service for AI image analysis of components."""

import logging

from ....onecore_api import core_api
from ..image_utils import image_to_data_url
from .component_hierarchy_service import ComponentHierarchyService

_logger = logging.getLogger(__name__)


class ComponentAIAnalysisService:
    """Service for handling AI image analysis of components."""

    def __init__(self, env):
        self.env = env
        self._api = None
        self._hierarchy_service = None

    @property
    def api(self):
        """Lazy-load the API client."""
        if self._api is None:
            self._api = core_api.CoreApi(self.env)
        return self._api

    @property
    def hierarchy_service(self):
        """Lazy-load the hierarchy service."""
        if self._hierarchy_service is None:
            self._hierarchy_service = ComponentHierarchyService(self.env)
        return self._hierarchy_service

    def analyze_images(self, primary_image, additional_image=None):
        """Analyze component images using AI.

        Args:
            primary_image: Primary image binary data
            additional_image: Optional additional image binary data

        Returns:
            dict: Analysis result with form values, or error dict

        The returned dict contains either:
        - Success: form values to update the wizard
        - Error: {'error': True, 'error_message': str}
        """
        try:
            # Prepare and send images to AI
            payload = self._prepare_image_payload(primary_image, additional_image)
            response = self._call_analyze_api(payload)
            content = self._parse_analysis_response(response)

            # Try to find existing model in OneCore
            model_name = content.get('model')
            onecore_model = self._lookup_existing_model(model_name)

            # Build form values from AI + OneCore data
            return self._build_form_values(content, onecore_model)

        except Exception as e:
            _logger.error(f"AI analysis failed: {str(e)}", exc_info=True)
            error_detail = self._extract_error_detail(e)
            return {
                'error': True,
                'error_message': f"Kunde inte analysera bilderna: {error_detail}\n\nKontrollera att bilderna är tydliga och försök igen."
            }

    def _prepare_image_payload(self, primary_image, additional_image):
        """Prepare images for API request.

        Args:
            primary_image: Primary image binary data
            additional_image: Optional additional image binary data

        Returns:
            dict: Payload with image data URLs
        """
        payload = {"image": image_to_data_url(primary_image, logger=_logger)}
        if additional_image:
            payload["additionalImage"] = image_to_data_url(additional_image, logger=_logger)

        _logger.info(
            f"Sending payload with image data URL prefix: "
            f"{payload['image'][:100] if payload.get('image') else 'None'}"
        )
        return payload

    def _call_analyze_api(self, payload):
        """Call the AI analyze endpoint.

        Args:
            payload: Image payload dict

        Returns:
            dict: API response JSON

        Raises:
            Exception: If API call fails
        """
        response = self.api.request(
            "POST", "/components/analyze-image", json=payload, timeout=30
        )
        response.raise_for_status()
        return response.json()

    def _parse_analysis_response(self, response):
        """Parse the AI analysis response.

        Args:
            response: Raw API response dict

        Returns:
            dict: Extracted content from response
        """
        return response.get('content', {})

    def _lookup_existing_model(self, model_name):
        """Try to find an existing model in OneCore.

        Args:
            model_name: Model name to search for

        Returns:
            dict: OneCore model data or None
        """
        if not model_name:
            return None

        try:
            models = self.api.fetch_component_models(model_name, page=1, limit=1)
            if models and len(models) > 0:
                _logger.info(f"Found existing model in OneCore: {model_name}")
                return models[0]
        except Exception as e:
            _logger.warning(f"Failed to fetch component model from OneCore: {e}")

        return None

    def _build_form_values(self, content, onecore_model):
        """Build form values from AI content and OneCore model data.

        Args:
            content: Parsed AI response content
            onecore_model: Optional OneCore model data

        Returns:
            dict: Form values to update the wizard
        """
        # Initialize values from AI
        form_values = {
            'form_model': content.get('model'),
            'form_serial_number': content.get('serialNumber'),
            'form_estimated_age': content.get('estimatedAge'),
            'form_warranty_months': content.get('warrantyMonths'),
            'form_ncs_code': content.get('ncsCode'),
            'form_confidence': content.get('confidence', 0.0),
            'form_ai_suggested': True,
            'form_state': 'review',
        }

        # Initialize price and technical fields from AI
        form_values['form_specifications'] = content.get('specifications')
        form_values['form_dimensions'] = content.get('dimensions')
        form_values['form_additional_information'] = content.get('additionalInformation')
        form_values['form_coclass_code'] = None
        form_values['form_current_price'] = 0
        form_values['form_current_install_price'] = 0

        if onecore_model:
            # Extract hierarchy from OneCore model
            form_values.update(self._extract_onecore_values(content, onecore_model))
            form_values['form_model_data_loaded'] = True
        else:
            # Use AI values and try to match to hierarchy
            form_values.update(self._extract_ai_values(content))
            form_values['form_model_data_loaded'] = False

        return form_values

    def _extract_onecore_values(self, content, onecore_model):
        """Extract form values from OneCore model data.

        Args:
            content: AI response content (for fallback values)
            onecore_model: OneCore model data

        Returns:
            dict: Form values extracted from OneCore
        """
        subtype_data = onecore_model.get('subtype', {}) or {}
        component_type_data = subtype_data.get('componentType', {}) or {}
        category_data = component_type_data.get('category', {}) or {}

        # Get manufacturer, preferring OneCore unless it's "Unknown"
        manufacturer = onecore_model.get('manufacturer')
        if not manufacturer or manufacturer == 'Unknown':
            manufacturer = content.get('manufacturer')

        values = {
            'form_category': category_data.get('categoryName') or content.get('componentCategory'),
            'form_category_id': category_data.get('id'),
            'form_type': component_type_data.get('typeName') or content.get('componentType'),
            'form_type_id': component_type_data.get('id'),
            'form_subtype': subtype_data.get('subTypeName') or content.get('componentSubtype'),
            'form_subtype_id': subtype_data.get('id'),
            'form_manufacturer': manufacturer,
            'form_current_price': onecore_model.get('currentPrice', 0),
            'form_current_install_price': onecore_model.get('currentInstallPrice', 0),
        }

        # Prefer OneCore technical fields over AI
        if onecore_model.get('dimensions'):
            values['form_dimensions'] = onecore_model.get('dimensions')
        if onecore_model.get('technicalSpecification'):
            values['form_specifications'] = onecore_model.get('technicalSpecification')
        if onecore_model.get('installationInstructions'):
            values['form_additional_information'] = onecore_model.get('installationInstructions')
        if onecore_model.get('coclassCode'):
            values['form_coclass_code'] = onecore_model.get('coclassCode')

        return values

    def _extract_ai_values(self, content):
        """Extract form values from AI content and match to hierarchy.

        Args:
            content: AI response content

        Returns:
            dict: Form values with matched hierarchy IDs
        """
        category = content.get('componentCategory')
        type_name = content.get('componentType')
        subtype = content.get('componentSubtype')

        values = {
            'form_category': category,
            'form_type': type_name,
            'form_subtype': subtype,
            'form_manufacturer': content.get('manufacturer'),
            'form_category_id': None,
            'form_type_id': None,
            'form_subtype_id': None,
        }

        # Try to match AI values to OneCore hierarchy
        if category:
            matches = self.hierarchy_service.match_ai_values_to_hierarchy(
                category, type_name, subtype
            )
            values['form_category_id'] = matches['category_id']
            values['form_type_id'] = matches['type_id']
            values['form_subtype_id'] = matches['subtype_id']

        return values

    def _extract_error_detail(self, exception):
        """Log detailed error and return user-friendly message.

        Args:
            exception: The exception that occurred

        Returns:
            str: User-friendly error message
        """
        _logger.error(f"Exception details: {str(exception)}")
        if hasattr(exception, 'response') and exception.response is not None:
            try:
                _logger.error(f"API Response body: {exception.response.text}")
            except Exception:
                pass
        return "Ett tekniskt fel uppstod"
