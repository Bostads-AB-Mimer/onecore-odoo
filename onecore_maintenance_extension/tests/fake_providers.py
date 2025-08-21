from faker.providers import BaseProvider


class MaintenanceProvider(BaseProvider):
    """Custom Faker provider for maintenance-related mock data."""

    # Static data lists
    building_names = [
        "Roslagstull 12",
        "Vasastan 45",
        "Södermalm 8",
        "Östermalm 23",
        "Norrmalm 15",
        "Gamla Stan 7",
        "Kungsholmen 31",
        "Söder Mälarstrand 19",
    ]

    building_types = [
        "Flerfamiljshus",
        "Kontorsbyggnad",
        "Kommersiell fastighet",
        "Hyreshus",
        "Bostadsrättsförening",
        "Industribyggnad",
    ]

    lease_types = [
        "Bostadshyra",
        "Kommersiell hyra",
        "Garage",
        "Förråd",
        "Kontor",
        "Butik",
        "Restaurang",
        "Lager",
    ]

    maintenance_categories = [
        "VVS",
        "Elektricitet",
        "Måleri",
        "Låssmide",
        "Städning",
        "Fasadarbete",
        "Glas & Fönster",
        "Golv",
        "Värme",
        "Ventilation",
    ]

    property_designations = [
        "STOCKHOLM VASASTAN 1:12",
        "STOCKHOLM SÖDERMALM 2:15",
        "STOCKHOLM ÖSTERMALM 3:8",
        "STOCKHOLM NORRMALM 4:23",
        "STOCKHOLM GAMLA STAN 5:7",
        "STOCKHOLM KUNGSHOLMEN 6:19",
    ]

    space_captions = [
        "Byggnad",
        "Fastighet", 
        "Lägenhet",
        "Tvättstuga",
        "Uppgång",
        "Miljöbod",
        "Lekplats",
        "Lokal",
        "Bilplats",
        "Vind",
        "Källare",
        "Cykelförråd",
        "Övrigt",
        "Gården/Utomhus",
    ]

    team_names = [
        "VVS-team Stockholm",
        "El-team Söder",
        "Måleri-team Väst",
        "Låssmide-team Central",
        "Städ-team Nord",
        "Fasad-team Öst",
    ]

    tenant_contact_types = [
        "Hyresgäst",
        "Bostadsrättsinnehavare",
        "Kommersiell hyresgäst",
        "Företagskund",
        "Föreningsrepresentant",
    ]

    maintenance_unit_captions = [
        "Huvudkök",
        "Gästbadrum",
        "Stora vardagsrummet",
        "Sovrum 1",
        "Entréhall",
        "Klädkammare",
        "Balkong söder",
        "Gemensam tvätt",
    ]

    maintenance_unit_types = [
        "Kök",
        "Badrum",
        "Vardagsrum",
        "Sovrum",
        "Hall",
        "Förråd",
        "Balkong",
        "Trapphus",
        "Källare",
        "Vind",
        "Garage",
    ]

    def building_code(self):
        """Generate building code."""
        return self.bothify(text="B###")

    def building_id(self):
        """Generate building ID."""
        return f"building_{self.random_int(1000, 9999)}"

    def building_name(self):
        """Generate Swedish building name."""
        return self.random_element(self.building_names)

    def building_type(self):
        """Generate Swedish building type."""
        return self.random_element(self.building_types)

    def lease_number(self):
        """Generate lease number."""
        return f"{self.random_int(2020, 2024)}-{self.random_int(1000, 9999)}"

    def lease_type(self):
        """Generate Swedish lease type."""
        return self.random_element(self.lease_types)

    def lease_id(self):
        """Generate lease ID."""
        return f"lease_{self.random_int(1000, 9999)}"

    def maintenance_category(self):
        """Generate Swedish maintenance category."""
        return self.random_element(self.maintenance_categories)

    def maintenance_request_name(self):
        """Generate Swedish maintenance request name."""
        category = self.maintenance_category().lower()
        issue = self.random_element(
            [
                "läckage",
                "defekt",
                "trasig",
                "byte av",
                "reparation",
                "underhåll",
                "renovering",
                "installation",
            ]
        )
        location = self.maintenance_unit_type().lower()
        return f"{category.title()}: {issue} i {location}"

    def property_code(self):
        """Generate property code."""
        return self.bothify(text="P###")

    def property_designation(self):
        """Generate Swedish property designation."""
        return self.random_element(self.property_designations)

    def space_caption(self):
        """Generate Swedish space caption for maintenance requests."""
        return self.random_element(self.space_captions)

    def team_name(self):
        """Generate Swedish maintenance team name."""
        return self.random_element(self.team_names)

    def tenant_contact_code(self):
        """Generate tenant contact code."""
        return self.bothify(text="T######")

    def tenant_contact_key(self):
        """Generate tenant contact key."""
        return self.lexify(
            text="????????", letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )

    def contact_code(self):
        """Alias for tenant_contact_code."""
        return self.tenant_contact_code()

    def contact_key(self):
        """Alias for tenant_contact_key."""
        return self.tenant_contact_key()

    def tenant_contact_type(self):
        """Generate Swedish tenant contact type."""
        return self.random_element(self.tenant_contact_types)

    def maintenance_unit_caption(self):
        """Generate Swedish unit caption."""
        return self.random_element(self.maintenance_unit_captions)

    def maintenance_unit_code(self):
        """Generate unit code."""
        return self.bothify(text="U###")

    def maintenance_unit_type(self):
        """Generate Swedish unit type."""
        return self.random_element(self.maintenance_unit_types)

    def category_name(self):
        """Generate category name."""
        return self.maintenance_category()

    def lease_model_name(self):
        """Generate lease name with prefix."""
        return f"Hyresavtal {self.lease_number()}"

    def rental_property_name(self):
        """Generate rental property name with prefix."""
        return f"Hyresfastighet {self.building_name()}"

    def rental_property_code(self):
        """Generate rental property code."""
        return self.bothify(text="RP###")

    def tenant_full_name(self):
        """Generate full tenant name."""
        return f"{self.generator.first_name()} {self.generator.last_name()}"

    def maintenance_unit_full_name(self):
        """Generate full unit name with type and caption."""
        return f"{self.maintenance_unit_type()} - {self.maintenance_unit_caption()}"

    def parking_space_name(self):
        """Generate parking space name."""
        return f"Bilplats {self.random_int(1, 999)}"

    def parking_space_code(self):
        """Generate parking space code."""
        return self.bothify(text="PS###")
