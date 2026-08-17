"""Backfill lookups for the add/change wizard (MIM-1841).

Two entry points, both contract-driven:

* objektnummer (rentalId): fetch the object's contracts once, derive the object
  kind from each contract's type, then fetch the object itself. No contract at
  all → the object is offered as vacant.
* kundnummer (contactCode): fetch ALL of the customer's contracts across object
  types (apartment / parking / lokal). Picking a contract attaches its object +
  tenant and (in the wizard) aligns the request's space type.

Both end up in :meth:`DirectLookupService._build_options`, which reuses the
space-type handlers so the created lease options are linked to their object
option and tenant options.

A OneCore call that *fails* (outage, auth, 5xx) raises :class:`LookupFailed`;
"no such object/customer" is a plain empty result. The wizard needs the
difference to avoid telling the user their number is wrong when it isn't.
"""

import logging

from ..handlers.base_handler import BaseMaintenanceHandler
from ..handlers.rental_property_handler import RentalPropertyHandler
from ..handlers.parking_space_handler import ParkingSpaceHandler
from ..handlers.facility_handler import FacilityHandler
from ....onecore_api import core_api

_logger = logging.getLogger(__name__)


class LookupFailed(Exception):
    """A OneCore call failed — as opposed to answering "nothing found"."""


# One entry per rentalId-bearing object kind. Keys match
# ``core_api.OBJECT_KIND_FETCHERS`` / ``core_api.LEASE_TYPE_TO_OBJECT_KIND``.
_ROUTES = {
    "residence": {
        "space": "Lägenhet",
        "option_model": "maintenance.rental.property.option",
        "option_field": "rental_property_option_id",
        "handler": RentalPropertyHandler,
        "save_method": "_save_rental_property",
        "record_field": "rental_property_id",
    },
    "parking": {
        "space": "Bilplats",
        "option_model": "maintenance.parking.space.option",
        "option_field": "parking_space_option_id",
        "handler": ParkingSpaceHandler,
        "save_method": "_save_parking_space",
        "record_field": "parking_space_id",
    },
    "facility": {
        "space": "Lokal",
        "option_model": "maintenance.facility.option",
        "option_field": "facility_option_id",
        "handler": FacilityHandler,
        "save_method": "_save_facility",
        "record_field": "facility_id",
    },
}

_OPTION_MODEL_TO_KIND = {route["option_model"]: kind for kind, route in _ROUTES.items()}


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


def _is_not_found(err):
    """True when OneCore answered "no such record" (404) rather than failing."""
    response = getattr(err, "response", None)
    return getattr(response, "status_code", None) == 404


class DirectLookupService:
    """Fetch OneCore data and create the linked transient option records."""

    def __init__(self, env, core_api):
        self.env = env
        self.core_api = core_api

    # ------------------------------------------------------------------ public
    def load_object_contracts(self, request, rental_id):
        """Objektnummer entry: resolve the object regardless of the request's
        current space type and create its object + contract + tenant options.

        Returns ``{"lease_options", "object_option"}`` or ``None`` when OneCore
        knows no such object. ``object_option`` carries the vacant case (object
        found, no contract). Raises :class:`LookupFailed` if a call failed.
        """
        leases = self._fetch_leases("rentalObjectId", rental_id)
        if leases:
            lease_options = self._build_options(request, leases)
            if lease_options:
                return {"lease_options": lease_options, "object_option": None}
            return None
        return self._load_vacant_object(request, rental_id)

    def load_contact_contracts(self, request, contact_code):
        """Kundnummer entry: fetch ALL of the customer's contracts (any object
        type) and create their linked object/lease/tenant options.

        Returns ``{"lease_options"}`` or ``None``; raises :class:`LookupFailed`
        if a call failed.
        """
        leases = self._fetch_leases("contactCode", contact_code)
        if not leases:
            return None
        lease_options = self._build_options(request, leases)
        return {"lease_options": lease_options} if lease_options else None

    # ----------------------------------------------------------------- fetching
    def _fetch_leases(self, identifier, value):
        try:
            return self.core_api.fetch_leases_unfiltered(identifier, value)
        except Exception as err:
            if _is_not_found(err):
                return []
            _logger.warning("Lease lookup failed for %s %s: %s", identifier, value, err)
            raise LookupFailed(str(err)) from err

    def _fetch_object(self, kind, rental_id):
        """One object payload, or None when OneCore has no such object of that
        kind. Raises :class:`LookupFailed` when the call itself failed."""
        fetcher = getattr(self.core_api, core_api.OBJECT_KIND_FETCHERS[kind])
        try:
            return fetcher(rental_id)
        except Exception as err:
            if _is_not_found(err):
                return None
            _logger.warning(
                "Object lookup failed for %s as %s: %s", rental_id, kind, err
            )
            raise LookupFailed(str(err)) from err

    # ------------------------------------------------------------------ options
    def _build_options(self, request, leases):
        """Create the object/lease/tenant options for ``leases``, fetching each
        distinct object once. Returns the resulting lease options (possibly
        empty)."""
        BaseMaintenanceHandler(request, self.core_api)._delete_options()

        objects = {}
        failed = False
        for lease in leases:
            kind = core_api.LEASE_TYPE_TO_OBJECT_KIND.get(
                (lease.get("type") or "").strip()
            )
            route = _ROUTES.get(kind)
            if not route:
                continue

            rental_id = lease.get("rentalPropertyId")
            if (kind, rental_id) not in objects:
                try:
                    objects[(kind, rental_id)] = self._fetch_object(kind, rental_id)
                except LookupFailed:
                    # One unreachable object must not sink the whole result set;
                    # only report failure if nothing at all could be built.
                    objects[(kind, rental_id)] = None
                    failed = True
            obj = objects[(kind, rental_id)]
            if not obj:
                continue

            if not self._create_options(
                request, route, core_api.build_form_item(lease, kind, obj)
            ):
                failed = True

        lease_options = self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if not lease_options and failed:
            raise LookupFailed("No options could be built from the OneCore payload")
        return lease_options

    def _load_vacant_object(self, request, rental_id):
        """No contract for this objektnummer: the object's kind is unknown, so try
        each fetcher until one answers, and offer the object as vacant."""
        failed = False
        for kind, route in _ROUTES.items():
            try:
                obj = self._fetch_object(kind, rental_id)
            except LookupFailed:
                failed = True
                continue
            if not obj:
                continue

            BaseMaintenanceHandler(request, self.core_api)._delete_options()
            if not self._create_options(
                request, route, core_api.build_form_item(None, kind, obj)
            ):
                raise LookupFailed("Could not build options for the vacant object")
            object_option = self.env[route["option_model"]].search(
                [("user_id", "=", self.env.user.id)], limit=1
            )
            if not object_option:
                return None
            return {
                "lease_options": self.env["maintenance.lease.option"].browse(),
                "object_option": object_option,
            }

        if failed:
            raise LookupFailed("Object lookup failed for every object kind")
        return None

    def _create_options(self, request, route, item):
        """Hand one payload item to its space-type handler.

        Guarded: an unexpected/partial payload would otherwise surface as a 500
        after ``_delete_options()`` has already wiped the form's dropdowns.
        Returns False (logged) instead, so the caller can report a plain message.
        """
        try:
            route["handler"](request, self.core_api).update_form_options([item])
            return True
        except Exception as err:
            _logger.warning(
                "Could not build %s options from the OneCore payload: %s",
                route["space"],
                err,
                exc_info=True,
            )
            return False
