"""Constants and configurations for maintenance requests."""

# Lease status labels
LEASE_STATUS_LABELS = {
    0: "Gällande",
    1: "Kommande",
    2: "Uppsagt",
    3: "Upphört",
    4: "Okänd status",
}

# Space types available for maintenance requests
SPACES = [
    ("Byggnad", "Byggnad"),
    ("Fastighet", "Fastighet"),
    ("Lägenhet", "Lägenhet"),
    ("Tvättstuga", "Tvättstuga"),
    ("Uppgång", "Uppgång"),  # saknas typ i maintenance_unit
    ("Miljöbod", "Miljöbod"),
    ("Lekplats", "Lekplats"),
    ("Lokal", "Lokal"),
    ("Bilplats", "Bilplats"),
    ("Vind", "Vind"),  # saknas typ i maintenance_unit
    ("Källare", "Källare"),  # saknas typ i maintenance_unit
    ("Cykelförråd", "Cykelförråd"),  # saknas typ i maintenance_unit
    ("Övrigt", "Övrigt"),
    ("Gården/Utomhus", "Gården/Utomhus"),
]

SORTED_SPACES = sorted(SPACES)

# Building-related space types
BUILDING_SPACE_TYPES = [
    "Byggnad",
    "Uppgång",
    "Vind",
    "Källare",
    "Cykelförråd",
    "Gården/Utomhus",
    "Övrigt",
]

# Search type options
SEARCH_TYPES = [
    ("leaseId", "Kontraktsnummer"),
    ("rentalObjectId", "Hyresobjekt"),
    ("contactCode", "Kundnummer"),
    ("pnr", "Personnummer (12 siffror)"),
    ("buildingCode", "Byggnadskod"),
    ("propertyName", "Fastighetsnamn"),
]

PRIORITY_CUSTOM = "custom"

# Prioritet presets. The value of every non-custom entry IS the number of days
# to förfallodatum — see models/utils/priority.py. PRIORITY_CUSTOM is the
# escape hatch (MIM-2038): the day count then comes from priority_weeks.
# '7' must stay a valid value: onecore's work-order odoo-adapter writes it
# over XML-RPC when creating besiktning requests.
PRIORITY_PRESETS = [
    ("0", "Akut"),
    ("1", "1 dag"),
    ("5", "5 dagar"),
    ("7", "7 dagar"),
    ("10", "10 dagar"),
    (PRIORITY_CUSTOM, "Antal veckor"),
]

PRIORITY_MAX_WEEKS = 52

# Legacy Selection values MIM-2038 retired, mapped to the weeks that replace
# them. Consumed by migrations/19.0.1.0.12/pre-migration.py.
LEGACY_PRIORITY_WEEKS = {
    "14": 2,
    "21": 3,
    "28": 4,
    "35": 5,
    "42": 6,
    "56": 8,
    "183": 26,
    "365": 52,
}

# Creation origin options. MIMER_NU_ORIGIN is the tenant self-service inflow;
# OrderingDepartmentService keys its Kundcenter rule on it.
MIMER_NU_ORIGIN = "mimer-nu"
CREATION_ORIGINS = [(MIMER_NU_ORIGIN, "Mimer.nu"), ("internal", "Internt")]

# Form state options
FORM_STATES = [
    ("rental-property", "Bostad"),
    ("property", "Fastighet"),
    ("building", "Byggnad"),
    ("parking-space", "Bilplats"),
    ("maintenance-unit", "Underhållsenhet"),
    ("facility", "Lokal"),
]

# Mail message types on the tenant <-> case channel.
# CUSTOMER_MESSAGE_TYPE is written by onecore's work-order service
# (odoo-adapter.addMessageToWorkOrder) when it forwards a Mina-sidor message.
# RECEIPT_TO_TENANT_MESSAGE_TYPE is our reply confirming receipt; the selection
# value itself is declared on mail.message in onecore_mail_extension, which
# cannot import this module. Keep the two strings in sync.
CUSTOMER_MESSAGE_TYPE = "from_tenant"
RECEIPT_TO_TENANT_MESSAGE_TYPE = "receipt_to_tenant"
