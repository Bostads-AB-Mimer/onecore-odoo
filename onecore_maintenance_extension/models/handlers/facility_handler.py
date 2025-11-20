import logging
from .base_handler import BaseMaintenanceHandler

_logger = logging.getLogger(__name__)


class FacilityHandler(BaseMaintenanceHandler):
    """Handler for facility-related maintenance requests."""

    def handle_search(self, search_type, search_value, space_caption):
        """Handle search for facility requests.

        FacilityHandler can handle:
        - lease-based searches (pnr, contactCode, leaseId, rentalObjectId): Find facilities via tenant/lease data
        """
        if search_type in ["pnr", "contactCode", "leaseId", "rentalObjectId"]:
            work_order_data = self.core_api.fetch_form_data(
                search_type, search_value, space_caption
            )

            if not work_order_data:
                _logger.info("No data found in response.")
                return self._return_no_results_warning(search_value)

            self.update_form_options(work_order_data)
            self._set_form_selections()
        else:
            raise ValueError(
                f"FacilityHandler does not support search type: {search_type}"
            )

    def update_form_options(self, work_order_data):
        """Update form options with facility data."""
        for item in work_order_data:
            facility = item.get("facility")
            lease = item["lease"]

            if not facility:
                continue

            facility_option = self.env["maintenance.facility.option"].create(
                {
                    "user_id": self.env.user.id,
                    "name": facility.get("name", "Namn saknas"),
                    "code": facility.get("code"),
                    "type_name": facility.get("type", {}).get("name"),
                    "type_code": facility.get("type", {}).get("code"),
                    "area": str(facility.get("area", "")),
                    "building_code": facility.get("building", {}).get("code"),
                    "building_name": facility.get("building", {}).get("name"),
                    "property_code": facility.get("property", {}).get("code"),
                    "property_name": facility.get("property", {}).get("name"),
                    "rental_type": facility.get("rentalInformation", {})
                    .get("type", {})
                    .get("name"),
                }
            )

            self._create_lease_option(lease, facility_option_id=facility_option.id)

            self._create_tenant_options(lease["tenants"])

    def _set_form_selections(self):
        """Set form selections for facility options."""
        facility_options = self.env["maintenance.facility.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if facility_options:
            self.record.facility_option_id = facility_options[0].id

        lease_options = self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if lease_options:
            self.record.lease_option_id = lease_options[0].id

        tenant_options = self.env["maintenance.tenant.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if tenant_options:
            self.record.tenant_option_id = tenant_options[0].id
