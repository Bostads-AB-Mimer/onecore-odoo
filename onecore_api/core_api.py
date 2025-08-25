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
        print(f"API - fetching leases for {location_type}!")
        paths = {
            "leaseId": "/leases",
            "rentalObjectId": "/leases/by-rental-property-id",
            "contactCode": "/leases/by-contact-code",
            "pnr": "/leases/for",
        }

        if identifier not in paths:
            raise OneCoreException(f"Ogiltig söktyp: {identifier}")

        try:
            content = self._get_json(
                f"{paths[identifier]}/{urllib.parse.quote(str(value), safe='')}",
                params={"includeContacts": "true"},
            )

            # Filter response on space caption if needed
            filtered_content = self.filter_lease_on_location_type(
                content, location_type
            )

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
        if location_type == False or location_type == "Lägenhet":
            filtered_content = [
                item for item in data if item["type"].strip() == "Bostadskontrakt"
            ]
            return filtered_content
        elif location_type == "Bilplats":
            filtered_content = [
                item for item in data if item["type"].strip() == "P-Platskontrakt"
            ]
            return filtered_content
        else:
            return data

    def fetch_residence(self, id):
        return self._get_json(
            f"/propertyBase/residence/rental-id/{urllib.parse.quote(str(id), safe='')}"
        )

    def fetch_building(self, id):
        return self._get_json(
            f"/propertyBase/buildings/by-building-code/{urllib.parse.quote(str(id), safe='')}"
        )

    def fetch_properties(self, name, location_type):
        properties = self._get_json(
            f"/propertyBase/properties/search", params={"q": name}
        )
        data = []

        # FIXME it would be nice if we could run these in parallel
        for property in properties:
            maintenance_units = self.fetch_maintenance_units_for_property(
                property["code"]
            )
            data.append(
                {
                    "property": property,
                    "maintenance_units": self.filter_maintenance_units_by_location_type(
                        maintenance_units, location_type
                    ),
                }
            )

        return data

    def fetch_maintenance_units_for_property(self, code):
        return self._get_json(
            f"/propertyBase/maintenance-units/by-property-code/{urllib.parse.quote(str(code), safe='')}"
        )

    def fetch_maintenance_units(self, id, location_type):
        content = self._get_json(
            f"/propertyBase/maintenance-units/by-property-code/{urllib.parse.quote(str(id), safe='')}"
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
            f"/propertyBase/parking-spaces/by-rental-id/{urllib.parse.quote(str(id), safe='')}"
        )

    def fetch_form_data(self, identifier, value, location_type):
        fetch_fns = {
            "Bostadskontrakt": lambda id: self.fetch_residence(id),
            "P-Platskontrakt": lambda id: self.fetch_parking_space(id),
        }
        lease_types_with_maintenance_units = ["Bostadskontrakt"]

        try:
            leases = self.fetch_leases(identifier, value, location_type)

            print(f"API - fetched {len(leases)} leases for {location_type}!")

            if leases and len(leases) > 0:
                data = []

                # FIXME it would be nice if we could run these in parallel
                for lease in leases:
                    lease_type = lease["type"].strip()
                    if lease_type in fetch_fns:
                        rental_property = fetch_fns[lease_type](
                            lease["rentalPropertyId"]
                        )
                        parking_space = fetch_fns[lease_type](lease["rentalPropertyId"])
                        maintenance_units = (
                            self.fetch_maintenance_units(
                                rental_property["property"]["code"], location_type
                            )
                            if lease_type in lease_types_with_maintenance_units
                            else []
                        )

                        data.append(
                            {
                                "lease": lease,
                                "rental_property": rental_property,
                                "parking_space": parking_space,
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
