# -*- coding: utf-8 -*-
"""Tests for MaintenanceComponentWizard TransientModel."""

import base64
import json
from datetime import date
from unittest.mock import Mock, patch, MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

from odoo.addons.onecore_maintenance_extension.tests.utils.test_utils import (
    setup_faker,
    create_maintenance_request,
    create_rental_property,
    create_component_wizard,
)

WIZARD_PATH = (
    'odoo.addons.onecore_maintenance_extension.models.maintenance_component_wizard'
)


# ==================== Computed Fields ====================


@tagged("onecore")
class TestWizardComputedFields(TransactionCase):
    """Tests for computed fields on the wizard."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_has_image_true_when_image_set(self):
        """has_image is True when temp_image contains data."""
        wizard = create_component_wizard(
            self.env,
            temp_image=base64.b64encode(b'fake_image'),
        )
        self.assertTrue(wizard.has_image)

    def test_has_image_false_when_no_image(self):
        """has_image is False when temp_image is empty."""
        wizard = create_component_wizard(self.env)
        self.assertFalse(wizard.has_image)

    def test_current_value_with_valid_depreciation_inputs(self):
        """form_current_value computed from price, lifespan, and date."""
        wizard = create_component_wizard(
            self.env,
            form_current_price=10000.0,
            form_economic_lifespan=120,
            form_installation_date=date(2024, 1, 1),
        )
        self.assertIsInstance(wizard.form_current_value, float)

    def test_current_value_zero_when_no_price(self):
        """form_current_value is 0 when form_current_price is 0."""
        wizard = create_component_wizard(
            self.env,
            form_current_price=0,
            form_economic_lifespan=120,
            form_installation_date=date(2024, 1, 1),
        )
        self.assertEqual(wizard.form_current_value, 0.0)

    def test_current_value_equals_price_when_no_lifespan(self):
        """form_current_value equals price when lifespan is 0."""
        wizard = create_component_wizard(
            self.env,
            form_current_price=5000.0,
            form_economic_lifespan=0,
            form_installation_date=date(2024, 1, 1),
        )
        self.assertEqual(wizard.form_current_value, 5000.0)

    def test_current_value_equals_price_when_no_date(self):
        """form_current_value equals price when installation_date is not set."""
        wizard = create_component_wizard(
            self.env,
            form_current_price=5000.0,
            form_economic_lifespan=120,
        )
        self.assertEqual(wizard.form_current_value, 5000.0)


# ==================== Onchange Handlers ====================


@tagged("onecore")
class TestWizardOnchangeHandlers(TransactionCase):
    """Tests for onchange methods on the wizard."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_onchange_category_id_loads_types(self):
        """Setting category_id loads types and clears type/subtype."""
        wizard = create_component_wizard(self.env)
        cat_id = self.fake.component_category_id()
        types_list = [
            {'id': self.fake.component_type_id(), 'name': self.fake.component_type_name()}
        ]

        wizard.form_category_id = cat_id
        wizard.form_category = self.fake.component_category_name()

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.load_types_for_category.return_value = types_list
            wizard._onchange_form_category_id()

        self.assertEqual(json.loads(wizard.available_types_json), types_list)
        self.assertFalse(wizard.form_type_id)
        self.assertFalse(wizard.form_subtype_id)

    def test_onchange_category_id_empty_clears_fields(self):
        """Clearing category_id resets types and subtypes."""
        wizard = create_component_wizard(self.env)
        wizard.form_category_id = False

        wizard._onchange_form_category_id()

        self.assertEqual(wizard.available_types_json, '[]')
        self.assertEqual(wizard.available_subtypes_json, '[]')

    def test_onchange_type_id_loads_subtypes(self):
        """Setting type_id loads subtypes."""
        wizard = create_component_wizard(self.env)
        type_id = self.fake.component_type_id()
        subtypes_list = [
            {'id': self.fake.component_subtype_id(), 'name': self.fake.component_subtype_name()}
        ]

        wizard.form_type_id = type_id
        wizard.form_type = self.fake.component_type_name()

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.load_subtypes_for_type.return_value = subtypes_list
            wizard._onchange_form_type_id()

        self.assertEqual(json.loads(wizard.available_subtypes_json), subtypes_list)
        self.assertFalse(wizard.form_subtype_id)

    def test_onchange_type_id_empty_clears_subtypes(self):
        """Clearing type_id resets subtypes."""
        wizard = create_component_wizard(self.env)
        wizard.form_type_id = False

        wizard._onchange_form_type_id()

        self.assertEqual(wizard.available_subtypes_json, '[]')

    def test_onchange_subtype_id_loads_economic_data(self):
        """Setting subtype_id populates economic fields."""
        wizard = create_component_wizard(self.env)
        subtype_id = self.fake.component_subtype_id()
        economic_data = {
            'depreciation_price': 300.0,
            'economic_lifespan': 120,
            'technical_lifespan': 180,
            'replacement_interval': 60,
        }

        wizard.form_subtype_id = subtype_id

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.get_economic_data_from_subtype.return_value = economic_data
            wizard._onchange_form_subtype_id_economics()

        self.assertEqual(wizard.form_depreciation_price, 300.0)
        self.assertEqual(wizard.form_economic_lifespan, 120)
        self.assertEqual(wizard.form_technical_lifespan, 180)
        self.assertEqual(wizard.form_replacement_interval, 60)

    def test_onchange_model_fills_form_from_onecore(self):
        """Setting form_model auto-fills fields from OneCore model data."""
        wizard = create_component_wizard(self.env)
        model_name = self.fake.component_model_name()
        model_data = {
            'category_name': self.fake.component_category_name(),
            'category_id': self.fake.component_category_id(),
            'type_name': self.fake.component_type_name(),
            'type_id': self.fake.component_type_id(),
            'subtype_name': self.fake.component_subtype_name(),
            'subtype_id': self.fake.component_subtype_id(),
            'manufacturer': self.fake.component_manufacturer(),
            'warranty_months': 24,
            'current_price': 5000.0,
            'current_install_price': 500.0,
            'dimensions': self.fake.component_dimensions(),
            'technical_specification': self.fake.component_specifications(),
            'installation_instructions': 'Test instructions',
            'coclass_code': 'CC123',
        }

        wizard.form_model = model_name

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.load_model_data.return_value = model_data
            wizard._onchange_form_model()

        self.assertEqual(wizard.form_category, model_data['category_name'])
        self.assertEqual(wizard.form_category_id, model_data['category_id'])
        self.assertEqual(wizard.form_type, model_data['type_name'])
        self.assertEqual(wizard.form_type_id, model_data['type_id'])
        self.assertEqual(wizard.form_subtype, model_data['subtype_name'])
        self.assertEqual(wizard.form_subtype_id, model_data['subtype_id'])
        self.assertEqual(wizard.form_manufacturer, model_data['manufacturer'])
        self.assertEqual(wizard.form_warranty_months, 24)
        self.assertEqual(wizard.form_current_price, 5000.0)
        self.assertEqual(wizard.form_current_install_price, 500.0)
        self.assertEqual(wizard.form_dimensions, model_data['dimensions'])
        self.assertEqual(wizard.form_specifications, model_data['technical_specification'])
        self.assertEqual(wizard.form_additional_information, 'Test instructions')
        self.assertEqual(wizard.form_coclass_code, 'CC123')
        self.assertTrue(wizard.form_model_data_loaded)

    def test_onchange_model_not_found_sets_loaded_false(self):
        """When model not found, sets form_model_data_loaded to False."""
        wizard = create_component_wizard(self.env)
        wizard.form_model = 'NonexistentModel'

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.load_model_data.return_value = None
            wizard._onchange_form_model()

        self.assertFalse(wizard.form_model_data_loaded)

    def test_onchange_model_empty_returns_early(self):
        """Empty form_model does not call the service."""
        wizard = create_component_wizard(self.env)
        wizard.form_model = False

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            wizard._onchange_form_model()
            MockService.assert_not_called()

    def test_onchange_model_skips_unknown_manufacturer(self):
        """Manufacturer 'Unknown' from OneCore is not set on the form."""
        wizard = create_component_wizard(self.env)
        wizard.form_model = self.fake.component_model_name()

        model_data = {
            'manufacturer': 'Unknown',
            'category_name': self.fake.component_category_name(),
            'category_id': self.fake.component_category_id(),
        }

        with patch(f'{WIZARD_PATH}.ComponentHierarchyService') as MockService:
            MockService.return_value.load_model_data.return_value = model_data
            wizard._onchange_form_model()

        self.assertFalse(wizard.form_manufacturer)


# ==================== Action: Analyze Images ====================


@tagged("onecore")
class TestWizardActionAnalyzeImages(TransactionCase):
    """Tests for action_analyze_images."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_analyze_images_raises_without_image(self):
        """Raises UserError when no image is uploaded."""
        wizard = create_component_wizard(self.env)

        with self.assertRaises(UserError):
            wizard.action_analyze_images()

    def test_analyze_images_success_transitions_to_review(self):
        """On success, form_state changes to review and fields are populated."""
        wizard = create_component_wizard(
            self.env,
            temp_image=base64.b64encode(b'fake_image'),
        )

        ai_result = {
            'form_state': 'review',
            'form_ai_suggested': True,
            'form_model': self.fake.component_model_name(),
            'form_manufacturer': self.fake.component_manufacturer(),
            'form_confidence': 0.85,
        }

        with patch(f'{WIZARD_PATH}.ComponentAIAnalysisService') as MockService:
            MockService.return_value.analyze_images.return_value = ai_result
            wizard.action_analyze_images()

        self.assertEqual(wizard.form_state, 'review')
        self.assertTrue(wizard.form_ai_suggested)

    def test_analyze_images_error_sets_api_error_flag(self):
        """On error, api_error is True and error_message is set."""
        wizard = create_component_wizard(
            self.env,
            temp_image=base64.b64encode(b'fake_image'),
        )

        error_result = {
            'error': True,
            'error_message': 'AI service unavailable',
        }

        with patch(f'{WIZARD_PATH}.ComponentAIAnalysisService') as MockService:
            MockService.return_value.analyze_images.return_value = error_result
            wizard.action_analyze_images()

        self.assertTrue(wizard.api_error)
        self.assertEqual(wizard.error_message, 'AI service unavailable')
        self.assertEqual(wizard.form_state, 'review')

    def test_analyze_images_preserves_images_after_write(self):
        """Images are preserved in the wizard after analysis."""
        image_data = base64.b64encode(b'fake_image')
        additional_data = base64.b64encode(b'additional_image')

        wizard = create_component_wizard(
            self.env,
            temp_image=image_data,
            temp_additional_image=additional_data,
        )

        ai_result = {
            'form_state': 'review',
            'form_ai_suggested': True,
            'form_confidence': 0.9,
        }

        with patch(f'{WIZARD_PATH}.ComponentAIAnalysisService') as MockService:
            MockService.return_value.analyze_images.return_value = ai_result
            wizard.action_analyze_images()

        self.assertTrue(wizard.temp_image)
        self.assertTrue(wizard.temp_additional_image)

    def test_analyze_images_returns_wizard_action(self):
        """Returns action dict to reload wizard."""
        wizard = create_component_wizard(
            self.env,
            temp_image=base64.b64encode(b'fake_image'),
        )

        ai_result = {
            'form_state': 'review',
            'form_ai_suggested': True,
            'form_confidence': 0.9,
        }

        with patch(f'{WIZARD_PATH}.ComponentAIAnalysisService') as MockService:
            MockService.return_value.analyze_images.return_value = ai_result
            result = wizard.action_analyze_images()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')
        self.assertEqual(result['res_id'], wizard.id)


# ==================== Action: Manual Entry ====================


@tagged("onecore")
class TestWizardActionManualEntry(TransactionCase):
    """Tests for action_manual_entry."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_manual_entry_sets_review_state(self):
        """form_state becomes review."""
        wizard = create_component_wizard(self.env)
        wizard.action_manual_entry()
        self.assertEqual(wizard.form_state, 'review')

    def test_manual_entry_clears_form_fields(self):
        """Form fields are reset."""
        wizard = create_component_wizard(
            self.env,
            form_model=self.fake.component_model_name(),
            form_manufacturer=self.fake.component_manufacturer(),
        )
        wizard.action_manual_entry()

        self.assertFalse(wizard.form_model)
        self.assertFalse(wizard.form_manufacturer)
        self.assertFalse(wizard.form_type)
        self.assertFalse(wizard.form_subtype)
        self.assertFalse(wizard.form_category)

    def test_manual_entry_sets_ai_suggested_false(self):
        """form_ai_suggested is False."""
        wizard = create_component_wizard(self.env)
        wizard.action_manual_entry()
        self.assertFalse(wizard.form_ai_suggested)

    def test_manual_entry_returns_wizard_action(self):
        """Returns action dict to reload wizard."""
        wizard = create_component_wizard(self.env)
        result = wizard.action_manual_entry()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')


# ==================== Action: Add To List ====================


@tagged("onecore")
class TestWizardActionAddToList(TransactionCase):
    """Tests for action_add_to_list."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_add_to_list_raises_without_room_id(self):
        """Raises UserError when form_room_id is empty."""
        wizard = create_component_wizard(
            self.env,
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
        )

        with self.assertRaises(UserError):
            wizard.action_add_to_list()

    def test_add_to_list_raises_without_subtype_id(self):
        """Raises UserError when form_subtype_id is empty."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_serial_number=self.fake.component_serial_number(),
        )

        with self.assertRaises(UserError):
            wizard.action_add_to_list()

    def test_add_to_list_raises_without_serial_number(self):
        """Raises UserError when form_serial_number is empty."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
        )

        with self.assertRaises(UserError):
            wizard.action_add_to_list()

    def test_add_to_list_success_creates_component(self):
        """Calls create_component and reloads components on success."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
            form_model=self.fake.component_model_name(),
        )

        comp_id = self.fake.component_instance_id()

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            mock_service = MockService.return_value
            mock_service.create_component.return_value = {'id': comp_id}
            mock_service.upload_component_images.return_value = {
                'success_count': 0, 'errors': []
            }

            with patch.object(
                type(wizard), '_load_onecore_components', return_value=None
            ):
                wizard.action_add_to_list()

            mock_service.create_component.assert_called_once()

    def test_add_to_list_uploads_images_on_success(self):
        """Uploads images when component is created successfully."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
            temp_image=base64.b64encode(b'main_image'),
        )

        comp_id = self.fake.component_instance_id()

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            mock_service = MockService.return_value
            mock_service.create_component.return_value = {'id': comp_id}
            mock_service.upload_component_images.return_value = {
                'success_count': 1, 'errors': []
            }

            with patch.object(
                type(wizard), '_load_onecore_components', return_value=None
            ):
                wizard.action_add_to_list()

            mock_service.upload_component_images.assert_called_once()
            call_args = mock_service.upload_component_images.call_args
            self.assertEqual(call_args[0][0], comp_id)

    def test_add_to_list_resets_form_after_success(self):
        """After success, form_state resets to upload."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
        )

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            mock_service = MockService.return_value
            mock_service.create_component.return_value = {'id': 'comp-1'}
            mock_service.upload_component_images.return_value = {
                'success_count': 0, 'errors': []
            }

            with patch.object(
                type(wizard), '_load_onecore_components', return_value=None
            ):
                wizard.action_add_to_list()

        self.assertEqual(wizard.form_state, 'upload')

    def test_add_to_list_api_error_raises_user_error(self):
        """Exception from service raises UserError."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
        )

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.create_component.side_effect = Exception("API error")

            with self.assertRaises(UserError):
                wizard.action_add_to_list()

    def test_add_to_list_subtype_api_error_specific_message(self):
        """Error containing componentSubtypeId shows subtype-specific message."""
        wizard = create_component_wizard(
            self.env,
            form_room_id=self.fake.component_room_id(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
        )

        error = Exception("Invalid componentSubtypeId")

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.create_component.side_effect = error

            with self.assertRaises(UserError) as ctx:
                wizard.action_add_to_list()

            self.assertIn('Undertyp saknas', str(ctx.exception))


# ==================== CRUD and Helpers ====================


@tagged("onecore")
class TestWizardCrudAndHelpers(TransactionCase):
    """Tests for create(), reload, helpers."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_create_calls_load_onecore_components(self):
        """create() calls _load_onecore_components for each wizard."""
        with patch.object(
            type(self.env['maintenance.component.wizard']),
            '_load_onecore_components',
        ) as mock_load:
            self.env['maintenance.component.wizard'].create({})
            mock_load.assert_called_once()

    def test_create_without_maintenance_request_skips_api(self):
        """Without maintenance_request_id, _load_onecore_components returns early."""
        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            with patch.object(
                type(self.env['maintenance.component.wizard']),
                '_load_onecore_components',
                wraps=None,
            ):
                wizard = self.env['maintenance.component.wizard'].create({})

            # The actual service should not be called when no request is set
            self.assertFalse(wizard.maintenance_request_id)

    def test_reload_components_unlinks_and_reloads(self):
        """reload_components clears lines then reloads."""
        wizard = create_component_wizard(self.env)

        with patch.object(
            type(wizard), '_load_onecore_components', return_value=None
        ) as mock_load:
            wizard.reload_components()
            mock_load.assert_called_once()

    def test_load_onecore_components_creates_lines(self):
        """When API returns component data, creates component line records."""
        request = create_maintenance_request(self.env, space_caption='Lägenhet')
        rental_prop = create_rental_property(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id='rental-123',
        )
        request.write({'rental_property_id': rental_prop.id})

        line_data = self.fake.component_line_data()

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            mock_service = MockService.return_value
            mock_service.load_components_for_residence.return_value = (
                json.dumps([{'id': 'room-1', 'name': 'Kök'}]),
                json.dumps([]),
                [line_data],
            )
            wizard = self.env['maintenance.component.wizard'].create({
                'maintenance_request_id': request.id,
            })

        self.assertEqual(len(wizard.component_ids), 1)
        self.assertEqual(wizard.component_ids[0].model, line_data['model'])

    def test_extract_component_instance_id_direct(self):
        """Returns id from top-level dict."""
        wizard = create_component_wizard(self.env)
        result = wizard._extract_component_instance_id({'id': 'comp-123'})
        self.assertEqual(result, 'comp-123')

    def test_extract_component_instance_id_content_wrapper(self):
        """Returns id from content wrapper."""
        wizard = create_component_wizard(self.env)
        result = wizard._extract_component_instance_id({'content': {'id': 'comp-456'}})
        self.assertEqual(result, 'comp-456')

    def test_extract_component_instance_id_nested(self):
        """Returns id from nested component key."""
        wizard = create_component_wizard(self.env)
        result = wizard._extract_component_instance_id(
            {'component': {'id': 'comp-789'}}
        )
        self.assertEqual(result, 'comp-789')

    def test_extract_component_instance_id_none_result(self):
        """Returns None for None input."""
        wizard = create_component_wizard(self.env)
        result = wizard._extract_component_instance_id(None)
        self.assertIsNone(result)

    def test_extract_component_instance_id_no_id(self):
        """Returns None when no id found."""
        wizard = create_component_wizard(self.env)
        result = wizard._extract_component_instance_id({'status': 'ok'})
        self.assertIsNone(result)

    def test_upload_images_collects_all_image_fields(self):
        """Collects temp_image, temp_additional_image, extra images."""
        wizard = create_component_wizard(
            self.env,
            temp_image=base64.b64encode(b'img1'),
            temp_additional_image=base64.b64encode(b'img2'),
            form_extra_image_1=base64.b64encode(b'img3'),
            form_extra_image_2=base64.b64encode(b'img4'),
        )

        mock_service = Mock()
        mock_service.upload_component_images.return_value = {
            'success_count': 4, 'errors': []
        }

        wizard._upload_images_to_component(mock_service, 'comp-123')

        mock_service.upload_component_images.assert_called_once()
        images_arg = mock_service.upload_component_images.call_args[0][1]
        self.assertEqual(len(images_arg), 4)

    def test_upload_images_skips_when_no_images(self):
        """Returns early when all image fields are empty."""
        wizard = create_component_wizard(self.env)

        mock_service = Mock()
        wizard._upload_images_to_component(mock_service, 'comp-123')

        mock_service.upload_component_images.assert_not_called()

    def test_get_form_data_maps_all_fields(self):
        """Returns dict with all expected keys."""
        wizard = create_component_wizard(
            self.env,
            form_model=self.fake.component_model_name(),
            form_subtype_id=self.fake.component_subtype_id(),
            form_serial_number=self.fake.component_serial_number(),
            form_warranty_months=24,
            form_current_price=5000.0,
            form_manufacturer=self.fake.component_manufacturer(),
            form_condition='GOOD',
        )

        form_data = wizard._get_form_data()

        self.assertEqual(form_data['model'], wizard.form_model)
        self.assertEqual(form_data['subtype_id'], wizard.form_subtype_id)
        self.assertEqual(form_data['serial_number'], wizard.form_serial_number)
        self.assertEqual(form_data['warranty_months'], 24)
        self.assertEqual(form_data['current_price'], 5000.0)
        self.assertEqual(form_data['manufacturer'], wizard.form_manufacturer)
        self.assertEqual(form_data['condition'], 'GOOD')
        self.assertIn('specifications', form_data)
        self.assertIn('dimensions', form_data)
        self.assertIn('additional_information', form_data)
        self.assertIn('ncs_code', form_data)
        self.assertIn('installation_date', form_data)
        self.assertIn('depreciation_price', form_data)
        self.assertIn('economic_lifespan', form_data)
        self.assertIn('current_install_price', form_data)

    def test_reset_form_fields_clears_all(self):
        """After reset, form_state is upload and fields are cleared."""
        wizard = create_component_wizard(
            self.env,
            form_model=self.fake.component_model_name(),
            form_serial_number=self.fake.component_serial_number(),
            form_state='review',
        )

        wizard._reset_form_fields()

        self.assertEqual(wizard.form_state, 'upload')
        self.assertFalse(wizard.form_model)
        self.assertFalse(wizard.form_serial_number)
        self.assertFalse(wizard.form_manufacturer)
        self.assertFalse(wizard.form_category_id)
        self.assertFalse(wizard.form_type_id)
        self.assertFalse(wizard.form_subtype_id)
        self.assertEqual(wizard.form_current_price, 0)
        self.assertEqual(wizard.form_confidence, 0.0)
        self.assertFalse(wizard.form_ai_suggested)

    def test_search_component_models_delegates_to_service(self):
        """Delegates to ComponentOneCoreService.search_models."""
        expected = [{'modelName': 'Test', 'label': 'Test (Mfg)'}]

        with patch(f'{WIZARD_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.search_models.return_value = expected

            result = self.env['maintenance.component.wizard'].search_component_models(
                'Test'
            )

        self.assertEqual(result, expected)


# ==================== Action: Reset and Retry ====================


@tagged("onecore")
class TestWizardActionResetAndRetry(TransactionCase):
    """Tests for action_reset_form, action_retry_upload, action_save_all."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()

    def test_action_reset_form_resets_state(self):
        """Resets form_state to upload and clears fields."""
        wizard = create_component_wizard(self.env, form_state='review')
        wizard.action_reset_form()

        self.assertEqual(wizard.form_state, 'upload')

    def test_action_reset_form_returns_wizard_action(self):
        """Returns action dict with res_model and res_id."""
        wizard = create_component_wizard(self.env)
        result = wizard.action_reset_form()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')
        self.assertEqual(result['res_id'], wizard.id)

    def test_action_retry_upload_clears_error(self):
        """Sets form_state to upload and clears error fields."""
        wizard = create_component_wizard(
            self.env,
            form_state='review',
            api_error=True,
            error_message='Some error',
        )

        wizard.action_retry_upload()

        self.assertEqual(wizard.form_state, 'upload')
        self.assertFalse(wizard.api_error)
        self.assertEqual(wizard.error_message, '')

    def test_action_retry_upload_returns_wizard_action(self):
        """Returns action dict."""
        wizard = create_component_wizard(self.env)
        result = wizard.action_retry_upload()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')

    def test_action_save_all_returns_close_action(self):
        """Returns window close action."""
        wizard = create_component_wizard(self.env)
        result = wizard.action_save_all()

        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})
