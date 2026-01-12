import requests
import logging
import urllib.parse
import json

_logger = logging.getLogger(__name__)


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

    def fetch_leases(self, identifier, value, location_type):
        paths = {
            "leaseId": "/leases",
            "rentalObjectId": "/leases/by-rental-property-id",
            "contactCode": "/leases/by-contact-code",
            "pnr": "/leases/by-pnr",
        }

        if identifier not in paths:
            raise OneCoreException(f"Ogiltig söktyp: {identifier}")

        try:
            content = self._get_json(
                f"{paths[identifier]}/{urllib.parse.quote(str(value), safe='')}",
                params={"includeContacts": "true", "includeUpcomingLeases": "true"},
            )

            # If no content returned, return empty list.
            if content is None:
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
                and item.get("type", "").strip() == "P-Platskontrakt"
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

    def fetch_rooms(self, residence_id):
        """Fetch rooms for a residence."""
        return self._get_json(
            f"/rooms?residenceId={urllib.parse.quote(str(residence_id), safe='')}"
        )

    def fetch_components_by_room(self, room_id):
        """Fetch components for a specific room."""
        return self._get_json(
            f"/components/by-room/{urllib.parse.quote(str(room_id), safe='')}"
        )

    def fetch_component_models(self, model_name, page=1, limit=20, type_id=None, subtype_id=None):
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
            params={"categoryId": category_id, "page": page, "limit": limit}
        )

    def fetch_component_subtypes(self, type_id, page=1, limit=100):
        """Fetch component subtypes for a type."""
        return self._get_json(
            "/component-subtypes",
            params={"typeId": type_id, "page": page, "limit": limit}
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
        response = self.request("PUT", f"/component-installations/{installation_id}", json=payload)
        response.raise_for_status()
        return response.json()

    def fetch_form_data(self, identifier, value, location_type):
        fetch_fns = {
            "Bostadskontrakt": lambda id: self.fetch_residence(id),
            "Kooperativ hyresrätt": lambda id: self.fetch_residence(id),
            "P-Platskontrakt": lambda id: self.fetch_parking_space(id),
            "Lokalkontrakt": lambda id: self.fetch_facility(id),
        }
        lease_types_with_maintenance_units = [
            "Bostadskontrakt",
            "Kooperativ hyresrätt",
            "Lokalkontrakt",
        ]

        maintenance_unit_types = ["Tvättstuga", "Miljöbod", "Lekplats"]
        try:
            leases = self.fetch_leases(identifier, value, location_type)

            if leases and len(leases) > 0:
                data = []

                for lease in leases:
                    # Skip if lease is None or missing required fields.
                    if not lease or not lease.get("type"):
                        continue

                    lease_type = lease["type"].strip()
                    if lease_type in fetch_fns:
                        fetched_data = fetch_fns[lease_type](
                            lease["rentalPropertyId"]
                        )

                        rental_property = fetched_data if lease_type == "Bostadskontrakt" or lease_type == "Kooperativ hyresrätt" else None
                        parking_space = fetched_data if lease_type == "P-Platskontrakt" else None
                        facility = fetched_data if lease_type == "Lokalkontrakt" else None

                        maintenance_units = (
                            self.fetch_maintenance_units(
                                fetched_data["property"]["code"], location_type
                            )
                            if lease_type in lease_types_with_maintenance_units
                            and location_type in maintenance_unit_types
                            else []
                        )

                        data.append(
                            {
                                "lease": lease,
                                "rental_property": rental_property,
                                "parking_space": parking_space,
                                "facility": facility,
                                "maintenance_units": maintenance_units,
                            }
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
                            data.append(
                                {
                                    "lease": None,
                                    "rental_property": None,
                                    "parking_space": parking_space,
                                    "facility": None,
                                    "maintenance_units": [],
                                }
                            )
                            return data
                    elif location_type == "Lokal":
                        # Fetch facility
                        facility = self.fetch_facility(value)
                        if facility:
                            maintenance_units = (
                                self.fetch_maintenance_units(
                                    facility["property"]["code"], location_type
                                )
                                if location_type in maintenance_unit_types
                                else []
                            )

                            data.append(
                                {
                                    "lease": None,
                                    "rental_property": None,
                                    "parking_space": None,
                                    "facility": facility,
                                    "maintenance_units": maintenance_units,
                                }
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
                                if location_type in maintenance_unit_types
                                else []
                            )

                            data.append(
                                {
                                    "lease": None,
                                    "rental_property": rental_property,
                                    "parking_space": None,
                                    "facility": None,
                                    "maintenance_units": maintenance_units,
                                }
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
