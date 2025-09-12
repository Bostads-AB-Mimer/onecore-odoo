import logging
from .base_handler import BaseMaintenanceHandler
from ..constants import BUILDING_SPACE_TYPES

_logger = logging.getLogger(__name__)


class RentalPropertyHandler(BaseMaintenanceHandler):
    """Handler for rental property maintenance requests (apartments, etc.)."""

    def handle_search(self, search_type, search_value, space_caption):
        """Handle search for rental property related requests.

        RentalPropertyHandler can handle:
        - lease-based searches (pnr, contactCode, leaseId, rentalObjectId): Find rental properties via tenant/lease data
        """
        if search_type in ["pnr", "contactCode", "leaseId", "rentalObjectId"]:
            work_order_data = self.core_api.fetch_form_data(
                search_type, search_value, space_caption
            )

            if not work_order_data:
                _logger.info("No data found in response.")
                self._raise_no_results_error(search_value)

            self.update_form_options(work_order_data)
            self._set_form_selections()
        else:
            raise ValueError(
                f"RentalPropertyHandler does not support search type: {search_type}"
            )

    def update_form_options(self, work_order_data):
        """Update form options with rental property data."""
        for item in work_order_data:
            property_data = item["rental_property"]
            lease = item["lease"]
            maintenance_units = item.get("maintenance_units", [])

            rental_property_option = self.env[
                "maintenance.rental.property.option"
            ].create(
                {
                    "user_id": self.env.user.id,
                    "name": property_data["rentalInformation"].get("rentalId"),
                    "address": property_data["name"],
                    "code": property_data["code"],
                    "property_type": property_data["type"].get("name"),
                    "area": property_data["areaSize"],
                    "entrance": property_data["entrance"],
                    "has_elevator": (
                        "Ja"
                        if property_data["accessibility"].get("elevator")
                        else "Nej"
                    ),
                    "estate_code": property_data["property"].get("code"),
                    "estate": property_data["property"].get("name"),
                    "building_code": property_data["building"].get("code"),
                    "building": property_data["building"].get("name"),
                }
            )

            self._create_lease_option(
                lease, rental_property_option_id=rental_property_option.id
            )

            self._create_tenant_options(lease["tenants"])
            print(maintenance_units)

            for maintenance_unit in maintenance_units:
                self.env["maintenance.maintenance.unit.option"].create(
                    {
                        "user_id": self.env.user.id,
                        "id": maintenance_unit["id"],
                        "name": maintenance_unit["caption"],
                        "caption": maintenance_unit["caption"],
                        "type": maintenance_unit["type"],
                        "code": maintenance_unit["code"],
                        "rental_property_option_id": rental_property_option.id,
                    }
                )

    def _set_form_selections(self):
        """Set the form field selections after creating options."""
        property_records = self.env["maintenance.rental.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if property_records:
            self.record.rental_property_option_id = property_records[0].id

        maintenance_unit_records = self.env[
            "maintenance.maintenance.unit.option"
        ].search([("user_id", "=", self.env.user.id)])
        if maintenance_unit_records:
            self.record.maintenance_unit_option_id = maintenance_unit_records[0].id

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
