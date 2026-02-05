"""Service for OneCore component CRUD operations."""

import json
import logging
from datetime import datetime

from odoo import fields

from ....onecore_api import core_api

_logger = logging.getLogger(__name__)

# Space type caption for apartments
APARTMENT_SPACE_CAPTION = 'Lägenhet'
# Space type for property objects (rooms)
PROPERTY_OBJECT_SPACE_TYPE = 'PropertyObject'


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
            # Fetch residence to get residenceId
            residence = self.api.fetch_residence(rental_property_id)
            if not residence or not residence.get('id'):
                return '[]', '[]', []

            residence_id = residence['id']

            # Fetch rooms
            rooms = self.api.fetch_rooms(residence_id)
            if not rooms:
                return '[]', '[]', []

            # Build rooms JSON
            rooms_json = json.dumps([
                {'id': r.get('propertyObjectId'), 'name': r.get('name', 'Okänt rum')}
                for r in rooms
            ])

            # Fetch categories
            categories_json = '[]'
            try:
                categories = self.api.fetch_component_categories()
                if categories:
                    categories_json = json.dumps(categories)
            except Exception as e:
                _logger.warning(f"Failed to fetch component categories: {e}")

            # Fetch components for each room
            component_data_list = []
            for room in rooms:
                room_id = room.get('propertyObjectId')
                room_name = room.get('name', 'Okänt rum')

                room_components = self._fetch_room_components(room_id)
                for comp in room_components:
                    comp_data = self._transform_component_data(comp, room_name, room_id)
                    if comp_data:
                        component_data_list.append(comp_data)

            return rooms_json, categories_json, component_data_list

        except Exception as e:
            _logger.warning(f"Failed to fetch components from OneCore: {e}")
            return '[]', '[]', []

    def _fetch_room_components(self, room_id):
        """Fetch components for a specific room.

        Args:
            room_id: The room/property object ID

        Returns:
            list: List of component dicts from API
        """
        try:
            components = self.api.fetch_components_by_room(room_id)
            return components or []
        except Exception as e:
            _logger.warning(f"Failed to fetch components for room {room_id}: {e}")
            return []

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
        subtype_data = model_data.get('subtype', {}) or {}
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

        # Fetch all image URLs for the component (not base64 data)
        image_urls = self.fetch_all_component_image_urls(comp.get('id'))

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
            # All image URLs from OneCore as JSON array
            'image_urls_json': json.dumps(image_urls) if image_urls else '[]',
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
