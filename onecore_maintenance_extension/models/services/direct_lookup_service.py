"""Direct paste-to-populate lookups for tenant and rental object (MIM-1841).

Fills either the object field group OR the tenant field group of a maintenance
request directly from ``core_api``, reusing the existing option-record and
``FormFieldService`` machinery. The two fills are strictly independent — the
object fill never touches tenant data and vice versa.
"""

import logging

from ..handlers.rental_property_handler import RentalPropertyHandler
from ..handlers.parking_space_handler import ParkingSpaceHandler
from ..handlers.facility_handler import FacilityHandler
from ..utils.helpers import get_tenant_name, get_main_phone_number
from .form_field_service import FormFieldService

_logger = logging.getLogger(__name__)

# space_caption -> how to fetch and where to put the result. Only rentalId-bearing
# space types appear here; any other space_caption is a no-op for object lookup.
_OBJECT_ROUTES = {
    "Lägenhet": {
        "fetch": "fetch_residence",
        "data_key": "rental_property",
        "option_model": "maintenance.rental.property.option",
        "option_field": "rental_property_option_id",
        "handler": RentalPropertyHandler,
        "update": "update_rental_property_fields",
    },
    "Bilplats": {
        "fetch": "fetch_parking_space",
        "data_key": "parking_space",
        "option_model": "maintenance.parking.space.option",
        "option_field": "parking_space_option_id",
        "handler": ParkingSpaceHandler,
        "update": "update_parking_space_fields",
    },
    "Lokal": {
        "fetch": "fetch_facility",
        "data_key": "facility",
        "option_model": "maintenance.facility.option",
        "option_field": "facility_option_id",
        "handler": FacilityHandler,
        "update": "update_facility_fields",
    },
}


class DirectLookupService:
    """Fill the object or tenant field group directly from a pasted id."""

    def __init__(self, env, core_api):
        self.env = env
        self.core_api = core_api
        self.form_field_service = FormFieldService(env)

    def populate_rental_object(self, record, rental_id):
        """Fill the object field group for ``record.space_caption`` from a rentalId.

        Returns an onchange ``warning`` dict when nothing is found, else ``None``.
        No-op (``None``) when the space type has no rentalId.
        """
        route = _OBJECT_ROUTES.get(record.space_caption)
        if not route:
            return None

        try:
            data = getattr(self.core_api, route["fetch"])(rental_id)
        except Exception as err:
            _logger.info("Rental object lookup failed for %s: %s", rental_id, err)
            data = None

        if not data:
            return self._rental_object_not_found(rental_id)

        uid = self.env.user.id
        # Clear any leftover options of this type for the user, then let the
        # handler create fresh ones. lease=None guarantees no tenant/lease options.
        self.env[route["option_model"]].search([("user_id", "=", uid)]).unlink()

        item = {
            "lease": None,
            "rental_property": None,
            "parking_space": None,
            "facility": None,
            "maintenance_units": [],
        }
        item[route["data_key"]] = data
        route["handler"](record, self.core_api).update_form_options([item])

        option = self.env[route["option_model"]].search(
            [("user_id", "=", uid)], limit=1
        )
        if not option:
            return self._rental_object_not_found(rental_id)

        record[route["option_field"]] = option.id
        getattr(self.form_field_service, route["update"])(record)
        return None

    def _rental_object_not_found(self, rental_id):
        return {
            "warning": {
                "title": "Inget hyresobjekt hittades",
                "message": (
                    f"Inget hyresobjekt hittades för objektnummer {rental_id}. "
                    "Kontrollera att numret är korrekt."
                ),
            }
        }
