"""Helper functions for maintenance requests."""

import logging
import os

from markupsafe import Markup

from ....onecore_api.core_api import ONECORE_LEASE_STATUSES

_logger = logging.getLogger(__name__)

# OneCore's lease status names, mapped to the numeric codes used throughout
# this addon (LEASE_STATUS_LABELS in constants.py). The codes are this addon's
# own: 4 is "Okänd status", so OneCore's 4-6 map to 5-7.
LEASE_STATUS_MAP = {
    "Current": 0,
    "Upcoming": 1,
    "AboutToEnd": 2,
    "Ended": 3,
    "PreliminaryTerminated": 5,
    "PendingSignature": 6,
    "NotSent": 7,
}
UNKNOWN_LEASE_STATUS = 4

# The order a lease is preselected in when an object or customer has several.
LEASE_STATUS_PRIORITY = [
    LEASE_STATUS_MAP[name]
    for name in (
        "Current",
        "AboutToEnd",
        "PreliminaryTerminated",
        "Upcoming",
        "PendingSignature",
        "NotSent",
        "Ended",
    )
] + [UNKNOWN_LEASE_STATUS]

# Leases nobody has signed yet: the person on them isn't a tenant yet.
UNSIGNED_LEASE_STATUSES = (
    LEASE_STATUS_MAP["PendingSignature"],
    LEASE_STATUS_MAP["NotSent"],
)


def normalize_lease_status(raw_status):
    """Normalize a OneCore lease status to a LEASE_STATUS_LABELS key.

    Accepts OneCore's status either by name ("Current", "PendingSignature", ...)
    or by its LeaseStatus number, which is translated through the name. The
    input is always OneCore's value, never one of this addon's codes.
    """
    if isinstance(raw_status, int) and not isinstance(raw_status, bool):
        if 0 <= raw_status < len(ONECORE_LEASE_STATUSES):
            raw_status = ONECORE_LEASE_STATUSES[raw_status]
    if raw_status in LEASE_STATUS_MAP:
        return LEASE_STATUS_MAP[raw_status]
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


def _select_by_lease_priority(leases, status_of, number_of):
    for priority_status in LEASE_STATUS_PRIORITY:
        matches = [lease for lease in leases if status_of(lease) == priority_status]
        if matches:
            return max(matches, key=number_of)
    return max(leases, key=number_of)


def select_active_lease(lease_records):
    """Select lease by priority: Current (0) > AboutToEnd (2) >
    PreliminaryTerminated (5) > Upcoming (1) > PendingSignature (6) >
    NotSent (7) > Ended (3) > Okänd (4) > highest lease_number."""
    return _select_by_lease_priority(
        lease_records,
        lambda record: record.lease_status,
        lambda record: record.lease_number or "",
    )


def select_active_lease_data(leases):
    """select_active_lease for lease dicts in the shape OneCore returns them."""
    return _select_by_lease_priority(
        leases,
        lambda lease: normalize_lease_status(lease.get("status")),
        lambda lease: lease.get("leaseNumber") or "",
    )


def close_request_reason_html(reason):
    """Free text for a close-request message body, or None when blank (MIM-2036).

    Escaped, then line breaks as <br>: Mina sidor renders message bodies with
    v-html, and the text is a tenant's or a handläggare's own words, so it must
    never reach the body as markup. Markup.join escapes every piece it joins.
    Whitespace-only counts as no reason at all.
    """
    text = str(reason or "").strip()
    if not text:
        return None
    return Markup("<br>").join(text.splitlines())
