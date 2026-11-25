# -*- coding: utf-8 -*-
"""Tests for ComponentOneCoreService."""

import json
import time
from datetime import date
from unittest.mock import Mock

import psycopg2

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services import component_onecore_service
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
            {'propertyObjectId': room_1_id, 'name': 'Kök', 'sortingOrder': 1},
            {'propertyObjectId': room_2_id, 'name': 'Badrum', 'sortingOrder': 2},
        ]

        cat_id = self.fake.component_category_id()

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
        # Categories + per-room components are fetched in one parallel wave;
        # results are aligned: [categories, room1_components, room2_components]
        self.mock_api.parallel_get_json.return_value = [
            [{'id': cat_id, 'categoryName': 'Kök'}],
            [component],
            [component],
        ]

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

        # Components are loaded via the parallel helper, not per-room serial
        # calls, and image URLs are NOT fetched during load (deferred to the
        # gallery widget) — both used to dominate the wizard's load time.
        self.mock_api.parallel_get_json.assert_called_once()
        self.mock_api.fetch_component_documents.assert_not_called()
        self.assertNotIn('image_urls_json', components[0])

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

    def test_onecore_transform_reads_subtype_on_component_without_model(self):
        """Surfaces have no model; the hierarchy sits on the component."""
        service = self._create_service()

        component = {
            'id': 'comp-001',
            'modelId': None,
            'model': None,
            'subtype': {
                'subTypeName': 'Parkettgolv',
                'technicalLifespan': 30,
                'componentType': {
                    'typeName': 'Golv',
                    'category': {'categoryName': 'Ytskikt', 'type': 'SURFACE'},
                },
            },
            'componentInstallations': [{'id': 'inst-001', 'installationDate': '2024-01-15'}],
        }

        result = service._transform_component_data(component, 'Vardagsrum', 'room-001')

        self.assertEqual(result['subtype'], 'Parkettgolv')
        self.assertEqual(result['typ'], 'Golv')
        self.assertEqual(result['category'], 'Ytskikt')
        self.assertEqual(result['technical_lifespan'], 30)
        self.assertIsNone(result['model'])
        self.assertIsNone(result['model_id'])

    def test_onecore_transform_still_reads_subtype_nested_under_model(self):
        """Older responses nest the hierarchy under model."""
        service = self._create_service()

        component = {
            'id': 'comp-002',
            'model': {
                'id': 'model-002',
                'modelName': 'KG-1234',
                'subtype': {
                    'subTypeName': 'Frys',
                    'componentType': {'typeName': 'Vitvara', 'category': {'categoryName': 'Kök'}},
                },
            },
            'componentInstallations': [{'id': 'inst-002', 'installationDate': '2024-01-15'}],
        }

        result = service._transform_component_data(component, 'Kök', 'room-002')

        self.assertEqual(result['subtype'], 'Frys')
        self.assertEqual(result['typ'], 'Vitvara')
        self.assertEqual(result['category'], 'Kök')
        self.assertEqual(result['model_id'], 'model-002')

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


def _room(room_id, name=None, sorting_order=0, **kwargs):
    room = {'propertyObjectId': room_id, 'name': name, 'sortingOrder': sorting_order}
    room.update(kwargs)
    return room


def _component(comp_id, type_name, subtype_name, category_type='EQUIPMENT',
               installation_date='2024-01-15', xpand_code=None):
    return {
        'id': comp_id,
        'modelId': None,
        'model': None,
        'subtype': {
            'subTypeName': subtype_name,
            'xpandCode': xpand_code,
            'componentType': {
                'typeName': type_name,
                'category': {'categoryName': 'Kategori', 'type': category_type},
            },
        },
        'componentInstallations': [
            {'id': f'inst-{comp_id}', 'installationDate': installation_date}
        ],
    }


@tagged("onecore")
class TestLoadRoomComponents(TransactionCase):
    """Rooms and their components for the room grid on the ärende."""

    def setUp(self):
        super().setUp()
        component_onecore_service._room_components_cache.clear()
        self.addCleanup(component_onecore_service._room_components_cache.clear)
        self.mock_api = Mock()

    def _load(self, rental_id='406-096-04-0101'):
        service = ComponentOneCoreService(self.env)
        service._api = self.mock_api
        return service.load_room_components(rental_id)

    def _key(self, rental_id='406-096-04-0101'):
        return (self.env.cr.dbname, rental_id)

    def test_rooms_with_their_components(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-kok', 'Kök', 1),
            _room('room-vard', 'Vardagsrum', 2),
        ]
        self.mock_api.parallel_get_json.return_value = [
            [_component('comp-frys', 'Frys', 'Frysskåp fristående 190-225 liter',
                        xpand_code='FRY01')],
            [_component('comp-golv', 'Golv', 'Parkettgolv', 'SURFACE')],
        ]

        result = self._load()

        self.assertTrue(result['ok'])
        self.assertEqual(
            result['rooms'],
            [
                {
                    'id': 'room-kok', 'name': 'Kök', 'sequence': 0, 'loaded': True,
                    'components': [{
                        'id': 'comp-frys', 'label': 'Frys', 'number': None,
                        'subtype_name': 'Frysskåp fristående 190-225 liter',
                        'subtype_xpand_code': 'FRY01',
                        'category_type': 'EQUIPMENT', 'installation_id': 'inst-comp-frys',
                    }],
                },
                {
                    'id': 'room-vard', 'name': 'Vardagsrum', 'sequence': 1, 'loaded': True,
                    'components': [{
                        'id': 'comp-golv', 'label': 'Golv', 'number': None,
                        'subtype_name': 'Parkettgolv', 'subtype_xpand_code': None,
                        'category_type': 'SURFACE', 'installation_id': 'inst-comp-golv',
                    }],
                },
            ],
        )
        self.mock_api.fetch_rooms.assert_called_once_with('406-096-04-0101')
        # One wave for all rooms, and no /component-categories
        self.mock_api.parallel_get_json.assert_called_once_with(
            ['/components/by-room/room-kok', '/components/by-room/room-vard']
        )

    def test_rooms_follow_sorting_order(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-b', 'Badrum', 2),
            _room('room-x', 'Utan ordning', None),
            _room('room-k', 'Kök', 1),
        ]
        self.mock_api.parallel_get_json.return_value = [[], [], []]

        result = self._load()

        self.assertEqual([r['name'] for r in result['rooms']], ['Kök', 'Badrum', 'Utan ordning'])
        self.assertEqual([r['sequence'] for r in result['rooms']], [0, 1, 2])

    def test_room_name_falls_back_to_room_type_then_code(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-1', None, 1, roomType={'name': 'Sovrum'}, code='SOV'),
            _room('room-2', None, 2, roomType=None, code='HALL'),
        ]
        self.mock_api.parallel_get_json.return_value = [[], []]

        result = self._load()

        self.assertEqual([r['name'] for r in result['rooms']], ['Sovrum', 'Hall'])

    def test_room_names_in_capitals_get_sentence_case(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-1', 'KÖK', 1),
            _room('room-2', 'KLÄDKAMMARE 1', 2),
            _room('room-3', 'WC/DUSCH', 3),
            _room('room-4', 'RUM 1', 4),
            _room('room-5', 'Allrum', 5),
        ]
        self.mock_api.parallel_get_json.return_value = [[], [], [], [], []]

        result = self._load()

        self.assertEqual(
            [r['name'] for r in result['rooms']],
            ['Kök', 'Klädkammare 1', 'WC/dusch', 'Rum 1', 'Allrum'],
        )

    def test_deleted_rooms_are_left_out(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-1', 'Kök', 1),
            _room('room-2', 'Gammalt förråd', 2, deleted=True),
        ]
        self.mock_api.parallel_get_json.return_value = [[]]

        result = self._load()

        self.assertEqual([r['id'] for r in result['rooms']], ['room-1'])
        self.mock_api.parallel_get_json.assert_called_once_with(['/components/by-room/room-1'])

    def test_rooms_error_gives_not_ok(self):
        # Core answers 500 for an unknown rental id
        self.mock_api.fetch_rooms.side_effect = Exception("500 Server Error")

        result = self._load()

        self.assertEqual(result, {'ok': False, 'rooms': []})
        self.mock_api.parallel_get_json.assert_not_called()

    def test_one_failed_room_keeps_the_others(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-1', 'Kök', 1),
            _room('room-2', 'Badrum', 2),
        ]
        self.mock_api.parallel_get_json.return_value = [
            [_component('comp-frys', 'Frys', 'Frysskåp')],
            None,
        ]

        result = self._load()

        self.assertTrue(result['ok'])
        kok, badrum = result['rooms']
        self.assertTrue(kok['loaded'])
        self.assertEqual(len(kok['components']), 1)
        self.assertFalse(badrum['loaded'])
        self.assertEqual(badrum['components'], [])

    def test_identical_components_in_one_room_are_numbered_in_installation_order(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Vardagsrum', 1)]
        self.mock_api.parallel_get_json.return_value = [[
            _component('comp-b', 'Fönster', 'Fönster 3-glas', installation_date='2020-05-01'),
            _component('comp-a', 'Fönster', 'Fönster 3-glas', installation_date='2018-03-01'),
            _component('comp-c', 'Element', 'Radiator'),
        ]]

        result = self._load()

        components = result['rooms'][0]['components']
        self.assertEqual(
            [(c['id'], c['label'], c['number']) for c in components],
            [
                ('comp-c', 'Element', None),
                ('comp-a', 'Fönster', 1),
                ('comp-b', 'Fönster', 2),
            ],
        )

    def test_numbered_components_sort_by_number_not_text(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Vardagsrum', 1)]
        self.mock_api.parallel_get_json.return_value = [[
            _component(f'comp-{i:02d}', 'Fönster', 'Fönster 3-glas',
                       installation_date=f'2020-01-{i:02d}')
            for i in range(1, 12)
        ]]

        result = self._load()

        self.assertEqual(
            [c['number'] for c in result['rooms'][0]['components']], list(range(1, 12))
        )

    def test_components_are_named_by_type_with_the_subtype_below(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[
            _component('comp-spis', 'Spis', 'Elspisar bredd = 60 cm'),
            _component('comp-golv', 'Golv', 'Linoleum', 'SURFACE'),
            _component('comp-frys', 'Frys', 'Frys'),
        ]]

        result = self._load()

        self.assertEqual(
            [(c['label'], c['subtype_name']) for c in result['rooms'][0]['components']],
            # No subtype line when it would only repeat the name
            [('Frys', None), ('Golv', 'Linoleum'), ('Spis', 'Elspisar bredd = 60 cm')],
        )

    def test_label_falls_back_when_a_name_is_missing(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        no_type = _component('comp-1', None, 'Kylskåp fristående', 'EQUIPMENT')
        # An older core without category type: named like a surface
        no_category_type = _component('comp-2', 'Vägg', 'Tapetsering', None)
        nameless = _component('comp-3', None, None)
        self.mock_api.parallel_get_json.return_value = [[no_type, no_category_type, nameless]]

        result = self._load()

        self.assertEqual(
            sorted(c['label'] for c in result['rooms'][0]['components']),
            ['Kylskåp fristående', 'Okänd komponent', 'Vägg'],
        )

    def test_two_of_the_same_type_are_told_apart_by_subtype(self):
        # No numbers: a number would shift when a neighbour is installed or
        # removed, the subtype belongs to the component
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[
            _component('comp-a', 'Kombiskåp', 'Kyl- och frysskåp', installation_date='2019-01-01'),
            _component('comp-b', 'Kombiskåp', 'Kombinerad Kyl/Frys 200 cm',
                       installation_date='2021-01-01'),
            _component('comp-c', 'Spis', 'Elspis'),
        ]]

        result = self._load()

        self.assertEqual(
            [(c['label'], c['subtype_name']) for c in result['rooms'][0]['components']],
            [
                ('Kombiskåp', 'Kombinerad Kyl/Frys 200 cm'),
                ('Kombiskåp', 'Kyl- och frysskåp'),
                ('Spis', 'Elspis'),
            ],
        )

    def test_unexpected_component_data_only_affects_its_room(self):
        self.mock_api.fetch_rooms.return_value = [
            _room('room-1', 'Kök', 1),
            _room('room-2', 'Badrum', 2),
        ]
        broken = _component('comp-x', 'Spis', 'Elspis')
        broken['componentInstallations'] = [None]
        self.mock_api.parallel_get_json.return_value = [
            [_component('comp-frys', 'Frys', 'Frysskåp')],
            [broken],
        ]

        with self.assertLogs(component_onecore_service._logger, 'WARNING'):
            result = self._load()

        self.assertTrue(result['ok'])
        kok, badrum = result['rooms']
        self.assertTrue(kok['loaded'])
        self.assertEqual([c['label'] for c in kok['components']], ['Frys'])
        self.assertFalse(badrum['loaded'])
        self.assertEqual(badrum['components'], [])
        # Partly failed: not cached
        self.assertNotIn(self._key(), component_onecore_service._room_components_cache)

    def test_label_never_comes_from_model(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        component = _component('comp-1', 'Diskmaskin', 'Diskmaskin 60 cm')
        component['model'] = {'id': 'model-1', 'modelName': 'SMV4HVX33E'}
        self.mock_api.parallel_get_json.return_value = [[component]]

        result = self._load()

        self.assertEqual(result['rooms'][0]['components'][0]['label'], 'Diskmaskin')

    def test_deinstalled_component_is_skipped(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        removed = _component('comp-old', 'Spis', 'Elspis')
        removed['componentInstallations'][0]['deinstallationDate'] = '2025-01-01'
        self.mock_api.parallel_get_json.return_value = [
            [removed, _component('comp-new', 'Spis', 'Elspis')]
        ]

        result = self._load()

        self.assertEqual([c['id'] for c in result['rooms'][0]['components']], ['comp-new'])

    def test_no_rental_id_makes_no_call(self):
        self.assertEqual(self._load(rental_id=False), {'ok': False, 'rooms': []})
        self.mock_api.fetch_rooms.assert_not_called()

    def test_result_is_cached_within_ttl(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[_component('comp-1', 'Frys', 'Frysskåp')]]
        first = self._load()

        self.mock_api.reset_mock()
        second = self._load()

        self.assertEqual(second, first)
        self.mock_api.fetch_rooms.assert_not_called()
        self.mock_api.parallel_get_json.assert_not_called()

    def test_expired_cache_entry_is_refetched(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[]]
        self._load()
        cache = component_onecore_service._room_components_cache
        cache[self._key()] = (time.monotonic() - 1, cache[self._key()][1])

        self._load()

        self.assertEqual(self.mock_api.fetch_rooms.call_count, 2)

    def test_partial_failure_is_not_cached(self):
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [None]
        self._load()

        self._load()

        self.assertEqual(self.mock_api.fetch_rooms.call_count, 2)

    def test_storing_drops_expired_entries(self):
        cache = component_onecore_service._room_components_cache
        cache[self._key('old-rental')] = (time.monotonic() - 1, {'ok': True, 'rooms': []})
        cache[self._key('fresh-rental')] = (time.monotonic() + 60, {'ok': True, 'rooms': []})
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[]]

        self._load()

        self.assertNotIn(self._key('old-rental'), cache)
        self.assertIn(self._key('fresh-rental'), cache)
        self.assertIn(self._key(), cache)

    def test_cache_is_per_database(self):
        # Another database on the same server may use another OneCore
        component_onecore_service._room_components_cache[
            ('other_db', '406-096-04-0101')
        ] = (time.monotonic() + 60, {'ok': True, 'rooms': []})
        self.mock_api.fetch_rooms.return_value = [_room('room-1', 'Kök', 1)]
        self.mock_api.parallel_get_json.return_value = [[]]

        result = self._load()

        self.mock_api.fetch_rooms.assert_called_once_with('406-096-04-0101')
        self.assertEqual([r['id'] for r in result['rooms']], ['room-1'])

    def test_database_error_is_raised_not_swallowed(self):
        # The transaction is aborted: Odoo must roll back and retry
        self.mock_api.fetch_rooms.side_effect = psycopg2.errors.SerializationFailure(
            "could not serialize access due to concurrent update"
        )

        with self.assertRaises(psycopg2.errors.SerializationFailure):
            self._load()

    def test_rooms_error_is_not_cached(self):
        self.mock_api.fetch_rooms.side_effect = Exception("500 Server Error")
        self._load()

        self._load()

        self.assertEqual(self.mock_api.fetch_rooms.call_count, 2)
