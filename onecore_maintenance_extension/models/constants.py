"""Constants and configurations for maintenance requests."""

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

# Priority options with time periods
PRIORITY_OPTIONS = [
    ("1", "1 dag"),
    ("5", "5 dagar"),
    ("7", "7 dagar"),
    ("10", "10 dagar"),
    ("14", "2 veckor"),
    ("21", "3 veckor"),
    ("35", "5 veckor"),
    ("56", "8 veckor"),
]

# Creation origin options
CREATION_ORIGINS = [("mimer-nu", "Mimer.nu"), ("internal", "Internt")]

# Form state options
FORM_STATES = [
    ("rental-property", "Bostad"),
    ("property", "Fastighet"),
    ("building", "Byggnad"),
    ("parking-space", "Bilplats"),
    ("maintenance-unit", "Underhållsenhet"),
    ("facility", "Lokal"),
]
