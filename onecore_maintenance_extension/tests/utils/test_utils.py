"""Utility functions for tests."""
from unittest.mock import patch

from faker import Faker
from .fake_providers import MaintenanceProvider, ComponentProvider


def setup_faker():
    """Setup faker with Swedish locale and maintenance provider."""
    fake = Faker("sv_SE")
    fake.add_provider(MaintenanceProvider)
    fake.add_provider(ComponentProvider)
    return fake


def create_test_user(env, **kwargs):
    """Create a test user with standard groups.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="John Doe")

    Returns:
        res.users record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.name(),
        "login": fake.email(),
        "groups_id": [
            (
                6,
                0,
                [
                    env.ref("base.group_user").id,
                ],
            )
        ],
    }
    defaults.update(kwargs)
    return env["res.users"].create(defaults)


def create_internal_user(env, **kwargs):
    """Create internal user with equipment manager permissions.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., login="user@example.com")

    Returns:
        res.users record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.name(),
        "login": fake.email(),
        "groups_id": [
            (
                6,
                0,
                [
                    env.ref("base.group_user").id,
                    env.ref("maintenance.group_equipment_manager").id,
                ],
            )
        ],
    }
    defaults.update(kwargs)
    return env["res.users"].create(defaults)


def create_external_contractor_user(env, **kwargs):
    """Create external contractor user.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="Jane Smith")

    Returns:
        res.users record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.name(),
        "login": fake.email(),
        "groups_id": [
            (
                6,
                0,
                [
                    env.ref("base.group_user").id,
                    env.ref("onecore_maintenance_extension.group_external_contractor").id,
                ],
            )
        ],
    }
    defaults.update(kwargs)
    return env["res.users"].create(defaults)


def create_maintenance_request(env, **kwargs):
    """Create a maintenance request with minimal required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="Fix broken door")

    Returns:
        maintenance.request record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.maintenance_request_name(),
        "maintenance_request_category_id": env.ref(
            "onecore_maintenance_extension.category_1"
        ).id,
        "space_caption": fake.space_caption(),
    }
    defaults.update(kwargs)
    return env["maintenance.request"].create(defaults)


def create_property_option(env, **kwargs):
    """Create a property option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., code="PROP001")

    Returns:
        maintenance.property.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "code": fake.property_code(),
        "designation": fake.property_designation(),
    }
    defaults.update(kwargs)
    return env["maintenance.property.option"].create(defaults)


def create_building_option(env, **kwargs):
    """Create a building option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="Building A")

    Returns:
        maintenance.building.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.building_name(),
        "code": fake.building_code(),
    }
    defaults.update(kwargs)
    return env["maintenance.building.option"].create(defaults)


def create_rental_property_option(env, **kwargs):
    """Create a rental property option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., property_type="Apartment")

    Returns:
        maintenance.rental.property.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.rental_property_code(),
        "address": fake.building_name(),
        "property_type": fake.building_type(),
    }
    defaults.update(kwargs)
    return env["maintenance.rental.property.option"].create(defaults)


def create_parking_space_option(env, **kwargs):
    """Create a parking space option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., code="PS123")

    Returns:
        maintenance.parking.space.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.parking_space_name(),
        "code": fake.parking_space_code(),
    }
    defaults.update(kwargs)
    return env["maintenance.parking.space.option"].create(defaults)


def create_facility_option(env, **kwargs):
    """Create a facility option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="Storage Room")

    Returns:
        maintenance.facility.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.facility_name(),
        "code": fake.facility_code(),
    }
    defaults.update(kwargs)
    return env["maintenance.facility.option"].create(defaults)


def create_staircase_option(env, **kwargs):
    """Create a staircase option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., code="STAIR01")

    Returns:
        maintenance.staircase.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.building_name(),
        "code": fake.building_code(),
    }
    defaults.update(kwargs)
    return env["maintenance.staircase.option"].create(defaults)


def create_maintenance_unit_option(env, **kwargs):
    """Create a maintenance unit option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., code="UNIT001")

    Returns:
        maintenance.maintenance.unit.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.maintenance_unit_caption(),
        "code": fake.maintenance_unit_code(),
        "caption": fake.maintenance_unit_caption(),
    }
    defaults.update(kwargs)
    return env["maintenance.maintenance.unit.option"].create(defaults)


def create_tenant_option(env, **kwargs):
    """Create a tenant option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., name="John Smith")

    Returns:
        maintenance.tenant.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.tenant_full_name(),
        "contact_code": fake.contact_code(),
        "contact_key": fake.contact_key(),
        "is_tenant": True,
    }
    defaults.update(kwargs)
    return env["maintenance.tenant.option"].create(defaults)


def create_lease_option(env, **kwargs):
    """Create a lease option with required fields.

    Args:
        env: Odoo environment
        **kwargs: Additional fields to override defaults (e.g., lease_number="L12345")

    Returns:
        maintenance.lease.option record
    """
    fake = setup_faker()

    defaults = {
        "user_id": env.user.id,
        "name": fake.lease_id(),
        "lease_number": fake.lease_number(),
        "lease_type": fake.lease_type(),
        "lease_start_date": fake.date(),
        "lease_end_date": fake.date(),
        "contract_date": fake.date(),
        "approval_date": fake.date(),
    }
    defaults.update(kwargs)
    return env["maintenance.lease.option"].create(defaults)


def create_property(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance property with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., code="CUSTOM_CODE")

    Returns:
        maintenance.property record
    """
    fake = setup_faker()

    defaults = {
        "code": fake.property_code(),
        "designation": fake.property_designation(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.property"].create(defaults)


def create_building(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance building with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., name="CUSTOM_NAME")

    Returns:
        maintenance.building record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.building_name(),
        "code": fake.building_code(),
        "building_id": fake.building_id(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.building"].create(defaults)


def create_lease(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance lease with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., lease_number="12345")

    Returns:
        maintenance.lease record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.lease_model_name(),
        "lease_number": fake.lease_number(),
        "lease_type": fake.lease_type(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.lease"].create(defaults)


def create_tenant(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance tenant with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., name="John Doe")

    Returns:
        maintenance.tenant record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.tenant_full_name(),
        "contact_code": fake.tenant_contact_code(),
        "contact_key": fake.tenant_contact_key(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.tenant"].create(defaults)


def create_parking_space(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance parking space with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., code="P123")

    Returns:
        maintenance.parking.space record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.parking_space_name(),
        "code": fake.parking_space_code(),
        "type_name": "Standard",
        "type_code": "STD",
        "number": str(fake.random_int(1, 999)),
        "property_code": fake.property_code(),
        "property_name": fake.building_name(),
        "address": fake.address(),
        "postal_code": fake.postcode(),
        "city": fake.city(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.parking.space"].create(defaults)


def create_facility(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance facility with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., name="Laundry Room")

    Returns:
        maintenance.facility record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.facility_name(),
        "code": fake.facility_code(),
        "type_name": fake.facility_type_name(),
        "type_code": fake.facility_type_code(),
        "rental_type": fake.facility_rental_type(),
        "area": fake.facility_area(),
        "building_code": fake.building_code(),
        "building_name": fake.building_name(),
        "property_code": fake.property_code(),
        "property_name": fake.building_name(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.facility"].create(defaults)


def create_rental_property(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance rental property with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., property_type="Apartment")

    Returns:
        maintenance.rental.property record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.rental_property_name(),
        "property_type": fake.building_type(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.rental.property"].create(defaults)


def create_maintenance_unit(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance unit with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., code="UNIT123")

    Returns:
        maintenance.maintenance.unit record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.maintenance_unit_full_name(),
        "type": fake.maintenance_unit_type(),
        "code": fake.maintenance_unit_code(),
        "caption": fake.maintenance_unit_caption(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.maintenance.unit"].create(defaults)


def create_staircase(env, maintenance_request_id=None, **kwargs):
    """Create a maintenance staircase with required fields.

    Args:
        env: Odoo environment
        maintenance_request_id: ID of the maintenance request to link to
        **kwargs: Additional fields to override defaults (e.g., name="Staircase A")

    Returns:
        maintenance.staircase record
    """
    fake = setup_faker()

    defaults = {
        "name": fake.building_name(),
        "code": fake.building_code(),
        "staircase_id": fake.building_id(),
    }
    if maintenance_request_id:
        defaults["maintenance_request_id"] = maintenance_request_id
    defaults.update(kwargs)
    return env["maintenance.staircase"].create(defaults)


def create_component_wizard(env, maintenance_request_id=None, **kwargs):
    """Create a component wizard with _load_onecore_components patched out.

    The wizard's create() calls _load_onecore_components which hits the API,
    so we must patch it for every wizard creation in tests.

    Args:
        env: Odoo environment
        maintenance_request_id: Optional maintenance request ID to link to
        **kwargs: Additional fields to override defaults

    Returns:
        maintenance.component.wizard record
    """
    defaults = {}
    if maintenance_request_id:
        defaults['maintenance_request_id'] = maintenance_request_id
    defaults.update(kwargs)

    with patch.object(
        type(env['maintenance.component.wizard']),
        '_load_onecore_components',
        return_value=None,
    ):
        return env['maintenance.component.wizard'].create(defaults)


def create_component_line(env, wizard_id, **kwargs):
    """Create a component line attached to a wizard.

    Args:
        env: Odoo environment
        wizard_id: ID of the parent wizard record
        **kwargs: Additional fields to override defaults

    Returns:
        maintenance.component.line record
    """
    fake = setup_faker()

    defaults = {
        'wizard_id': wizard_id,
        'typ': fake.component_type_name(),
        'subtype': fake.component_subtype_name(),
        'category': fake.component_category_name(),
        'model': fake.component_model_name(),
        'manufacturer': fake.component_manufacturer(),
        'serial_number': fake.component_serial_number(),
        'room_name': fake.component_room_name(),
        'room_id': fake.component_room_id(),
        'onecore_component_id': fake.component_instance_id(),
        'model_id': fake.component_model_id(),
        'installation_id': fake.component_installation_id(),
        'condition': fake.component_condition(),
    }
    defaults.update(kwargs)
    return env['maintenance.component.line'].create(defaults)
