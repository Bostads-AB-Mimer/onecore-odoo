"""Service for OneCore component CRUD operations."""

import json
import logging
import re
import time
import urllib.parse
from datetime import datetime

from odoo import fields

from ....onecore_api import core_api

_logger = logging.getLogger(__name__)

# Space type caption for apartments
APARTMENT_SPACE_CAPTION = 'Lägenhet'
# Space type for property objects (rooms)
PROPERTY_OBJECT_SPACE_TYPE = 'PropertyObject'

# Per-worker cache for the ärende form's room grid, which loads on every form
# open; users page back and forth between ärenden on the same apartment.
# Worst-case staleness = TTL.
ROOM_COMPONENTS_CACHE_TTL = 300  # seconds
_room_components_cache = {}  # rental_id -> (expires_at_monotonic, result)


def _component_subtype(comp):
    """The component's subtype, with its componentType and category nested.

    OneCore now returns the hierarchy on the component itself, and model is
    null for components without one (every surface). Older responses nest it
    under model, so fall back to that.
    """
    return comp.get('subtype') or (comp.get('model') or {}).get('subtype') or {}


def _sentence_case(name):
    """KÖK -> Kök, KLÄDKAMMARE 1 -> Klädkammare 1, WC/DUSCH -> WC/dusch.

    OneCore's room names are all capitals. Words of one or two letters stay
    capitals (WC). A name that isn't all capitals is left as it is.
    """
    if name != name.upper():
        return name
    # Odd indexes are runs of letters; a plain \b would split "kök" at the ö
    parts = re.split(r'([^\W\d_]+)', name)
    for i in range(1, len(parts), 2):
        if len(parts[i]) > 2:
            parts[i] = parts[i].lower()
    result = ''.join(parts)
    for i, char in enumerate(result):
        if char.isalpha():
            return result[:i] + char.upper() + result[i + 1:]
    return result


def _room_name(room):
    # Same fallback as property-tree's getRoomDisplayName
    return _sentence_case(
        room.get('name')
        or (room.get('roomType') or {}).get('name')
        or room.get('code')
        or 'Okänt rum'
    )


def _room_sort_key(room):
    sorting_order = room.get('sortingOrder')
    return (sorting_order is None, sorting_order or 0, _room_name(room))


def _component_options(components):
    """Selectable components of one room, named for the grid.

    Each is named by its component type (Spis, Golv), with the subtype shown
    under it (Elspisar bredd = 60 cm, Linoleum): the type is short to scan,
    the subtype says which one it is. Never from model: it is null for
    surfaces.
    """
    options = []
    for comp in components:
        installations = comp.get('componentInstallations') or []
        if installations and installations[0].get('deinstallationDate'):
            continue
        subtype = _component_subtype(comp)
        component_type = subtype.get('componentType') or {}
        category = component_type.get('category') or {}
        subtype_name = subtype.get('subTypeName')
        label = component_type.get('typeName') or subtype_name or 'Okänd komponent'
        options.append({
            'id': comp.get('id'),
            'label': label,
            # Empty when it would only repeat the name
            'subtype_name': subtype_name if subtype_name != label else None,
            'category_type': category.get('type'),
            'installation_id': installations[0].get('id') if installations else None,
            'installation_date': (
                installations[0].get('installationDate') if installations else None
            ),
        })

    # The subtype tells two of the same type apart (two Kombiskåp). Only the
    # same type and subtype twice (two identical Fönster) are numbered, in
    # installation order.
    identical = {}
    for option in options:
        identical.setdefault((option['label'], option['subtype_name']), []).append(option)
    for same in identical.values():
        if len(same) > 1:
            same.sort(key=lambda o: (o['installation_date'] or '', o['id'] or ''))
            for number, option in enumerate(same, start=1):
                option['label'] = f"{option['label']} {number}"

    for option in options:
        del option['installation_date']
    return sorted(
        options,
        key=lambda o: (o['label'].casefold(), (o['subtype_name'] or '').casefold()),
    )


class ComponentOneCoreService:
    """Service for handling OneCore component CRUD operations."""

    def __init__(self, env):
        self.env = env
        self._api = None

    @property
    def api(self):
        """Lazy-load the API client."""
        if self._api is None:
            self._api = core_api.CoreApi(self.env)
        return self._api

    def create_component(self, form_data, room_id):
        """Create a component in OneCore.

        Args:
            form_data: Dict containing form field values
            room_id: The room/space ID to create the component in

        Returns:
            dict: Created component data from OneCore

        Raises:
            Exception: If component creation fails
        """
        payload = self._build_create_payload(form_data, room_id)
        return self.api.create_component(payload)

    def _build_create_payload(self, form_data, room_id):
        """Build the API payload for component creation.

        Args:
            form_data: Dict containing form field values
            room_id: The room/space ID

        Returns:
            dict: Payload ready for OneCore API
        """
        # Use today's date if no installation date provided
        installation_date = form_data.get('installation_date')
        if installation_date:
            installation_date_iso = datetime.combine(
                installation_date, datetime.min.time()
            ).isoformat() + "Z"
        else:
            installation_date_iso = datetime.combine(
                fields.Date.today(), datetime.min.time()
            ).isoformat() + "Z"

        payload = {
            # Required fields
            "modelName": form_data.get('model') or "Unknown",
            "componentSubtypeId": form_data.get('subtype_id'),
            "serialNumber": form_data.get('serial_number') or "",
            "componentWarrantyMonths": form_data.get('warranty_months') or 0,
            # Price fields
            "priceAtPurchase": form_data.get('current_price') or 0,
            "currentPrice": form_data.get('current_price') or 0,
            "installationCost": form_data.get('current_install_price') or 0,
            "currentInstallPrice": form_data.get('current_install_price') or 0,
            # From subtype
            "depreciationPriceAtPurchase": form_data.get('depreciation_price') or 0,
            "economicLifespan": form_data.get('economic_lifespan') or 0,
            "spaceId": room_id,
            "spaceType": PROPERTY_OBJECT_SPACE_TYPE,
            "installationDate": installation_date_iso,
            # Conditionally required for new models
            "manufacturer": form_data.get('manufacturer') or "Unknown",
            "modelWarrantyMonths": form_data.get('warranty_months') or 0,
            # Always included optional fields
            "warrantyStartDate": installation_date_iso,
            "quantity": 1,
            "status": "ACTIVE",
            "condition": form_data.get('condition') or "NEW",
        }

        # Only include optional string fields if they have values
        if form_data.get('specifications'):
            payload["technicalSpecification"] = form_data['specifications']
            payload["specifications"] = form_data['specifications']
        if form_data.get('dimensions'):
            payload["dimensions"] = form_data['dimensions']
        if form_data.get('additional_information'):
            payload["additionalInformation"] = form_data['additional_information']
        if form_data.get('ncs_code'):
            payload["ncsCode"] = form_data['ncs_code']

        return payload

    def load_components_for_residence(self, rental_property_id, space_caption):
        """Load all components for a residence from OneCore.

        Args:
            rental_property_id: The rental property ID (from Odoo record)
            space_caption: The space type caption (e.g., 'Lägenhet')

        Returns:
            tuple: (rooms_json, categories_json, component_data_list)
        """
        # Only fetch for apartment errands
        if space_caption != APARTMENT_SPACE_CAPTION:
            return '[]', '[]', []

        if not rental_property_id:
            return '[]', '[]', []

        try:
            # Fetch rooms first (serial): primes/refreshes the auth token so
            # the parallel wave below runs with a valid token.
            rooms = self.api.fetch_rooms(rental_property_id)
            if not rooms:
                return '[]', '[]', []

            # Build rooms JSON
            rooms_json = json.dumps([
                {'id': r.get('propertyObjectId'), 'name': r.get('name', 'Okänt rum')}
                for r in rooms
            ])

            # Fan out concurrently: component categories + components for every
            # room in a single parallel wave (was a serial call per room, which
            # dominated the wizard's load time).
            categories_path = "/component-categories"
            room_paths = [
                "/components/by-room/%s"
                % urllib.parse.quote(str(room.get('propertyObjectId')), safe='')
                for room in rooms
            ]
            results = self.api.parallel_get_json([categories_path] + room_paths)

            categories = results[0]
            categories_json = json.dumps(categories) if categories else '[]'

            # Transform components (main thread — pure dict work, no HTTP/ORM).
            # Image URLs are intentionally NOT loaded here; the wizard loads a
            # component's images lazily when its detail is opened.
            component_data_list = []
            for room, room_components in zip(rooms, results[1:]):
                room_name = room.get('name', 'Okänt rum')
                room_id = room.get('propertyObjectId')
                for comp in room_components or []:
                    comp_data = self._transform_component_data(comp, room_name, room_id)
                    if comp_data:
                        component_data_list.append(comp_data)

            return rooms_json, categories_json, component_data_list

        except Exception as e:
            _logger.warning(f"Failed to fetch components from OneCore: {e}")
            return '[]', '[]', []

    def load_room_components(self, rental_id):
        """Load the rooms of a rental object with the components in each.

        Args:
            rental_id: The rental object's id, e.g. '406-096-04-0101'

        Returns:
            dict: {'ok': bool, 'rooms': [{'id', 'name', 'sequence', 'loaded',
            'components': [{'id', 'label', 'subtype_name', 'category_type',
            'installation_id'}]}]}.
            'ok' is False when the rooms can't be fetched. Core answers 500,
            not 404, for an unknown rental id, so this is shown as "no rooms"
            rather than as an error. A room whose components can't be fetched
            has 'loaded' False; the other rooms still load.
        """
        if not rental_id:
            return {'ok': False, 'rooms': []}

        cached = _room_components_cache.get(rental_id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]

        try:
            # Fetch rooms first (serial): primes/refreshes the auth token so
            # the parallel wave below runs with a valid token.
            rooms = [
                room for room in self.api.fetch_rooms(rental_id) or []
                if not room.get('deleted')
            ]
            rooms.sort(key=_room_sort_key)
            room_paths = [
                "/components/by-room/%s"
                % urllib.parse.quote(str(room.get('propertyObjectId')), safe='')
                for room in rooms
            ]
            results = self.api.parallel_get_json(room_paths) if room_paths else []
        except Exception as e:
            _logger.warning(
                "Failed to fetch rooms for rental id %s from OneCore: %s", rental_id, e
            )
            return {'ok': False, 'rooms': []}

        result_rooms = []
        for sequence, (room, room_components) in enumerate(zip(rooms, results)):
            # parallel_get_json gives None for a failed call, e.g. the 500
            # core returns when one component in the room fails to parse
            loaded = room_components is not None
            try:
                components = _component_options(room_components or [])
            except Exception as e:
                # Unexpected data: show this room as not loaded, keep the rest
                _logger.warning(
                    "Unexpected components for room %s from OneCore: %s",
                    room.get('propertyObjectId'), e,
                )
                loaded, components = False, []
            result_rooms.append({
                'id': room.get('propertyObjectId'),
                'name': _room_name(room),
                'sequence': sequence,
                'loaded': loaded,
                'components': components,
            })
        result = {'ok': True, 'rooms': result_rooms}

        if all(room['loaded'] for room in result_rooms):
            now = time.monotonic()
            # Drop expired entries, so the cache only holds the apartments
            # opened within the TTL. A copy of the items: other worker
            # threads may change the dict meanwhile.
            for key, (expires_at, _cached) in list(_room_components_cache.items()):
                if expires_at <= now:
                    _room_components_cache.pop(key, None)
            _room_components_cache[rental_id] = (now + ROOM_COMPONENTS_CACHE_TTL, result)
        return result

    def _transform_component_data(self, comp, room_name, room_id):
        """Transform OneCore component data to wizard format.

        Args:
            comp: Raw component data from OneCore API
            room_name: Name of the room
            room_id: ID of the room

        Returns:
            dict: Transformed component data for wizard line, or None if skipped
        """
        # Extract nested data
        model_data = comp.get('model', {}) or {}
        subtype_data = _component_subtype(comp)
        component_type_data = subtype_data.get('componentType', {}) or {}
        category_data = component_type_data.get('category', {}) or {}

        # Get installation data
        installations = comp.get('componentInstallations', [])
        install_date = None
        installation_id = None

        if installations:
            # Skip components that have been uninstalled
            if installations[0].get('deinstallationDate'):
                return None

            install_date_str = installations[0].get('installationDate')
            if install_date_str:
                install_date = install_date_str[:10]  # Extract YYYY-MM-DD
            installation_id = installations[0].get('id')

        # NOTE: image URLs are intentionally NOT fetched here — that used to
        # cost one documents-call per component and dominated the wizard's
        # load time. maintenance.component.line fetches them lazily via the
        # image_urls_json compute when a component's detail form is opened.
        return {
            'typ': component_type_data.get('typeName'),
            'subtype': subtype_data.get('subTypeName'),
            'category': category_data.get('categoryName'),
            'model': model_data.get('modelName'),
            'manufacturer': model_data.get('manufacturer'),
            'serial_number': comp.get('serialNumber'),
            'warranty_months': comp.get('warrantyMonths'),
            'specifications': comp.get('specifications'),
            'ncs_code': comp.get('ncsCode'),
            'additional_information': comp.get('additionalInformation'),
            'condition': comp.get('condition'),
            'installation_date': install_date,
            'room_name': room_name,
            'room_id': room_id,
            'onecore_component_id': comp.get('id'),
            'model_id': model_data.get('id'),
            'installation_id': installation_id,
            # Economic fields
            'price_at_purchase': comp.get('priceAtPurchase') or 0,
            'depreciation_price_at_purchase': comp.get('depreciationPriceAtPurchase') or 0,
            'economic_lifespan': comp.get('economicLifespan') or 0,
            'technical_lifespan': subtype_data.get('technicalLifespan') or 0,
            'replacement_interval': subtype_data.get('replacementIntervalMonths') or 0,
        }

    def search_models(self, search_text, type_id=None, subtype_id=None):
        """Search component models for autocomplete.

        Args:
            search_text: Model name to search for (minimum 2 characters)
            type_id: Optional component type ID to filter by
            subtype_id: Optional component subtype ID to filter by

        Returns:
            list: List of model dicts for dropdown
        """
        if not search_text or len(search_text) < 2:
            return []

        try:
            models = self.api.fetch_component_models(
                search_text,
                page=1,
                limit=5,
                type_id=type_id,
                subtype_id=subtype_id
            )
            return [
                {
                    'modelName': m.get('modelName'),
                    'manufacturer': m.get('manufacturer'),
                    'label': f"{m.get('modelName')} ({m.get('manufacturer', 'Okänd')})"
                }
                for m in (models or [])
            ]
        except Exception as e:
            _logger.warning(f"Failed to search component models: {e}")
            return []

    def upload_component_images(self, component_instance_id, images):
        """Upload images to a component instance in OneCore.

        Args:
            component_instance_id: The component instance ID to attach images to
            images: List of tuples (image_data, caption) where image_data is base64

        Returns:
            dict: Result with 'success_count' and 'errors' list
        """
        result = {
            'success_count': 0,
            'errors': []
        }

        if not component_instance_id:
            _logger.warning("Cannot upload images: no component_instance_id provided")
            return result

        for image_data, caption in images:
            if not image_data:
                continue

            try:
                self.api.upload_document(image_data, component_instance_id)
                result['success_count'] += 1
                _logger.info(f"Successfully uploaded image '{caption}' to component {component_instance_id}")
            except Exception as e:
                error_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_msg = e.response.text
                    except Exception:
                        pass
                _logger.warning(f"Failed to upload image '{caption}': {error_msg}")
                result['errors'].append({
                    'caption': caption,
                    'error': error_msg
                })

        return result

    def fetch_all_component_image_urls(self, component_instance_id):
        """Fetch all image URLs for a component instance.

        Args:
            component_instance_id: The component instance ID

        Returns:
            list: List of all valid image URLs, or empty list
        """
        if not component_instance_id:
            return []

        try:
            documents = self.api.fetch_component_documents(component_instance_id)
            if not documents:
                return []

            # Filter to only documents with valid URLs (size > 0 and url present)
            valid_documents = [
                doc for doc in documents
                if doc.get('url') and doc.get('size', 0) > 0
            ]

            # Return all valid URLs
            return [doc.get('url') for doc in valid_documents]
        except Exception as e:
            _logger.warning(f"Failed to fetch component image URLs: {e}")
            return []
