"""Fetch + create transient option records for the backfill wizard (MIM-1841).

Given a rentalId or contactCode, fetch from OneCore and create the matching
transient *option* record, returning it for preview. Persisting the option onto
the request (materializing the permanent record) is done by the wizard via
``RecordManagementService._save_*`` — NOT here. Object and tenant paths are
independent.
"""

import logging

from ..handlers.base_handler import BaseMaintenanceHandler
from ..handlers.rental_property_handler import RentalPropertyHandler
from ..handlers.parking_space_handler import ParkingSpaceHandler
from ..handlers.facility_handler import FacilityHandler
from ..utils.helpers import (
    get_tenant_name,
    get_main_phone_number,
    select_active_lease,
)

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

    def create_tenant_option(self, request, contact_code):
        """Resolve a contact from its (unfiltered) leases and create a tenant option.

        Also creates lease options for every lease the contact is a tenant on and
        links the tenant option to the *active* one (same status-priority the
        create-time search uses), so confirming the wizard attaches the contact's
        current contract (unlocking the contract/phone/email/pet block in the
        form). The associated rental object is intentionally NOT attached.

        Returns the tenant option (with `lease_option_id` set when a lease was
        found), or None if the contact could not be resolved.
        """
        try:
            leases = self.core_api.fetch_contact_leases(contact_code)
        except Exception as err:
            _logger.warning("Tenant lookup failed for %s: %s", contact_code, err)
            leases = []

        # Collect (lease, tenant) pairs for every lease the contact appears on.
        matches = []
        for lease in leases or []:
            for candidate in (lease.get("tenants") or []):
                if candidate.get("contactCode") == contact_code:
                    matches.append((lease, candidate))
                    break

        if not matches:
            return None

        uid = self.env.user.id
        self.env["maintenance.tenant.option"].search([("user_id", "=", uid)]).unlink()
        self.env["maintenance.lease.option"].search([("user_id", "=", uid)]).unlink()

        # Reuse the create-time lease-option builder (status normalization + name).
        handler = BaseMaintenanceHandler(request, self.core_api)
        lease_options = self.env["maintenance.lease.option"]
        for lease, _candidate in matches:
            try:
                lease_options |= handler._create_lease_option(lease)
            except Exception as err:
                _logger.warning(
                    "Could not build lease option for contact %s: %s",
                    contact_code,
                    err,
                )

        active_lease = select_active_lease(lease_options) if lease_options else False
        tenant = matches[0][1]
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
                "lease_option_id": active_lease.id if active_lease else False,
            }
        )
