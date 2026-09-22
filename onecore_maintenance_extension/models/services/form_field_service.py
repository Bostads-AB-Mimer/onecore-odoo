"""Form field service for maintenance requests."""

from ..utils.helpers import select_active_lease


class FormFieldService:
    """Service for handling form field assignments and onchange logic."""

    def __init__(self, env):
        self.env = env

    def update_property_fields(self, record):
        """Update property-related fields."""
        if not record.property_option_id:
            return

        record.property_id = record.property_option_id.id
        record.property_designation = record.property_option_id.designation
        record.property_code = record.property_option_id.code

    def update_building_fields(self, record):
        """Update building-related fields."""
        if not record.building_option_id:
            return

        record.building_id = record.building_option_id.id
        record.building_name = record.building_option_id.name
        record.building_code = record.building_option_id.code
        record.building_type_name = record.building_option_id.building_type_name
        record.building_construction_year = record.building_option_id.construction_year
        record.building_renovation_year = record.building_option_id.renovation_year
        record.building_property_code = record.building_option_id.property_code
        record.building_property_name = record.building_option_id.property_name

    def update_staircase_fields(self, record):
        """Update staircase-related fields."""
        if not record.staircase_option_id:
            return

        record.staircase_id = record.staircase_option_id.id
        record.staircase_name = record.staircase_option_id.name
        record.staircase_code = record.staircase_option_id.code
        record.staircase_floor_plan = record.staircase_option_id.floor_plan
        record.staircase_accessible_by_elevator = (
            record.staircase_option_id.accessible_by_elevator
        )

    def update_rental_property_fields(self, record):
        """Update rental property-related fields."""
        # Before the early return: clearing the object must clear its unit too.
        self.sync_maintenance_unit_with_rental_property(record)
        if not record.rental_property_option_id:
            return

        record.rental_property_id = record.rental_property_option_id.name
        record.address = record.rental_property_option_id.address
        record.property_type = record.rental_property_option_id.property_type
        record.code = record.rental_property_option_id.code
        record.type = record.rental_property_option_id.type
        record.area = record.rental_property_option_id.area
        record.entrance = record.rental_property_option_id.entrance
        record.floor = record.rental_property_option_id.floor
        record.has_elevator = record.rental_property_option_id.has_elevator
        record.estate_code = record.rental_property_option_id.estate_code
        record.estate = record.rental_property_option_id.estate
        record.building_code = record.rental_property_option_id.building_code
        record.building = record.rental_property_option_id.building

        # Update related lease only if current lease doesn't belong to this rental property
        if not record.lease_option_id or record.lease_option_id.rental_property_option_id != record.rental_property_option_id:
            lease_records = record.env["maintenance.lease.option"].search(
                [("rental_property_option_id", "=", record.rental_property_option_id.id)]
            )
            if lease_records:
                record.lease_option_id = select_active_lease(lease_records).id

    def sync_maintenance_unit_with_rental_property(self, record):
        """Keep the unit on the selected object.

        A tenant with two contracts who switches object in the form must not
        keep the first object's laundry room. A manual pick on the SAME object
        is kept.
        """
        current_unit = record.maintenance_unit_option_id.exists()
        if (
            not current_unit
            or current_unit.rental_property_option_id != record.rental_property_option_id
        ):
            self.select_serving_maintenance_unit(record)

    def select_serving_maintenance_unit(self, record):
        """Preselect the unit that serves ``record.rental_property_option_id``.

        Xpand links each apartment to the laundry room it is assigned to
        (``serves_rental_object`` on the option). When there is no such link
        nothing is preselected: the user picks from the property's units
        rather than getting the property's first one (MIM-1921).
        """
        serving = self.env["maintenance.maintenance.unit.option"].search(
            [
                ("user_id", "=", self.env.user.id),
                ("rental_property_option_id", "=", record.rental_property_option_id.id),
                ("serves_rental_object", "=", True),
            ],
            order="id",
            limit=1,
        )
        record.maintenance_unit_option_id = serving.id if serving else False
        self.update_maintenance_unit_fields(record)

    def update_maintenance_unit_fields(self, record):
        """Update maintenance unit-related fields.

        Clears them when no option is selected, so a search that preselects
        nothing does not leave the previous search's unit on the form.
        """
        option = record.maintenance_unit_option_id
        # The maintenance.maintenance.unit snapshot is only created on save
        # (_save_maintenance_unit); until then the copied fields carry the
        # values shown on the form.
        record.maintenance_unit_id = False
        record.maintenance_unit_type = option.type if option else False
        record.maintenance_unit_code = option.code if option else False
        record.maintenance_unit_caption = option.caption if option else False

    def _copy_lease_fields(self, record):
        """Copy lease data fields from lease_option_id to the record."""
        record.lease_id = record.lease_option_id.name
        record.lease_type = record.lease_option_id.lease_type
        record.contract_date = record.lease_option_id.contract_date
        record.lease_start_date = record.lease_option_id.lease_start_date
        record.lease_end_date = record.lease_option_id.lease_end_date

    def _copy_tenant_fields(self, record):
        """Copy tenant data fields from tenant_option_id to the record."""
        # `name` is the bare person name; the lease-status label lives only in
        # the option's display_name, so it never leaks into the record or SMS.
        record.tenant_id = record.tenant_option_id.name
        record.tenant_name = record.tenant_option_id.name
        record.contact_code = record.tenant_option_id.contact_code
        record.national_registration_number = (
            record.tenant_option_id.national_registration_number
        )
        record.phone_number = record.tenant_option_id.phone_number
        record.email_address = record.tenant_option_id.email_address
        record.is_tenant = record.tenant_option_id.is_tenant
        record.special_attention = record.tenant_option_id.special_attention

    def update_lease_fields(self, record):
        """Update lease-related fields and sync tenant and associated object."""
        if not record.lease_option_id:
            return

        self._copy_lease_fields(record)

        lease_tenants = record.env["maintenance.tenant.option"].search(
            [("lease_option_id", "=", record.lease_option_id.id),
             ("user_id", "=", record.env.user.id)]
        )
        if lease_tenants and record.tenant_option_id not in lease_tenants:
            record.tenant_option_id = lease_tenants[0].id
        if record.tenant_option_id:
            self._copy_tenant_fields(record)

        # Sync the associated object to match the selected lease
        lease = record.lease_option_id
        if lease.parking_space_option_id and lease.parking_space_option_id != record.parking_space_option_id:
            record.parking_space_option_id = lease.parking_space_option_id.id
        if lease.rental_property_option_id and lease.rental_property_option_id != record.rental_property_option_id:
            record.rental_property_option_id = lease.rental_property_option_id.id
            # The object's onchange has already run in this cascade, so the
            # unit must follow the object from here.
            self.sync_maintenance_unit_with_rental_property(record)
        if lease.facility_option_id and lease.facility_option_id != record.facility_option_id:
            record.facility_option_id = lease.facility_option_id.id

    def update_tenant_fields(self, record):
        """Update tenant-related fields and sync lease."""
        if not record.tenant_option_id:
            return

        self._copy_tenant_fields(record)

        tenant_lease = record.tenant_option_id.lease_option_id
        if tenant_lease and tenant_lease != record.lease_option_id:
            record.lease_option_id = tenant_lease.id
            self._copy_lease_fields(record)

    def update_parking_space_fields(self, record):
        """Update parking space-related fields."""
        if not record.parking_space_option_id:
            return

        record.parking_space_id = record.parking_space_option_id.name
        record.parking_space_name = record.parking_space_option_id.name
        record.parking_space_code = record.parking_space_option_id.code
        record.parking_space_type_name = record.parking_space_option_id.type_name
        record.parking_space_type_code = record.parking_space_option_id.type_code
        record.parking_space_number = record.parking_space_option_id.number
        record.parking_space_property_code = (
            record.parking_space_option_id.property_code
        )
        record.parking_space_property_name = (
            record.parking_space_option_id.property_name
        )
        record.parking_space_address = record.parking_space_option_id.address
        record.parking_space_postal_code = record.parking_space_option_id.postal_code
        record.parking_space_city = record.parking_space_option_id.city

        # Update related lease only if current lease doesn't belong to this parking space
        if not record.lease_option_id or record.lease_option_id.parking_space_option_id != record.parking_space_option_id:
            lease_records = record.env["maintenance.lease.option"].search(
                [("parking_space_option_id", "=", record.parking_space_option_id.id)]
            )
            if lease_records:
                record.lease_option_id = select_active_lease(lease_records).id

    def update_facility_fields(self, record):
        """Update facility-related fields."""
        if not record.facility_option_id:
            return

        record.facility_id = record.facility_option_id.name
        record.facility_code = record.facility_option_id.code
        record.facility_type_name = record.facility_option_id.type_name
        record.facility_type_code = record.facility_option_id.type_code
        record.facility_rental_type = record.facility_option_id.rental_type
        record.facility_area = record.facility_option_id.area
        record.facility_building_code = record.facility_option_id.building_code
        record.facility_building_name = record.facility_option_id.building_name
        record.facility_property_code = record.facility_option_id.property_code
        record.facility_property_name = record.facility_option_id.property_name

        # Update related lease only if current lease doesn't belong to this facility
        if not record.lease_option_id or record.lease_option_id.facility_option_id != record.facility_option_id:
            lease_records = record.env["maintenance.lease.option"].search(
                [("facility_option_id", "=", record.facility_option_id.id)]
            )
            if lease_records:
                record.lease_option_id = select_active_lease(lease_records).id
