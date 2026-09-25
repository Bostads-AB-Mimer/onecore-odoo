"""Helper functions for maintenance requests."""

import logging
import os

_logger = logging.getLogger(__name__)

# OneCore's lease status strings, mapped to the numeric codes used throughout
# this addon (LEASE_STATUS_LABELS in constants.py).
LEASE_STATUS_MAP = {"Current": 0, "Upcoming": 1, "AboutToEnd": 2, "Ended": 3}
UNKNOWN_LEASE_STATUS = 4


def normalize_lease_status(raw_status):
    """Normalize a OneCore lease status to a LEASE_STATUS_LABELS key.

    Accepts either OneCore's string status ("Current", "Upcoming", ...) or an
    already-numeric LEASE_STATUS_LABELS code, so callers that re-fetch a lease
    and callers that already hold a normalized value can share this function.
    """
    if raw_status in LEASE_STATUS_MAP:
        return LEASE_STATUS_MAP[raw_status]
    if raw_status in LEASE_STATUS_MAP.values():
        return raw_status
    _logger.warning("Unexpected lease status value: %s", raw_status)
    return UNKNOWN_LEASE_STATUS


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
