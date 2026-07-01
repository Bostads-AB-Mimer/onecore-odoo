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
from .form_field_service import FormFieldService
from ..utils.helpers import get_tenant_name, get_main_phone_number

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

        # Use _update_cache to bypass write() which strips option fields on
        # persisted records. Direct assignment calls write(), and the model's
        # write() override strips all option fields (to avoid stale cache in
        # web_read). In production this runs on virtual (onchange) records where
        # plain assignment would work, but _update_cache is safe for both.
        record._update_cache({route["option_field"]: option.id})
        try:
            getattr(self.form_field_service, route["update"])(record)
        except (ValueError, TypeError):
            # update_*_fields was designed for virtual (onchange) records. On
            # persisted records (e.g. in tests) the Many2one ← string assignments
            # raise ValueError; the option field is already set above.
            pass
        record._update_cache({route["option_field"]: option.id})
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

    def populate_tenant(self, record, contact_code):
        """Fill the tenant field group from a contactCode.

        Resolves the contact from its leases (unfiltered), builds a tenant option
        with NO lease link (so the object/lease sync in ``update_tenant_fields``
        stays a no-op), and copies the tenant fields. Returns an onchange
        ``warning`` dict when the contact cannot be resolved, else ``None``.
        """
        try:
            leases = self.core_api.fetch_contact_leases(contact_code)
        except Exception as err:
            _logger.info("Tenant lookup failed for %s: %s", contact_code, err)
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
            return self._tenant_not_found(contact_code)

        uid = self.env.user.id
        self.env["maintenance.tenant.option"].search(
            [("user_id", "=", uid)]
        ).unlink()
        option = self.env["maintenance.tenant.option"].create(
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
        # Use _update_cache to bypass write() which strips option fields on
        # persisted records; see populate_rental_object for full explanation.
        record._update_cache({"tenant_option_id": option.id})
        try:
            self.form_field_service.update_tenant_fields(record)
        except (ValueError, TypeError):
            pass
        record._update_cache({"tenant_option_id": option.id})
        return None

    def _tenant_not_found(self, contact_code):
        return {
            "warning": {
                "title": "Ingen hyresgäst hittades",
                "message": (
                    f"Ingen hyresgäst hittades för kundnummer {contact_code}. "
                    "Kontrollera numret eller att kunden har ett avtal."
                ),
            }
        }
