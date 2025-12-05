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
                        rental_property = fetch_fns[lease_type](
                            lease["rentalPropertyId"]
                        )

                        parking_space = fetch_fns[lease_type](lease["rentalPropertyId"])
                        facility = fetch_fns[lease_type](lease["rentalPropertyId"])

                        maintenance_units = (
                            self.fetch_maintenance_units(
                                rental_property["property"]["code"], location_type
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

            return None
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
            raise err


class OneCoreException(Exception):
    def __init__(self, message):
        super().__init__(message)
