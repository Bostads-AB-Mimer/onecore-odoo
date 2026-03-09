from .rental_object_base_handler import RentalObjectBaseHandler
from ..constants import BUILDING_SPACE_TYPES


class RentalPropertyHandler(RentalObjectBaseHandler):
    """Handler for rental property maintenance requests (apartments, etc.)."""

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

            # Only create lease and tenant options if lease data exists
            if lease:
                lease_option = self._create_lease_option(
                    lease, rental_property_option_id=rental_property_option.id
                )
                self._create_tenant_options(lease["tenants"], lease_option_id=lease_option.id)
            else:
                self._clear_lease_and_tenant_options()

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

    def _set_form_selections(self, search_type=None, search_value=None):
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

        self._set_lease_and_tenant_selections(search_type, search_value)
