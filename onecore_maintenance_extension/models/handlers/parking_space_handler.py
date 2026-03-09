from .rental_object_base_handler import RentalObjectBaseHandler


class ParkingSpaceHandler(RentalObjectBaseHandler):
    """Handler for parking space maintenance requests."""

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
                lease_option = self._create_lease_option(
                    lease, parking_space_option_id=parking_space_option.id
                )
                self._create_tenant_options(lease["tenants"], lease_option_id=lease_option.id)
            else:
                self._clear_lease_and_tenant_options()

    def _set_form_selections(self, search_type=None, search_value=None):
        """Set the form field selections after creating options."""
        parking_space_records = self.env["maintenance.parking.space.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if parking_space_records:
            self.record.parking_space_option_id = parking_space_records[0].id

        self._set_lease_and_tenant_selections(search_type, search_value)
