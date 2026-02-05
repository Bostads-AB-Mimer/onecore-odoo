"""Service for component category/type/subtype hierarchy management."""

import json
import logging

from ....onecore_api import core_api

_logger = logging.getLogger(__name__)


class ComponentHierarchyService:
    """Service for handling component hierarchy (category/type/subtype) operations."""

    def __init__(self, env):
        self.env = env
        self._api = None

    @property
    def api(self):
        """Lazy-load the API client."""
        if self._api is None:
            self._api = core_api.CoreApi(self.env)
        return self._api

    def load_categories(self):
        """Fetch all component categories from OneCore.

        Returns:
            list: List of category dicts or empty list on error
        """
        try:
            categories = self.api.fetch_component_categories()
            return categories or []
        except Exception as e:
            _logger.warning(f"Failed to fetch component categories: {e}")
            return []

    def load_types_for_category(self, category_id):
        """Fetch types for a given category.

        Args:
            category_id: The category ID to fetch types for

        Returns:
            list: List of type dicts or empty list on error
        """
        if not category_id:
            return []

        try:
            types = self.api.fetch_component_types(category_id)
            return types or []
        except Exception as e:
            _logger.warning(f"Failed to fetch component types: {e}")
            return []

    def load_subtypes_for_type(self, type_id):
        """Fetch subtypes for a given type.

        Args:
            type_id: The type ID to fetch subtypes for

        Returns:
            list: List of subtype dicts or empty list on error
        """
        if not type_id:
            return []

        try:
            subtypes = self.api.fetch_component_subtypes(type_id)
            return subtypes or []
        except Exception as e:
            _logger.warning(f"Failed to fetch component subtypes: {e}")
            return []

    def get_economic_data_from_subtype(self, subtype_id, available_subtypes_json):
        """Extract economic data from a subtype.

        Args:
            subtype_id: The subtype ID to get economic data for
            available_subtypes_json: JSON string of available subtypes

        Returns:
            dict: Economic data fields or default values
        """
        default_data = {
            'depreciation_price': 0,
            'economic_lifespan': 0,
            'technical_lifespan': 0,
            'replacement_interval': 0,
        }

        if not subtype_id:
            return default_data

        subtypes = json.loads(available_subtypes_json or '[]')
        subtype = next(
            (s for s in subtypes if str(s.get('id')) == str(subtype_id)),
            None
        )

        if subtype:
            return {
                'depreciation_price': subtype.get('depreciationPrice', 0) or 0,
                'economic_lifespan': subtype.get('economicLifespan', 0) or 0,
                'technical_lifespan': subtype.get('technicalLifespan', 0) or 0,
                'replacement_interval': subtype.get('replacementIntervalMonths', 0) or 0,
            }

        return default_data

    def load_model_data(self, model_name):
        """Load full model data from OneCore including hierarchy info.

        Args:
            model_name: The model name to search for

        Returns:
            dict: Model data with extracted hierarchy or None if not found
        """
        if not model_name:
            return None

        try:
            models = self.api.fetch_component_models(model_name, page=1, limit=1)
            if models and len(models) > 0:
                onecore_model = models[0]
                return self._extract_model_data(onecore_model)
            return None
        except Exception as e:
            _logger.warning(f"Failed to fetch component model from OneCore: {e}")
            return None

    def _extract_model_data(self, onecore_model):
        """Extract and structure model data from OneCore response.

        Args:
            onecore_model: Raw model data from OneCore API

        Returns:
            dict: Structured model data
        """
        subtype_data = onecore_model.get('subtype', {}) or {}
        component_type_data = subtype_data.get('componentType', {}) or {}
        category_data = component_type_data.get('category', {}) or {}

        return {
            'category_name': category_data.get('categoryName'),
            'category_id': category_data.get('id'),
            'type_name': component_type_data.get('typeName'),
            'type_id': component_type_data.get('id'),
            'subtype_name': subtype_data.get('subTypeName'),
            'subtype_id': subtype_data.get('id'),
            'manufacturer': onecore_model.get('manufacturer'),
            'warranty_months': onecore_model.get('warrantyMonths'),
            'current_price': onecore_model.get('currentPrice'),
            'current_install_price': onecore_model.get('currentInstallPrice'),
            'dimensions': onecore_model.get('dimensions'),
            'technical_specification': onecore_model.get('technicalSpecification'),
            'installation_instructions': onecore_model.get('installationInstructions'),
            'coclass_code': onecore_model.get('coclassCode'),
        }

    def match_ai_values_to_hierarchy(self, category_name, type_name, subtype_name):
        """Match AI-suggested values to OneCore category/type/subtype IDs.

        Args:
            category_name: Category name from AI
            type_name: Type name from AI
            subtype_name: Subtype name from AI

        Returns:
            dict: Matched IDs and available options JSON
        """
        result = {
            'category_id': None,
            'type_id': None,
            'subtype_id': None,
            'available_types_json': '[]',
            'available_subtypes_json': '[]',
        }

        if not category_name:
            return result

        try:
            categories = self.load_categories()
            if not categories:
                return result

            matched_cat = next(
                (c for c in categories if c.get('categoryName') == category_name),
                None
            )
            if not matched_cat:
                return result

            result['category_id'] = matched_cat.get('id')

            # Load types for matched category
            types = self.load_types_for_category(result['category_id'])
            result['available_types_json'] = json.dumps(types)

            if types and type_name:
                matched_type = next(
                    (t for t in types if t.get('typeName') == type_name),
                    None
                )
                if matched_type:
                    result['type_id'] = matched_type.get('id')

                    # Load subtypes for matched type
                    subtypes = self.load_subtypes_for_type(result['type_id'])
                    result['available_subtypes_json'] = json.dumps(subtypes)

                    if subtypes and subtype_name:
                        matched_subtype = next(
                            (s for s in subtypes if s.get('subTypeName') == subtype_name),
                            None
                        )
                        if matched_subtype:
                            result['subtype_id'] = matched_subtype.get('id')

        except Exception as e:
            _logger.warning(f"Failed to match AI values to OneCore: {e}")

        return result
