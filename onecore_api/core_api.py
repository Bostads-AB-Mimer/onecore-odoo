import requests
import logging
import urllib.parse
import json

from concurrent.futures import ThreadPoolExecutor

_logger = logging.getLogger(__name__)

# Cap on concurrent outbound HTTP calls to OneCore when fanning out (e.g.
# fetching components for every room of an apartment).
_PARALLEL_GET_MAX_WORKERS = 8
# (connect, read) timeout for each parallel call — without it a single hung
# OneCore call would block its worker thread and stall the whole wave.
_PARALLEL_GET_TIMEOUT = (5, 30)

# Endpoints that answer "which leases match this identifier".
LEASE_PATHS = {
    "leaseId": "/leases",
    "rentalObjectId": "/leases/by-rental-property-id",
    "contactCode": "/leases/by-contact-code",
    "pnr": "/leases/by-pnr",
}

# Which kind of rental object a contract points at. Single source of truth, also
# used by the direct lookups in onecore_maintenance_extension.
LEASE_TYPE_TO_OBJECT_KIND = {
    "Bostadskontrakt": "residence",
    "Kooperativ hyresrätt": "residence",
    "P-Platskontrakt": "parking",
    "Garagekontrakt": "parking",
    "Lokalkontrakt": "facility",
}

# The CoreApi method that fetches each object kind by rental id.
OBJECT_KIND_FETCHERS = {
    "residence": "fetch_residence",
    "parking": "fetch_parking_space",
    "facility": "fetch_facility",
}

# Object kinds that can carry maintenance units (laundry rooms, playgrounds, ...).
MAINTENANCE_UNIT_KINDS = ("residence", "facility")

MAINTENANCE_UNIT_TYPES = ["Tvättstuga", "Miljöbod", "Lekplats"]


def build_form_item(lease, kind, obj, maintenance_units=None):
    """The per-contract payload shape the space-type handlers consume.

    ``kind`` is one of :data:`OBJECT_KIND_FETCHERS`; ``lease`` may be None for a
    vacant object.
    """
    return {
        "lease": lease,
        "rental_property": obj if kind == "residence" else None,
        "parking_space": obj if kind == "parking" else None,
        "facility": obj if kind == "facility" else None,
        "maintenance_units": maintenance_units or [],
    }


class CoreApi:
    def __init__(self, env):
        self.env = env
        if self._get_persisted_token() is None:
            self._get_auth_token()

    def _get_env_value(self, key):
        return self.env["ir.config_parameter"].sudo().get_param(key, default=None)

    def _get_persisted_token(self):
        return self._get_env_value("onecore_api_token")

    def _persist_token(self, token):
        self.env["ir.config_parameter"].sudo().set_param("onecore_api_token", token)

    def _get_auth_token(self):
        body = {
            "username": self._get_env_value("onecore_username"),
            "password": self._get_env_value("onecore_password"),
        }
        base_url = self._get_env_value("onecore_base_url")
        response = requests.post(f"{base_url}/auth/generateToken", json=body)

        if response.status_code == 200:
            new_token = response.json().get("token")
            self._persist_token(new_token)
            return new_token
        else:
            response.raise_for_status()

    def request(self, method, url, **kwargs):
        token = self._get_persisted_token()
        base_url = self._get_env_value("onecore_base_url")
        full_url = f"{base_url}{url}"
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.request(method, full_url, headers=headers, **kwargs)
        if response.status_code == 401:
            new_token = self._get_auth_token()
            headers["Authorization"] = f"Bearer {new_token}"
            response = requests.request(method, full_url, headers=headers, **kwargs)

            if response.status_code == 401:
                _logger.error(
                    "Unauthorized request after token refresh: %s", response.text
                )
                response.raise_for_status()

        return response

    def _get_json(self, url, **kwargs):
        response = self.request("GET", url, **kwargs)
        response.raise_for_status()
        return response.json().get("content")

    def parallel_get_json(self, urls):
        """Fetch several GET endpoints concurrently and return their ``content``.

        Pure outbound HTTP: the auth token and base URL are read ONCE here on
        the calling (main) thread, then each request runs in a worker thread
        that only touches the captured strings + ``requests`` — never
        ``self.env``/the ORM (not thread-safe).

        Args:
            urls: list of path strings (same form as ``_get_json``).

        Returns:
            list aligned with ``urls``; each item is the parsed ``content`` on
            success or ``None`` on any error (logged). Falls back to serial
            ``_get_json`` if the prerequisites for threading aren't met.
        """
        if not urls:
            return []

        token = self._get_persisted_token()
        base_url = self._get_env_value("onecore_base_url")

        # Without a token/base_url we can't do the pure-HTTP threaded path;
        # fall back to the serial (ORM-aware, token-refreshing) client.
        if not token or not base_url:
            return self._serial_get_json_safe(urls)

        headers = {"Authorization": f"Bearer {token}"}

        def _fetch(path):
            # Runs in a worker thread — no self.env access here.
            try:
                response = requests.get(
                    f"{base_url}{path}",
                    headers=headers,
                    timeout=_PARALLEL_GET_TIMEOUT,
                )
                response.raise_for_status()
                return response.json().get("content")
            except Exception as err:
                _logger.warning("parallel_get_json failed for %s: %s", path, err)
                return None

        try:
            max_workers = min(_PARALLEL_GET_MAX_WORKERS, len(urls))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # executor.map preserves input order.
                return list(executor.map(_fetch, urls))
        except Exception as err:
            _logger.warning("parallel_get_json pool failed, falling back to serial: %s", err)
            return self._serial_get_json_safe(urls)

    def _serial_get_json_safe(self, urls):
        """Serial fallback for parallel_get_json: same shape (None on error)."""
        results = []
        for url in urls:
            try:
                results.append(self._get_json(url))
            except Exception as err:
                _logger.warning("parallel_get_json (serial) failed for %s: %s", url, err)
                results.append(None)
        return results

    def fetch_leases_unfiltered(self, identifier, value):
        """Leases for an identifier WITHOUT location-type filtering.

        Used by the direct lookups (MIM-1841): there the object/contact must
        resolve regardless of contract type, so this deliberately skips
        ``filter_lease_on_location_type``. Each lease dict may carry a ``tenants``
        list; returns an empty list when there is no content.
        """
        if identifier not in LEASE_PATHS:
            raise OneCoreException(f"Ogiltig söktyp: {identifier}")

        content = self._get_json(
            f"{LEASE_PATHS[identifier]}/{urllib.parse.quote(str(value), safe='')}",
            params={"includeContacts": "true", "includeUpcomingLeases": "true"},
        )
        if content is None:
            return []
        return content if isinstance(content, list) else [content]

    def fetch_leases(self, identifier, value, location_type):
        try:
            content = self.fetch_leases_unfiltered(identifier, value)

            # If no content returned, return empty list.
            if not content:
                return []

            # Filter response on space caption if needed
            filtered_content = self.filter_lease_on_location_type(
                content, location_type
            )

            # If filter returned None or empty, return empty list.
            if filtered_content is None:
                return []

            return (
                filtered_content
                if isinstance(filtered_content, list)
                else [filtered_content]
            )

        except requests.HTTPError as http_err:
            raise OneCoreException(
                f"Kunde inte hitta något resultat för {identifier}: {value}. Det verkar som att det inte finns någon koppling till OneCore-servern.",
            )

    def filter_lease_on_location_type(self, data, location_type):
        """
        Filter leases based on location type.
        """

        # Handle case where data might not be a list or contain non-dict items
        if not isinstance(data, list):
            return data

        if location_type == "Bilplats":
            filtered_content = [
                item
                for item in data
                if isinstance(item, dict)
                and item.get("type", "").strip()
                in ("P-Platskontrakt", "Garagekontrakt")
            ]
            return filtered_content

        if location_type == "Lokal":
            filtered_content = [
                item
                for item in data
                if isinstance(item, dict)
                and item.get("type", "").strip() == "Lokalkontrakt"
            ]
            return filtered_content

        # Default to "Bostadskontrakt", fallback to "Kooperativ hyresrätt"
        filtered_content = [
            item
            for item in data
            if isinstance(item, dict)
            and item.get("type", "").strip() == "Bostadskontrakt"
        ]

        if not filtered_content:
            filtered_content = [
                item
                for item in data
                if isinstance(item, dict)
                and item.get("type", "").strip() == "Kooperativ hyresrätt"
            ]

        return filtered_content

    def fetch_residence(self, id):
        return self._get_json(
            f"/residences/by-rental-id/{urllib.parse.quote(str(id), safe='')}"
        )

    # Fetch staircases for specified building code
    # Note: Fix the endpoint in OneCore so it follows the same naming structure?
    def fetch_staircases_for_building(self, code):
        return self._get_json(
            f"/staircases?buildingCode={urllib.parse.quote(str(code), safe='')}"
        )

    def fetch_building(self, id, location_type):
        building = self._get_json(
            f"/buildings/by-building-code/{urllib.parse.quote(str(id), safe='')}"
        )
        maintenance_unit_types = ["Tvättstuga", "Miljöbod", "Lekplats"]
        if building:
            maintenance_units = (
                self.fetch_maintenance_units_for_building(building["code"])
                if location_type in maintenance_unit_types
                else []
            )
            # Fetch staircases if location_type is 'Uppgång'
            staircases = (
                self.fetch_staircases_for_building(building["code"])
                if location_type == "Uppgång"
                else []
            )

            return {
                **building,
                "staircases": staircases,
                "maintenance_units": (
                    self.filter_maintenance_units_by_location_type(
                        maintenance_units, location_type
                    )
                    if maintenance_units
                    else []
                ),
            }
        return None

    def fetch_buildings_for_property(self, property_code):
        return self._get_json(
            f"/buildings/by-property-code/{urllib.parse.quote(str(property_code), safe='')}"
        )

    def fetch_properties(self, name, location_type):
        properties = self._get_json(f"/properties/search", params={"q": name})
        data = []

        maintenance_unit_types = ["Tvättstuga", "Miljöbod", "Lekplats"]
        building_types = ["Byggnad", "Övrigt"]

        for property in properties:
            buildings = (
                self.fetch_buildings_for_property(property["code"])
                if location_type in building_types
                else []
            )
            maintenance_units = (
                self.fetch_maintenance_units(property["code"], location_type)
                if location_type in maintenance_unit_types
                else []
            )

            data.append(
                {
                    "property": property,
                    "buildings": buildings,
                    "maintenance_units": (
                        self.filter_maintenance_units_by_location_type(
                            maintenance_units, location_type
                        )
                        if maintenance_units
                        else []
                    ),
                }
            )

        return data

    def fetch_maintenance_units_for_property(self, code):
        return self._get_json(
            f"/maintenance-units/by-property-code/{urllib.parse.quote(str(code), safe='')}"
        )

    def fetch_maintenance_units_for_building(self, code):
        return self._get_json(
            f"/maintenance-units/by-building-code/{urllib.parse.quote(str(code), safe='')}"
        )

    def fetch_maintenance_units(self, id, location_type):
        content = self._get_json(
            f"/maintenance-units/by-property-code/{urllib.parse.quote(str(id), safe='')}"
        )
        return self.filter_maintenance_units_by_location_type(content, location_type)

    def filter_maintenance_units_by_location_type(
        self, maintenance_units, location_type
    ):
        return filter(
            lambda maintenance_unit: maintenance_unit["type"] == location_type,
            maintenance_units,
        )

    def fetch_parking_space(self, id):
        return self._get_json(
            f"/parking-spaces/by-rental-id/{urllib.parse.quote(str(id), safe='')}"
        )

    def fetch_facility(self, id):
        return self._get_json(
            f"/facilities/by-rental-id/{urllib.parse.quote(str(id), safe='')}"
        )

    def fetch_rooms(self, rental_id):
        """Fetch rooms for a residence by rental id."""
        return self._get_json(
            f"/rooms?rentalId={urllib.parse.quote(str(rental_id), safe='')}"
        )

    def fetch_components_by_room(self, room_id):
        """Fetch components for a specific room."""
        return self._get_json(
            f"/components/by-room/{urllib.parse.quote(str(room_id), safe='')}"
        )

    def fetch_component_models(
        self, model_name, page=1, limit=20, type_id=None, subtype_id=None
    ):
        """Fetch component models matching the given model name.

        Args:
            model_name: The model name to search for
            page: Page number for pagination
            limit: Number of results per page
            type_id: Optional component type ID to filter by
            subtype_id: Optional component subtype ID to filter by
        """
        params = {
            "modelName": model_name,
            "page": page,
            "limit": limit,
        }
        if type_id:
            params["typeId"] = type_id
        if subtype_id:
            params["subtypeId"] = subtype_id
        return self._get_json("/component-models", params=params)

    def fetch_component_categories(self):
        """Fetch all component categories."""
        return self._get_json("/component-categories")

    def fetch_component_types(self, category_id, page=1, limit=100):
        """Fetch component types for a category."""
        return self._get_json(
            "/component-types",
            params={"categoryId": category_id, "page": page, "limit": limit},
        )

    def fetch_component_subtypes(self, type_id, page=1, limit=100):
        """Fetch component subtypes for a type."""
        return self._get_json(
            "/component-subtypes",
            params={"typeId": type_id, "page": page, "limit": limit},
        )

    def create_component(self, payload):
        """Create a component using the unified add-component process."""
        response = self.request("POST", "/processes/add-component", json=payload)
        response.raise_for_status()
        return response.json()

    def update_component(self, component_id, payload):
        """Update a component using PUT /components/{id}."""
        response = self.request("PUT", f"/components/{component_id}", json=payload)
        response.raise_for_status()
        return response.json()

    def update_component_installation(self, installation_id, payload):
        """Update component installation via PUT /component-installations/{id}."""
        response = self.request(
            "PUT", f"/component-installations/{installation_id}", json=payload
        )
        response.raise_for_status()
        return response.json()

    def upload_document(self, file_data, component_instance_id, file_name=None):
        """Upload a document/image to a component instance.

        Args:
            file_data: Base64 encoded image string
            component_instance_id: The component instance ID to attach the document to
            file_name: Optional filename for the image (auto-generated if not provided)

        Returns:
            dict: Response from the API
        """
        import base64 as b64
        import filetype

        # Ensure file_data is a string
        if isinstance(file_data, bytes):
            file_data = file_data.decode("utf-8")

        # Detect content type from image header bytes
        content_type = "image/jpeg"  # default
        try:
            header_bytes = b64.b64decode(file_data[:352])
            kind = filetype.guess(header_bytes)
            if kind is not None:
                content_type = kind.mime
        except Exception:
            pass  # Keep default image/jpeg

        # Generate filename with correct extension based on content type
        if file_name is None:
            import uuid
            from datetime import datetime

            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }
            extension = ext_map.get(content_type, ".jpg")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:8]
            file_name = f"image_{timestamp}_{unique_id}{extension}"

        _logger.info(
            f"upload_document: component_id={component_instance_id}, content_type={content_type}, file_name={file_name}"
        )

        # Build JSON payload
        payload = {
            "fileData": file_data,
            "fileName": file_name,
            "contentType": content_type,
        }

        response = self.request(
            "POST", f"/components/{component_instance_id}/upload", json=payload
        )
        response.raise_for_status()
        return response.json() if response.text else {}

    def fetch_component_documents(self, component_instance_id):
        """Fetch documents/images for a component instance.

        Args:
            component_instance_id: The component instance ID

        Returns:
            list: List of document objects with fileData, fileName, contentType, etc.
        """
        # Using the documents endpoint for fetching component instance documents
        response = self.request(
            "GET", f"/documents/component-instances/{component_instance_id}"
        )
        response.raise_for_status()
        return response.json() if response.text else []

    def fetch_form_data(self, identifier, value, location_type):
        try:
            leases = self.fetch_leases(identifier, value, location_type)

            if leases and len(leases) > 0:
                data = []

                for lease in leases:
                    # Skip if lease is None or missing required fields.
                    if not lease or not lease.get("type"):
                        continue

                    lease_type = lease["type"].strip()
                    kind = LEASE_TYPE_TO_OBJECT_KIND.get(lease_type)
                    if kind:
                        try:
                            fetched_data = getattr(self, OBJECT_KIND_FETCHERS[kind])(
                                lease["rentalPropertyId"]
                            )
                        except Exception:
                            _logger.warning(
                                "Skipping lease %s: could not fetch rental property %s as %s",
                                lease.get("leaseId"),
                                lease.get("rentalPropertyId"),
                                lease_type,
                            )
                            continue

                        maintenance_units = (
                            self.fetch_maintenance_units(
                                fetched_data["property"]["code"], location_type
                            )
                            if kind in MAINTENANCE_UNIT_KINDS
                            and location_type in MAINTENANCE_UNIT_TYPES
                            else []
                        )

                        data.append(
                            build_form_item(
                                lease, kind, fetched_data, maintenance_units
                            )
                        )
                return data

            # Handle case when identifier is "rentalObjectId" (Hyresobjekt) and leases array is empty
            # Fetch rental property directly using the search value as rental property ID
            if identifier == "rentalObjectId" and (not leases or len(leases) == 0):
                data = []

                # Use space caption (location_type) to determine which fetch method to call
                try:
                    if location_type == "Bilplats":
                        # Fetch parking space
                        parking_space = self.fetch_parking_space(value)
                        if parking_space:
                            data.append(build_form_item(None, "parking", parking_space))
                            return data
                    elif location_type == "Lokal":
                        # Fetch facility
                        facility = self.fetch_facility(value)
                        if facility:
                            maintenance_units = (
                                self.fetch_maintenance_units(
                                    facility["property"]["code"], location_type
                                )
                                if location_type in MAINTENANCE_UNIT_TYPES
                                else []
                            )

                            data.append(
                                build_form_item(
                                    None, "facility", facility, maintenance_units
                                )
                            )
                            return data
                    else:
                        # Default to fetching as residence (for "Lägenhet" and other residence types)
                        rental_property = self.fetch_residence(value)
                        if rental_property:
                            maintenance_units = (
                                self.fetch_maintenance_units(
                                    rental_property["property"]["code"], location_type
                                )
                                if location_type in MAINTENANCE_UNIT_TYPES
                                else []
                            )

                            data.append(
                                build_form_item(
                                    None,
                                    "residence",
                                    rental_property,
                                    maintenance_units,
                                )
                            )
                            return data
                except Exception:
                    pass

            return None
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
            raise err


class OneCoreException(Exception):
    def __init__(self, message):
        super().__init__(message)
