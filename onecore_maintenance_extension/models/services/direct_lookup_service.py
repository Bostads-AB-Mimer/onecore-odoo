"""Fetch + create transient option records for the backfill wizard (MIM-1841).

Given a rentalId or contactCode, fetch from OneCore and create the matching
transient *option* record, returning it for preview. Persisting the option onto
the request (materializing the permanent record) is done by the wizard via
``RecordManagementService._save_*`` — NOT here. Object and tenant paths are
independent.
"""

import logging

from ..handlers.rental_property_handler import RentalPropertyHandler
from ..handlers.parking_space_handler import ParkingSpaceHandler
from ..handlers.facility_handler import FacilityHandler
from ..utils.helpers import get_tenant_name, get_main_phone_number

_logger = logging.getLogger(__name__)

# space_caption -> fetch method, option model, and the RecordManagementService
# materializer the wizard calls on confirm. Only rentalId-bearing space types.
_OBJECT_ROUTES = {
    "Lägenhet": {
        "fetch": "fetch_residence",
        "data_key": "rental_property",
        "option_model": "maintenance.rental.property.option",
        "option_field": "rental_property_option_id",
        "handler": RentalPropertyHandler,
        "save_method": "_save_rental_property",
    },
    "Bilplats": {
        "fetch": "fetch_parking_space",
        "data_key": "parking_space",
        "option_model": "maintenance.parking.space.option",
        "option_field": "parking_space_option_id",
        "handler": ParkingSpaceHandler,
        "save_method": "_save_parking_space",
    },
    "Lokal": {
        "fetch": "fetch_facility",
        "data_key": "facility",
        "option_model": "maintenance.facility.option",
        "option_field": "facility_option_id",
        "handler": FacilityHandler,
        "save_method": "_save_facility",
    },
}


class DirectLookupService:
    """Fetch OneCore data and create the matching transient option record."""

    def __init__(self, env, core_api):
        self.env = env
        self.core_api = core_api

    def route_for(self, space_caption):
        """Return the object route for a space_caption, or None if not rentalId-bearing."""
        return _OBJECT_ROUTES.get(space_caption)

    def create_rental_object_option(self, request, rental_id):
        """Fetch the object (routed by request.space_caption) and create its option.

        Returns the created transient option record, or None if the space type has
        no rentalId or nothing was found. Does not touch the request.
        """
        route = _OBJECT_ROUTES.get(request.space_caption)
        if not route:
            return None

        try:
            data = getattr(self.core_api, route["fetch"])(rental_id)
        except Exception as err:
            _logger.warning("Rental object lookup failed for %s: %s", rental_id, err)
            data = None

        if not data:
            return None

        uid = self.env.user.id
        self.env[route["option_model"]].search([("user_id", "=", uid)]).unlink()

        item = {
            "lease": None,
            "rental_property": None,
            "parking_space": None,
            "facility": None,
            "maintenance_units": [],
        }
        item[route["data_key"]] = data
        route["handler"](request, self.core_api).update_form_options([item])

        return self.env[route["option_model"]].search(
            [("user_id", "=", uid)], limit=1
        ) or None

    def create_tenant_option(self, contact_code):
        """Resolve a contact from its (unfiltered) leases and create a tenant option.

        The option has NO lease link. Returns the option, or None if not found.
        """
        try:
            leases = self.core_api.fetch_contact_leases(contact_code)
        except Exception as err:
            _logger.warning("Tenant lookup failed for %s: %s", contact_code, err)
            leases = []

        tenant = None
        for lease in leases or []:
            for candidate in (lease.get("tenants") or []):
                if candidate.get("contactCode") == contact_code:
                    tenant = candidate
                    break
            if tenant:
                break

        if not tenant:
            return None

        uid = self.env.user.id
        self.env["maintenance.tenant.option"].search([("user_id", "=", uid)]).unlink()
        return self.env["maintenance.tenant.option"].create(
            {
                "user_id": uid,
                "name": get_tenant_name(tenant),
                "contact_code": tenant["contactCode"],
                "contact_key": tenant["contactKey"],
                "national_registration_number": tenant.get(
                    "nationalRegistrationNumber"
                ),
                "email_address": tenant.get("emailAddress"),
                "phone_number": get_main_phone_number(tenant),
                "is_tenant": tenant["isTenant"],
                "special_attention": tenant.get("specialAttention"),
            }
        )
