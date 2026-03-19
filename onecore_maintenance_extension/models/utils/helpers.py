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


def select_active_lease(lease_records):
    """Select lease by priority: Current (0) > AboutToEnd (2) > Upcoming (1) > Ended (3) > Okänd (4) > highest lease_number."""
    for priority_status in [0, 2, 1, 3, 4]:
        matches = [r for r in lease_records if r.lease_status == priority_status]
        if matches:
            return max(matches, key=lambda r: r.lease_number or "")
    return max(lease_records, key=lambda r: r.lease_number or "")
