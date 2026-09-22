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

            # Reuse existing rental property option if one already exists for this property
            property_code = property_data["code"]
            rental_id = item.get("rental_id") or property_data["rentalInformation"].get(
                "rentalId"
            )
            rental_property_option = self._existing_option(
                "maintenance.rental.property.option", rental_id
            )
            is_new_object = not rental_property_option

            if is_new_object:
                rental_property_option = self.env[
                    "maintenance.rental.property.option"
                ].create(
                    {
                        "user_id": self.env.user.id,
                        "name": property_data["rentalInformation"].get("rentalId"),
                        "rental_id": rental_id,
                        "address": property_data["name"],
                        "code": property_code,
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

            # A renewed contract is two lease items on one object: its units
            # were created with the first item, do not list them twice.
            if not is_new_object:
                continue

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
                        "serves_rental_object": bool(
                            maintenance_unit.get("serves_rental_object")
                        ),
                    }
                )

    def _set_form_selections(self, search_type=None, search_value=None):
        """Set the form field selections after creating options."""
        property_records = self.env["maintenance.rental.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if property_records:
            self.record.rental_property_option_id = property_records[0].id

        self._set_lease_and_tenant_selections(search_type, search_value)

        # The active lease decides the object (the lease onchange would switch
        # it anyway); pick the unit for THAT object, not for property_records[0].
        lease_object = self.record.lease_option_id.rental_property_option_id
        if lease_object:
            self.record.rental_property_option_id = lease_object.id

        # The unit Xpand assigns to the selected object, or none — never the
        # property's first unit (MIM-1921: it was always the same laundry room
        # for every tenant on the property). Imported here: the services
        # package imports the handlers (direct_lookup_service).
        from ..services.form_field_service import FormFieldService

        FormFieldService(self.env).select_serving_maintenance_unit(self.record)
