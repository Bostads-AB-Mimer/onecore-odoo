from .rental_object_base_handler import RentalObjectBaseHandler


class FacilityHandler(RentalObjectBaseHandler):
    """Handler for facility-related maintenance requests."""

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

            # Only create lease and tenant options if lease data exists
            if lease:
                lease_option = self._create_lease_option(lease, facility_option_id=facility_option.id)
                self._create_tenant_options(lease["tenants"], lease_option_id=lease_option.id)
            else:
                self._clear_lease_and_tenant_options()

    def _set_form_selections(self, search_type=None, search_value=None):
        """Set form selections for facility options."""
        facility_options = self.env["maintenance.facility.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if facility_options:
            self.record.facility_option_id = facility_options[0].id

        self._set_lease_and_tenant_selections(search_type, search_value)
