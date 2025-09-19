import logging
from odoo import _, exceptions
from ..utils.helpers import get_tenant_name, get_main_phone_number

_logger = logging.getLogger(__name__)


class BaseMaintenanceHandler:
    """Base class for handling different types of maintenance requests."""

    def __init__(self, maintenance_request, core_api):
        self.record = maintenance_request
        self.env = maintenance_request.env
        self.core_api = core_api

    def handle_search(self, search_type, search_value, space_caption):
        """Handle search logic for this type of maintenance request."""
        raise NotImplementedError("Subclasses must implement handle_search method")

    def update_form_options(self, data):
        """Update form options with search results."""
        raise NotImplementedError(
            "Subclasses must implement update_form_options method"
        )

    def _delete_options(self):
        """Delete existing user options."""
        self.env["maintenance.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.building.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.staircase.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.rental.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.maintenance.unit.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.parking.space.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.facility.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.tenant.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()

    def _create_lease_option(
        self,
        lease,
        parking_space_option_id=None,
        rental_property_option_id=None,
        facility_option_id=None,
    ):
        """Create a lease option record with common lease data."""
        lease_data = {
            "user_id": self.env.user.id,
            "name": lease["leaseId"],
            "lease_number": lease["leaseNumber"],
            "lease_type": lease["type"],
            "lease_start_date": lease["leaseStartDate"],
            "lease_end_date": lease["lastDebitDate"],
            "contract_date": lease["contractDate"],
            "approval_date": lease["approvalDate"],
        }

        if parking_space_option_id:
            lease_data["parking_space_option_id"] = parking_space_option_id
        if rental_property_option_id:
            lease_data["rental_property_option_id"] = rental_property_option_id
        if facility_option_id:
            lease_data["facility_option_id"] = facility_option_id

        return self.env["maintenance.lease.option"].create(lease_data)

    def _create_tenant_options(self, tenants):
        """Create tenant option records for a list of tenants."""
        for tenant in tenants:
            existing_tenant = self.env["maintenance.tenant.option"].search(
                [("contact_code", "=", tenant["contactCode"])], limit=1
            )

            if not existing_tenant:
                name = get_tenant_name(tenant)
                phone_number = get_main_phone_number(tenant)

                self.env["maintenance.tenant.option"].create(
                    {
                        "user_id": self.env.user.id,
                        "name": name,
                        "contact_code": tenant["contactCode"],
                        "contact_key": tenant["contactKey"],
                        "national_registration_number": tenant.get(
                            "nationalRegistrationNumber"
                        ),
                        "email_address": tenant.get("emailAddress"),
                        "phone_number": phone_number,
                        "is_tenant": tenant["isTenant"],
                        "special_attention": tenant.get("specialAttention"),
                    }
                )

    def _raise_no_results_error(self, search_value):
        """Raise a user error when no results are found."""
        raise exceptions.UserError(
            _(
                "Kunde inte hitta något resultat för %s",
                search_value,
            )
        )
