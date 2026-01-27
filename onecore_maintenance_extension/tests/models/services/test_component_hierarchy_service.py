# -*- coding: utf-8 -*-
"""Tests for ComponentHierarchyService."""

import json
from unittest.mock import Mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services.component_hierarchy_service import (
    ComponentHierarchyService,
)
from odoo.addons.onecore_maintenance_extension.tests.utils.test_utils import setup_faker


@tagged("onecore")
class TestComponentHierarchyService(TransactionCase):
    """Tests for ComponentHierarchyService."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.mock_api = Mock()

    def _create_service(self):
        """Create service with mocked API."""
        service = ComponentHierarchyService(self.env)
        service._api = self.mock_api
        return service

    def test_hierarchy_load_categories_success(self):
        """Returns categories list from API."""
        service = self._create_service()

        categories = [
            {'id': self.fake.component_category_id(), 'categoryName': self.fake.component_category_name()},
            {'id': self.fake.component_category_id(), 'categoryName': self.fake.component_category_name()},
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
            {'id': self.fake.component_type_id(), 'typeName': self.fake.component_type_name()},
            {'id': self.fake.component_type_id(), 'typeName': self.fake.component_type_name()},
        ]
        self.mock_api.fetch_component_types.return_value = types

        cat_id = self.fake.component_category_id()
        result = service.load_types_for_category(cat_id)

        self.assertEqual(result, types)
        self.mock_api.fetch_component_types.assert_called_once_with(cat_id)

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
            {'id': self.fake.component_subtype_id(), 'subTypeName': self.fake.component_subtype_name()},
            {'id': self.fake.component_subtype_id(), 'subTypeName': self.fake.component_subtype_name()},
        ]
        self.mock_api.fetch_component_subtypes.return_value = subtypes

        type_id = self.fake.component_type_id()
        result = service.load_subtypes_for_type(type_id)

        self.assertEqual(result, subtypes)
        self.mock_api.fetch_component_subtypes.assert_called_once_with(type_id)

    def test_hierarchy_load_subtypes_empty_id(self):
        """Returns empty list when no type_id provided."""
        service = self._create_service()

        result = service.load_subtypes_for_type(None)
        self.assertEqual(result, [])

    def test_hierarchy_get_economic_data_found(self):
        """Extracts lifespan, warranty, depreciation data from subtype."""
        service = self._create_service()

        sub_id = self.fake.component_subtype_id()
        depreciation = self.fake.component_depreciation_price()
        economic = self.fake.component_lifespan_months()
        technical = self.fake.component_lifespan_months()
        replacement = self.fake.component_replacement_interval()

        subtypes_json = json.dumps([
            {
                'id': sub_id,
                'depreciationPrice': depreciation,
                'economicLifespan': economic,
                'technicalLifespan': technical,
                'replacementIntervalMonths': replacement,
            }
        ])

        result = service.get_economic_data_from_subtype(sub_id, subtypes_json)

        self.assertEqual(result['depreciation_price'], depreciation)
        self.assertEqual(result['economic_lifespan'], economic)
        self.assertEqual(result['technical_lifespan'], technical)
        self.assertEqual(result['replacement_interval'], replacement)

    def test_hierarchy_get_economic_data_not_found(self):
        """Returns default values when subtype not in JSON."""
        service = self._create_service()

        subtypes_json = json.dumps([
            {'id': self.fake.component_subtype_id(), 'economicLifespan': 120}
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

        cat_id = self.fake.component_category_id()
        cat_name = self.fake.component_category_name()
        type_id = self.fake.component_type_id()
        type_name = self.fake.component_type_name()
        sub_id = self.fake.component_subtype_id()
        sub_name = self.fake.component_subtype_name()
        manufacturer = self.fake.component_manufacturer()
        model_name = self.fake.component_model_name()

        onecore_model = self.fake.onecore_model_response(
            modelName=model_name,
            manufacturer=manufacturer,
            category_id=cat_id,
            category_name=cat_name,
            type_id=type_id,
            type_name=type_name,
            subtype_id=sub_id,
            subtype_name=sub_name,
        )
        self.mock_api.fetch_component_models.return_value = [onecore_model]

        result = service.load_model_data(model_name)

        self.assertEqual(result['category_name'], cat_name)
        self.assertEqual(result['category_id'], cat_id)
        self.assertEqual(result['type_name'], type_name)
        self.assertEqual(result['type_id'], type_id)
        self.assertEqual(result['subtype_name'], sub_name)
        self.assertEqual(result['subtype_id'], sub_id)
        self.assertEqual(result['manufacturer'], manufacturer)

    def test_hierarchy_load_model_data_not_found(self):
        """Returns None when model not found."""
        service = self._create_service()

        self.mock_api.fetch_component_models.return_value = []

        result = service.load_model_data(self.fake.component_model_name())

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

        cat_id = self.fake.component_category_id()
        cat_name = self.fake.component_category_name()
        type_id = self.fake.component_type_id()
        type_name = self.fake.component_type_name()
        sub_id = self.fake.component_subtype_id()
        sub_name = self.fake.component_subtype_name()

        categories = [{'id': cat_id, 'categoryName': cat_name}]
        types = [{'id': type_id, 'typeName': type_name}]
        subtypes = [{'id': sub_id, 'subTypeName': sub_name}]

        self.mock_api.fetch_component_categories.return_value = categories
        self.mock_api.fetch_component_types.return_value = types
        self.mock_api.fetch_component_subtypes.return_value = subtypes

        result = service.match_ai_values_to_hierarchy(cat_name, type_name, sub_name)

        self.assertEqual(result['category_id'], cat_id)
        self.assertEqual(result['type_id'], type_id)
        self.assertEqual(result['subtype_id'], sub_id)

    def test_hierarchy_match_ai_values_partial_match(self):
        """Returns only category_id when type not found."""
        service = self._create_service()

        cat_id = self.fake.component_category_id()
        cat_name = self.fake.component_category_name()
        type_name = self.fake.component_type_name()

        categories = [{'id': cat_id, 'categoryName': cat_name}]
        types = [{'id': self.fake.component_type_id(), 'typeName': type_name}]

        self.mock_api.fetch_component_categories.return_value = categories
        self.mock_api.fetch_component_types.return_value = types

        result = service.match_ai_values_to_hierarchy(cat_name, 'NonExistentType', 'NonExistentSubtype')

        self.assertEqual(result['category_id'], cat_id)
        self.assertIsNone(result['type_id'])
        self.assertIsNone(result['subtype_id'])

    def test_hierarchy_match_ai_values_no_category(self):
        """Returns all None when no category provided."""
        service = self._create_service()

        result = service.match_ai_values_to_hierarchy(
            None,
            self.fake.component_type_name(),
            self.fake.component_subtype_name(),
        )

        self.assertIsNone(result['category_id'])
        self.assertIsNone(result['type_id'])
        self.assertIsNone(result['subtype_id'])
