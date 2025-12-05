import logging
from .base_handler import BaseMaintenanceHandler

_logger = logging.getLogger(__name__)


class ParkingSpaceHandler(BaseMaintenanceHandler):
    """Handler for parking space maintenance requests."""

    def handle_search(self, search_type, search_value, space_caption):
        """Handle search for parking space requests.

        ParkingSpaceHandler can handle:
        - lease-based searches (pnr, contactCode, leaseId, rentalObjectId): Find parking spaces via tenant/lease data
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
                f"ParkingSpaceHandler does not support search type: {search_type}"
            )

    def update_form_options(self, work_order_data):
        """Update form options with parking space data."""
        for item in work_order_data:
            parking_space = item.get("parking_space")
            lease = item["lease"]

            parking_space_info = (
                parking_space.get("parkingSpace", {}) if parking_space else {}
            )
            address_info = parking_space.get("address", {}) if parking_space else {}

            parking_space_option = self.env["maintenance.parking.space.option"].create(
                {
                    "user_id": self.env.user.id,
                    "name": parking_space_info.get("name", "Namn saknas"),
                    "code": parking_space_info.get("code"),
                    "type_name": parking_space_info.get("parkingSpaceType", {}).get(
                        "name"
                    ),
                    "type_code": parking_space_info.get("parkingSpaceType", {}).get(
                        "code"
                    ),
                    "number": parking_space_info.get("parkingNumber"),
                    "property_code": parking_space.get("propertyCode"),
                    "property_name": parking_space.get("propertyName"),
                    "address": address_info.get("streetAddress", ""),
                    "postal_code": address_info.get("postalCode"),
                    "city": address_info.get("city"),
                }
            )

            # Only create lease and tenant options if lease data exists
            if lease:
                self._create_lease_option(
                    lease, parking_space_option_id=parking_space_option.id
                )

                self._create_tenant_options(lease["tenants"])
            else:
                # Clear existing lease and tenant options when no lease data is available
                self.env["maintenance.lease.option"].search(
                    [("user_id", "=", self.env.user.id)]
                ).unlink()
                self.env["maintenance.tenant.option"].search(
                    [("user_id", "=", self.env.user.id)]
                ).unlink()

    def _set_form_selections(self):
        """Set the form field selections after creating options."""
        parking_space_records = self.env["maintenance.parking.space.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if parking_space_records:
            self.record.parking_space_option_id = parking_space_records[0].id

        lease_records = self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if lease_records:
            self.record.lease_option_id = lease_records[0].id

        tenant_records = self.env["maintenance.tenant.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if tenant_records:
            self.record.tenant_option_id = tenant_records[0].id
