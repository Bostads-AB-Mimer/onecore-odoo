import logging
import time

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Base URL of the app's workflow API, e.g. https://apps.mimer.nu/api/1.1/wf
API_URL_PARAM = "time_report_api_url"
API_TOKEN_PARAM = "time_report_api_token"
CREATE_TIME_REPORT = "create_time_report"
GET_USER_BY_EMAIL = "get_user_by_email"
REQUEST_TIMEOUT = 15
NOT_CONFIGURED_MESSAGE = (
    "Tidsrapporteringen är inte konfigurerad (systemparametern "
    f"{API_URL_PARAM} saknas). Kontakta en administratör."
)
# Only users that exist are cached: a user added in the app is picked up at
# once, while a found user doesn't cost a lookup on every open and submit.
USER_CACHE_TTL = 600
_user_cache = {}


class TimeReportService:
    """Talks to the time reporting app (apps.mimer.nu)."""

    def __init__(self, env):
        self.env = env

    def _get_param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def get_api_url(self):
        """Configured base URL, or False (logged) when the parameter is missing."""
        url = self._get_param(API_URL_PARAM)
        if not url:
            _logger.error(
                "System parameter %s is not set; time reports cannot be sent.",
                API_URL_PARAM,
            )
        return url

    def _endpoint(self, name):
        base = self.get_api_url()
        if not base:
            raise UserError(NOT_CONFIGURED_MESSAGE)
        base = base.rstrip("/")
        # Tolerate the full create URL, which this parameter used to hold.
        if base.endswith(f"/{CREATE_TIME_REPORT}"):
            base = base[: -len(CREATE_TIME_REPORT) - 1]
        return f"{base}/{name}"

    def _post(self, endpoint, payload):
        url = self._endpoint(endpoint)
        headers = {"Content-Type": "application/json"}
        token = self._get_param(API_TOKEN_PARAM)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.exceptions.RequestException as e:
            _logger.exception("Time report request to %s failed: %s", endpoint, e)
            raise UserError(
                "Kunde inte nå tidsrapporteringen. Försök igen om en stund."
            ) from e

        if not response.ok:
            _logger.error(
                "Time report %s rejected (%s): %s",
                endpoint,
                response.status_code,
                response.text,
            )
            raise UserError(
                f"Tidsrapporteringen svarade med fel ({response.status_code}). "
                "Försök igen om en stund."
            )

        try:
            return response.json()
        except ValueError:
            return {}

    def user_exists(self, email):
        """Is ``email`` a user in the time reporting app?

        The app answers with the user in ``response`` for a known user and
        ``{"response": {}}`` otherwise. Raises UserError when it can't be asked.
        """
        if not email:
            return False
        key = (self.env.cr.dbname, email.strip().lower())
        cached = _user_cache.get(key)
        if cached and time.monotonic() < cached:
            return True

        data = self._post(GET_USER_BY_EMAIL, {"email": email})
        # An empty response ({}) is the app's only "no such user"; don't depend
        # on the exact shape of a found user.
        user = data.get("response", data) if isinstance(data, dict) else None
        found = bool(user)
        _logger.info(
            "Time report user lookup for %s via %s: %s (response: %s)",
            email,
            self._endpoint(GET_USER_BY_EMAIL),
            "found" if found else "missing",
            data,
        )
        if found:
            _user_cache[key] = time.monotonic() + USER_CACHE_TTL
        return found

    def create_time_report(self, payload):
        return self._post(CREATE_TIME_REPORT, payload)
