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
        if identifier == "leaseId":
            path = "/leases"
        elif identifier == "rentalObjectId":
            path = "/leases/by-rental-property-id"
        elif identifier == "contactCode":
            path = "/leases/by-contact-code"
        elif identifier == "pnr":
            path = "/leases/for"

        try:
            response = self.request(
                "GET", f"{path}/{urllib.parse.quote(str(value), safe='')}"
            )
            response.raise_for_status()
            return response.json().get("content", {})  # TODO returnera alltid lista?
        except requests.HTTPError as http_err:
            raise OneCoreException(
                _(
                    "Kunde inte hitta något resultat för %s: %s. Det verkar som att det inte finns någon koppling till OneCore-servern.",
                    identifier,
                    value,
                )
            )

    def fetch_rental_property(self, id):
        url = (
            f"/propertyBase/residence/rental-id/{urllib.parse.quote(str(id), safe='')}"
        )
        response = self.request("GET", url)
        response.raise_for_status()
        return response.json().get("content")


class OneCoreException(Exception):
    def __init__(self, message):
        super().__init__(message)
