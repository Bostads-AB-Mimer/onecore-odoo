import requests
import logging
import urllib.parse

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

    def fetch_leases(self, identifier, value):
        paths = {
            "leaseId": "/leases",
            "rentalObjectId": "/leases/by-rental-property-id",
            "contactCode": "/leases/by-contact-code",
            "pnr": "/leases/for",
        }

        if identifier not in paths:
            raise OneCoreException(f"Ogiltig söktyp: {identifier}")

        try:
            response = self.request(
                "GET",
                f"{paths[identifier]}/{urllib.parse.quote(str(value), safe='')}",
                params={"includeContacts": "true"},
            )
            response.raise_for_status()
            content = response.json().get("content", {})

            return content if isinstance(content, list) else [content]
        except requests.HTTPError as http_err:
            raise OneCoreException(
                f"Kunde inte hitta något resultat för {identifier}: {value}. Det verkar som att det inte finns någon koppling till OneCore-servern.",
            )

    def fetch_residence(self, id):
        url = (
            f"/propertyBase/residence/rental-id/{urllib.parse.quote(str(id), safe='')}"
        )
        response = self.request("GET", url)
        response.raise_for_status()
        return response.json().get("content")

    def fetch_rental_property(self, identifier, value):
        fetch_fns = {
            "Bostadskontrakt": lambda id: self.fetch_residence(id),
        }

        try:
            leases = self.fetch_leases(identifier, value)

            if leases and len(leases) > 0:
                data = []

                for lease in leases:
                    lease_type = lease["type"].strip()
                    if lease_type in fetch_fns:
                        rental_property = fetch_fns[lease_type](
                            lease["rentalPropertyId"]
                        )

                        data.append(
                            {
                                "lease": lease,
                                "rental_property": rental_property,
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
