"""Backfill lookups for the add/change wizard (MIM-1841).

Two entry points, both contract-driven:

* objektnummer (rentalId): the object is of the request's space type, so we fetch
  by the request's space_caption and offer that object's contracts.
* kundnummer (contactCode): a customer, so we fetch ALL of the customer's contracts
  across object types (apartment / parking / lokal). Picking a contract attaches
  its object + tenant and (in the wizard) aligns the request's space type.

Both reuse ``core_api.fetch_form_data`` / the space-type handlers so the created
lease options are linked to their object option and tenant options.
"""

import logging

from ..handlers.base_handler import BaseMaintenanceHandler
from ..handlers.rental_property_handler import RentalPropertyHandler
from ..handlers.parking_space_handler import ParkingSpaceHandler
from ..handlers.facility_handler import FacilityHandler

_logger = logging.getLogger(__name__)

# One entry per rentalId-bearing object kind.
_ROUTES = {
    "residence": {
        "space": "Lägenhet",
        "option_model": "maintenance.rental.property.option",
        "option_field": "rental_property_option_id",
        "handler": RentalPropertyHandler,
        "save_method": "_save_rental_property",
        "record_field": "rental_property_id",
        "data_key": "rental_property",
        "fetch": "fetch_residence",
    },
    "parking": {
        "space": "Bilplats",
        "option_model": "maintenance.parking.space.option",
        "option_field": "parking_space_option_id",
        "handler": ParkingSpaceHandler,
        "save_method": "_save_parking_space",
        "record_field": "parking_space_id",
        "data_key": "parking_space",
        "fetch": "fetch_parking_space",
    },
    "facility": {
        "space": "Lokal",
        "option_model": "maintenance.facility.option",
        "option_field": "facility_option_id",
        "handler": FacilityHandler,
        "save_method": "_save_facility",
        "record_field": "facility_id",
        "data_key": "facility",
        "fetch": "fetch_facility",
    },
}

_SPACE_TO_KIND = {"Lägenhet": "residence", "Bilplats": "parking", "Lokal": "facility"}

_OPTION_MODEL_TO_KIND = {
    "maintenance.rental.property.option": "residence",
    "maintenance.parking.space.option": "parking",
    "maintenance.facility.option": "facility",
}

_LEASE_TYPE_TO_KIND = {
    "Bostadskontrakt": "residence",
    "Kooperativ hyresrätt": "residence",
    "P-Platskontrakt": "parking",
    "Garagekontrakt": "parking",
    "Lokalkontrakt": "facility",
}


def route_for_space(space_caption):
    """Route for a request's space type, or None if not rentalId-bearing."""
    return _ROUTES.get(_SPACE_TO_KIND.get(space_caption))


def route_for_lease_option(lease_option):
    """Route for a contract, derived from which object option it is linked to."""
    if lease_option.rental_property_option_id:
        return _ROUTES["residence"]
    if lease_option.parking_space_option_id:
        return _ROUTES["parking"]
    if lease_option.facility_option_id:
        return _ROUTES["facility"]
    return None


def route_for_object_option(object_option):
    """Route for a bare object option, derived from its model."""
    return _ROUTES.get(_OPTION_MODEL_TO_KIND.get(object_option._name))


def all_routes():
    return list(_ROUTES.values())


class DirectLookupService:
    """Fetch OneCore data and create the linked transient option records."""

    def __init__(self, env, core_api):
        self.env = env
        self.core_api = core_api

    def load_object_contracts(self, request, rental_id):
        """Objektnummer entry: resolve the object's kind (residence / parking /
        facility) regardless of the request's current space type, then create its
        object + contract + tenant options. Returns ``{"lease_options",
        "object_option"}`` or ``None``. ``object_option`` covers the vacant case
        (object found, no contract).

        The kind is discovered by probing ``fetch_form_data`` per object type — for
        the wrong type OneCore finds nothing, for the right one it returns the
        object with its contracts/tenants.
        """
        found_route = None
        data = None
        for route in _ROUTES.values():
            try:
                probe = self.core_api.fetch_form_data(
                    "rentalObjectId", rental_id, route["space"]
                )
            except Exception as err:
                _logger.warning(
                    "Object lookup failed for %s (%s): %s",
                    rental_id,
                    route["space"],
                    err,
                )
                probe = None
            if probe:
                found_route = route
                data = probe
                break
        if not data:
            return None

        uid = self.env.user.id
        BaseMaintenanceHandler(request, self.core_api)._delete_options()
        found_route["handler"](request, self.core_api).update_form_options(data)

        lease_options = self.env["maintenance.lease.option"].search(
            [("user_id", "=", uid)]
        )
        object_option = self.env[found_route["option_model"]].search(
            [("user_id", "=", uid)], limit=1
        )
        if not lease_options and not object_option:
            return None
        return {"lease_options": lease_options, "object_option": object_option}

    def load_contact_contracts(self, request, contact_code):
        """Kundnummer entry: fetch ALL of the customer's contracts (any object type)
        and create their linked object/lease/tenant options. Returns
        ``{"lease_options"}`` or ``None``."""
        try:
            leases = self.core_api.fetch_contact_leases(contact_code)
        except Exception as err:
            _logger.warning("Tenant lookup failed for %s: %s", contact_code, err)
            leases = []
        if not leases:
            return None

        uid = self.env.user.id
        BaseMaintenanceHandler(request, self.core_api)._delete_options()
        for lease in leases:
            route = _ROUTES.get(
                _LEASE_TYPE_TO_KIND.get((lease.get("type") or "").strip())
            )
            if not route:
                continue
            try:
                obj = getattr(self.core_api, route["fetch"])(
                    lease.get("rentalPropertyId")
                )
            except Exception as err:
                _logger.warning(
                    "Could not fetch object for lease %s: %s",
                    lease.get("leaseId"),
                    err,
                )
                obj = None
            if not obj:
                continue
            item = {
                "lease": lease,
                "rental_property": None,
                "parking_space": None,
                "facility": None,
                "maintenance_units": [],
            }
            item[route["data_key"]] = obj
            route["handler"](request, self.core_api).update_form_options([item])

        lease_options = self.env["maintenance.lease.option"].search(
            [("user_id", "=", uid)]
        )
        if not lease_options:
            return None
        return {"lease_options": lease_options}
