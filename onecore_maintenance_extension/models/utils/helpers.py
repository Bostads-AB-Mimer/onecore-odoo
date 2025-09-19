"""Helper functions for maintenance requests."""

import os


def is_local():
    """Check if running in local development environment."""
    return os.getenv("ENV") == "local"


def get_tenant_name(tenant):
    """Construct the tenant's name based on available information."""
    if tenant.get("firstName") and tenant.get("lastName"):
        return tenant["firstName"] + " " + tenant["lastName"]
    return tenant.get("fullName", "")


def get_main_phone_number(tenant):
    """Extract the main phone number from the tenant's phone numbers."""
    return next(
        (
            item["phoneNumber"]
            for item in tenant.get("phoneNumbers", [])
            if item["isMainNumber"] == 1
        ),
        None,
    )