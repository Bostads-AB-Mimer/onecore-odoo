# -*- coding: utf-8 -*-
"""Tests for MaintenanceComponentLine TransientModel."""

import base64
import json
from datetime import date
from unittest.mock import Mock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

from odoo.addons.onecore_maintenance_extension.tests.utils.test_utils import (
    setup_faker,
    create_component_wizard,
    create_component_line,
)

LINE_PATH = (
    'odoo.addons.onecore_maintenance_extension.models.maintenance_component_line'
)


# ==================== Computed Fields ====================


@tagged("onecore")
class TestComponentLineComputedFields(TransactionCase):
    """Tests for computed fields on the component line."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.wizard = create_component_wizard(self.env)

    def test_has_images_true_with_urls(self):
        """has_images is True when image_urls_json contains URLs."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            image_urls_json=json.dumps(['https://example.com/img1.jpg']),
        )
        self.assertTrue(line.has_images)

    def test_has_images_false_with_empty_array(self):
        """has_images is False when image_urls_json is empty array."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            image_urls_json='[]',
        )
        self.assertFalse(line.has_images)

    def test_has_images_false_with_invalid_json(self):
        """has_images is False when image_urls_json is invalid JSON."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            image_urls_json='not-json',
        )
        self.assertFalse(line.has_images)

    def test_has_images_false_with_none(self):
        """has_images is False when image_urls_json is falsy."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            image_urls_json=False,
        )
        self.assertFalse(line.has_images)

    def test_current_value_with_depreciation(self):
        """current_value computed via linear depreciation."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            price_at_purchase=10000.0,
            economic_lifespan=120,
            installation_date=date(2024, 1, 1),
        )
        self.assertIsInstance(line.current_value, float)

    def test_current_value_zero_without_price(self):
        """current_value is 0 when price_at_purchase is 0."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            price_at_purchase=0,
            economic_lifespan=120,
            installation_date=date(2024, 1, 1),
        )
        self.assertEqual(line.current_value, 0.0)


# ==================== Action: Save Component ====================


@tagged("onecore")
class TestComponentLineActionSave(TransactionCase):
    """Tests for action_save_component."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.wizard = create_component_wizard(self.env)

    def test_save_raises_without_onecore_id(self):
        """Raises UserError when onecore_component_id is empty."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            onecore_component_id=False,
        )

        with self.assertRaises(UserError):
            line.action_save_component()

    def test_save_raises_without_model_id(self):
        """Raises UserError when model_id is empty."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            model_id=False,
        )

        with self.assertRaises(UserError):
            line.action_save_component()

    def test_save_raises_without_room_id(self):
        """Raises UserError when room_id is empty."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            room_id=False,
        )

        with self.assertRaises(UserError):
            line.action_save_component()

    def test_save_builds_correct_payload(self):
        """Payload maps Odoo fields to API field names."""
        serial = self.fake.component_serial_number()
        line = create_component_line(
            self.env,
            self.wizard.id,
            serial_number=serial,
            condition='GOOD',
            warranty_months=24,
            price_at_purchase=5000.0,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}
            mock_api.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_save_component()

            mock_api.update_component.assert_called_once()
            payload = mock_api.update_component.call_args[0][1]

            self.assertEqual(payload['modelId'], line.model_id)
            self.assertEqual(payload['condition'], 'GOOD')
            self.assertEqual(payload['serialNumber'], serial)
            self.assertEqual(payload['warrantyMonths'], 24)
            self.assertEqual(payload['priceAtPurchase'], 5000.0)

    def test_save_calls_update_component_api(self):
        """Calls api.update_component with component ID."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}
            mock_api.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_save_component()

            mock_api.update_component.assert_called_once_with(
                line.onecore_component_id,
                mock_api.update_component.call_args[0][1],
            )

    def test_save_calls_update_installation_when_present(self):
        """Calls update_component_installation when installation_id is set."""
        inst_id = self.fake.component_installation_id()
        comp_id = self.fake.component_instance_id()
        room_id = self.fake.component_room_id()

        line = create_component_line(
            self.env,
            self.wizard.id,
            installation_id=inst_id,
            onecore_component_id=comp_id,
            room_id=room_id,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}
            mock_api.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_save_component()

            mock_api.update_component_installation.assert_called_once()
            inst_payload = mock_api.update_component_installation.call_args[0][1]
            self.assertEqual(inst_payload['componentId'], comp_id)
            self.assertEqual(inst_payload['spaceId'], room_id)
            self.assertEqual(inst_payload['spaceType'], 'PropertyObject')

    def test_save_skips_installation_update_without_installation_id(self):
        """Does not call update_component_installation when no installation_id."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            installation_id=False,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_save_component()

            mock_api.update_component_installation.assert_not_called()

    def test_save_uploads_new_images(self):
        """Uploads new images when set."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            new_image_1=base64.b64encode(b'new_img'),
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}
            mock_api.update_component_installation.return_value = {}

            with patch(f'{LINE_PATH}.ComponentOneCoreService') as MockService:
                MockService.return_value.upload_component_images.return_value = {
                    'success_count': 1, 'errors': []
                }

                with patch.object(
                    type(self.wizard), '_load_onecore_components', return_value=None
                ):
                    line.action_save_component()

                MockService.return_value.upload_component_images.assert_called_once()

    def test_save_returns_wizard_action(self):
        """Returns action dict to reopen parent wizard."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            installation_id=False,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                result = line.action_save_component()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')
        self.assertEqual(result['res_id'], self.wizard.id)

    def test_save_api_error_raises_user_error(self):
        """Exception from API raises UserError."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            MockApi.return_value.update_component.side_effect = Exception("API fail")

            with self.assertRaises(UserError):
                line.action_save_component()

    def test_save_condition_defaults_to_new(self):
        """When condition is falsy, payload uses 'NEW'."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            condition=False,
            installation_id=False,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_save_component()

            payload = mock_api.update_component.call_args[0][1]
            self.assertEqual(payload['condition'], 'NEW')


# ==================== Action: Uninstall Component ====================


@tagged("onecore")
class TestComponentLineActionUninstall(TransactionCase):
    """Tests for action_uninstall_component."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.wizard = create_component_wizard(self.env)

    def test_uninstall_raises_without_installation_id(self):
        """Raises UserError when installation_id is empty."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            installation_id=False,
        )

        with self.assertRaises(UserError):
            line.action_uninstall_component()

    def test_uninstall_calls_api_with_correct_payload(self):
        """Calls update_component_installation with deinstallation payload."""
        inst_id = self.fake.component_installation_id()
        comp_id = self.fake.component_instance_id()
        room_id = self.fake.component_room_id()

        line = create_component_line(
            self.env,
            self.wizard.id,
            installation_id=inst_id,
            onecore_component_id=comp_id,
            room_id=room_id,
        )

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_uninstall_component()

            mock_api.update_component_installation.assert_called_once()
            call_args = mock_api.update_component_installation.call_args[0]
            self.assertEqual(call_args[0], inst_id)

            payload = call_args[1]
            self.assertEqual(payload['componentId'], comp_id)
            self.assertEqual(payload['spaceId'], room_id)
            self.assertEqual(payload['spaceType'], 'PropertyObject')

    def test_uninstall_deinstallation_date_is_iso_utc(self):
        """deinstallationDate value ends with Z and is valid ISO format."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            mock_api = MockApi.return_value
            mock_api.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                line.action_uninstall_component()

            payload = mock_api.update_component_installation.call_args[0][1]
            deinstall_date = payload['deinstallationDate']
            self.assertTrue(deinstall_date.endswith('Z'))

    def test_uninstall_reloads_components(self):
        """Calls wizard.reload_components after uninstall."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            MockApi.return_value.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), 'reload_components',
            ) as mock_reload:
                line.action_uninstall_component()
                mock_reload.assert_called_once()

    def test_uninstall_returns_wizard_action(self):
        """Returns action dict to reopen parent wizard."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            MockApi.return_value.update_component_installation.return_value = {}

            with patch.object(
                type(self.wizard), '_load_onecore_components', return_value=None
            ):
                result = line.action_uninstall_component()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')

    def test_uninstall_api_error_raises_user_error(self):
        """Exception from API raises UserError."""
        line = create_component_line(self.env, self.wizard.id)

        with patch(f'{LINE_PATH}.core_api.CoreApi') as MockApi:
            MockApi.return_value.update_component_installation.side_effect = (
                Exception("API fail")
            )

            with self.assertRaises(UserError):
                line.action_uninstall_component()


# ==================== Upload New Images ====================


@tagged("onecore")
class TestComponentLineUploadNewImages(TransactionCase):
    """Tests for _upload_new_images."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.wizard = create_component_wizard(self.env)

    def test_upload_returns_false_when_no_images(self):
        """Returns False when no new images are set."""
        line = create_component_line(self.env, self.wizard.id)
        result = line._upload_new_images()
        self.assertFalse(result)

    def test_upload_single_image(self):
        """Uploads one image and returns True."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            new_image_1=base64.b64encode(b'img_data'),
        )

        with patch(f'{LINE_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.upload_component_images.return_value = {
                'success_count': 1, 'errors': []
            }
            result = line._upload_new_images()

        self.assertTrue(result)

    def test_upload_both_images(self):
        """Uploads two images when both are set."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            new_image_1=base64.b64encode(b'img1'),
            new_image_2=base64.b64encode(b'img2'),
        )

        with patch(f'{LINE_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.upload_component_images.return_value = {
                'success_count': 2, 'errors': []
            }
            result = line._upload_new_images()

        self.assertTrue(result)
        images_arg = MockService.return_value.upload_component_images.call_args[0][1]
        self.assertEqual(len(images_arg), 2)

    def test_upload_clears_fields_after_success(self):
        """Clears new_image_1 and new_image_2 after upload."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            new_image_1=base64.b64encode(b'img_data'),
        )

        with patch(f'{LINE_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.upload_component_images.return_value = {
                'success_count': 1, 'errors': []
            }
            line._upload_new_images()

        self.assertFalse(line.new_image_1)
        self.assertFalse(line.new_image_2)

    def test_upload_returns_false_on_all_failures(self):
        """Returns False when success_count is 0."""
        line = create_component_line(
            self.env,
            self.wizard.id,
            new_image_1=base64.b64encode(b'img_data'),
        )

        with patch(f'{LINE_PATH}.ComponentOneCoreService') as MockService:
            MockService.return_value.upload_component_images.return_value = {
                'success_count': 0, 'errors': ['upload failed']
            }
            result = line._upload_new_images()

        self.assertFalse(result)


# ==================== Action: Close Popup ====================


@tagged("onecore")
class TestComponentLineActionClosePopup(TransactionCase):
    """Tests for action_close_popup."""

    def setUp(self):
        super().setUp()
        self.fake = setup_faker()
        self.wizard = create_component_wizard(self.env)

    def test_close_popup_returns_wizard_action(self):
        """Returns action dict pointing to parent wizard."""
        line = create_component_line(self.env, self.wizard.id)
        result = line.action_close_popup()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'maintenance.component.wizard')
        self.assertEqual(result['res_id'], self.wizard.id)
