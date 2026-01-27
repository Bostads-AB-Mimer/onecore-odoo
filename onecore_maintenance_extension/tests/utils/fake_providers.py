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

    def facility_name(self):
        """Generate facility name."""
        return f"Lokal {self.random_int(1, 999)}"

    def facility_code(self):
        """Generate facility code."""
        return self.bothify(text="F###")

    def facility_type_name(self):
        """Generate facility type name."""
        return self.random_element([
            "Butik",
            "Kontor",
            "Restaurang",
            "Lager",
            "Verkstad",
            "Studio"
        ])

    def facility_type_code(self):
        """Generate facility type code."""
        return self.random_element([
            "BTK",
            "KON",
            "RST",
            "LGR",
            "VRK",
            "STD"
        ])

    def facility_rental_type(self):
        """Generate facility rental type."""
        return self.random_element([
            "Kommersiell hyra",
            "Industrilokaler",
            "Kontorslokal",
            "Butikslokaler"
        ])

    def facility_area(self):
        """Generate facility area."""
        return f"{self.random_int(20, 500)} m²"


class ComponentProvider(BaseProvider):
    """Custom Faker provider for component-related mock data."""

    model_names = [
        "Electrolux EW6F5248G4",
        "Bosch SMV46CX01E",
        "Siemens WM14T46SNL",
        "Miele G 5210 SCi",
        "Samsung WW90T534DAW",
        "LG F4WV710P1E",
        "Whirlpool TDLR 7220SS",
        "AEG L6FBG841CA",
    ]

    manufacturers = [
        "Electrolux",
        "Bosch",
        "Siemens",
        "Miele",
        "Samsung",
        "LG",
        "Whirlpool",
        "AEG",
    ]

    category_names = [
        "Kök",
        "Badrum",
        "Tvättstuga",
        "Vardagsrum",
        "Sovrum",
        "Hall",
    ]

    type_names = [
        "Vitvaror",
        "Sanitet",
        "Belysning",
        "Golv",
        "Innerdörrar",
        "Garderober",
    ]

    subtype_names = [
        "Tvättmaskin",
        "Diskmaskin",
        "Kyl/Frys",
        "Spis",
        "Toalett",
        "Handfat",
        "Duschblandare",
        "Badkar",
    ]

    conditions = ["NEW", "GOOD", "FAIR", "POOR", "DAMAGED"]

    ncs_codes = [
        "S 1000-N",
        "S 0500-N",
        "S 2000-N",
        "S 1500-Y20R",
        "S 0300-N",
    ]

    def component_model_name(self):
        """Generate component model name."""
        return self.random_element(self.model_names)

    def component_manufacturer(self):
        """Generate component manufacturer."""
        return self.random_element(self.manufacturers)

    def component_serial_number(self):
        """Generate component serial number."""
        return self.bothify(text="SN#####")

    def component_category_name(self):
        """Generate component category name."""
        return self.random_element(self.category_names)

    def component_type_name(self):
        """Generate component type name."""
        return self.random_element(self.type_names)

    def component_subtype_name(self):
        """Generate component subtype name."""
        return self.random_element(self.subtype_names)

    def component_category_id(self):
        """Generate component category ID."""
        return f"cat-{self.random_int(100, 999)}"

    def component_type_id(self):
        """Generate component type ID."""
        return f"type-{self.random_int(100, 999)}"

    def component_subtype_id(self):
        """Generate component subtype ID."""
        return f"sub-{self.random_int(100, 999)}"

    def component_instance_id(self):
        """Generate component instance ID."""
        return f"comp-{self.random_int(100, 999)}"

    def component_installation_id(self):
        """Generate component installation ID."""
        return f"inst-{self.random_int(100, 999)}"

    def component_room_id(self):
        """Generate room ID."""
        return f"room-{self.random_int(100, 999)}"

    def component_confidence(self):
        """Generate AI confidence score."""
        return round(self.random_int(70, 99) / 100, 2)

    def component_price(self):
        """Generate component price."""
        return self.random_int(1000, 20000)

    def component_install_price(self):
        """Generate component installation price."""
        return self.random_int(200, 2000)

    def component_depreciation_price(self):
        """Generate depreciation price."""
        return self.random_int(50, 500)

    def component_warranty_months(self):
        """Generate warranty period in months."""
        return self.random_element([12, 24, 36, 48, 60])

    def component_lifespan_months(self):
        """Generate lifespan in months."""
        return self.random_element([60, 120, 180, 240])

    def component_replacement_interval(self):
        """Generate replacement interval in months."""
        return self.random_element([36, 60, 120, 180])

    def component_condition(self):
        """Generate component condition."""
        return self.random_element(self.conditions)

    def component_dimensions(self):
        """Generate component dimensions."""
        w = self.random_int(30, 90)
        d = self.random_int(30, 70)
        h = self.random_int(50, 100)
        return f"{w}x{d}x{h} cm"

    def component_ncs_code(self):
        """Generate NCS color code."""
        return self.random_element(self.ncs_codes)

    def component_specifications(self):
        """Generate technical specifications."""
        return self.random_element([
            "Energy class A++",
            "Energy class A+++",
            "1400 rpm",
            "Built-in",
            "Freestanding",
        ])

    def ai_analysis_response(self, **overrides):
        """Generate a complete AI analysis response content dict."""
        data = {
            'model': self.component_model_name(),
            'manufacturer': self.component_manufacturer(),
            'serialNumber': self.component_serial_number(),
            'componentCategory': self.component_category_name(),
            'componentType': self.component_type_name(),
            'componentSubtype': self.component_subtype_name(),
            'confidence': self.component_confidence(),
        }
        data.update(overrides)
        return data

    def onecore_model_response(self, **overrides):
        """Generate a complete OneCore model response dict with hierarchy."""
        cat_id = overrides.pop('category_id', self.component_category_id())
        cat_name = overrides.pop('category_name', self.component_category_name())
        type_id = overrides.pop('type_id', self.component_type_id())
        type_name = overrides.pop('type_name', self.component_type_name())
        sub_id = overrides.pop('subtype_id', self.component_subtype_id())
        sub_name = overrides.pop('subtype_name', self.component_subtype_name())

        data = {
            'modelName': self.component_model_name(),
            'manufacturer': self.component_manufacturer(),
            'currentPrice': self.component_price(),
            'currentInstallPrice': self.component_install_price(),
            'warrantyMonths': self.component_warranty_months(),
            'subtype': {
                'id': sub_id,
                'subTypeName': sub_name,
                'componentType': {
                    'id': type_id,
                    'typeName': type_name,
                    'category': {
                        'id': cat_id,
                        'categoryName': cat_name,
                    }
                }
            }
        }
        data.update(overrides)
        return data

    def component_room_name(self):
        """Generate component room name."""
        return self.random_element(["Kök", "Badrum", "Vardagsrum", "Sovrum", "Hall"])

    def component_model_id(self):
        """Generate component model ID."""
        return f"model-{self.random_int(100, 999)}"

    def component_line_data(self, **overrides):
        """Generate a complete component line data dict."""
        data = {
            'typ': self.component_type_name(),
            'subtype': self.component_subtype_name(),
            'category': self.component_category_name(),
            'model': self.component_model_name(),
            'manufacturer': self.component_manufacturer(),
            'serial_number': self.component_serial_number(),
            'warranty_months': self.component_warranty_months(),
            'specifications': self.component_specifications(),
            'ncs_code': self.component_ncs_code(),
            'additional_information': '',
            'condition': self.component_condition(),
            'installation_date': '2024-06-15',
            'room_name': self.component_room_name(),
            'room_id': self.component_room_id(),
            'onecore_component_id': self.component_instance_id(),
            'model_id': self.component_model_id(),
            'installation_id': self.component_installation_id(),
            'price_at_purchase': self.component_price(),
            'depreciation_price_at_purchase': self.component_depreciation_price(),
            'economic_lifespan': self.component_lifespan_months(),
            'technical_lifespan': self.component_lifespan_months(),
            'replacement_interval': self.component_replacement_interval(),
            'image_urls_json': '[]',
        }
        data.update(overrides)
        return data

    def component_form_data(self, **overrides):
        """Generate form data dict for component creation."""
        data = {
            'model': self.component_model_name(),
            'subtype_id': self.component_subtype_id(),
            'serial_number': self.component_serial_number(),
            'warranty_months': self.component_warranty_months(),
            'current_price': self.component_price(),
            'current_install_price': self.component_install_price(),
            'depreciation_price': self.component_depreciation_price(),
            'economic_lifespan': self.component_lifespan_months(),
            'manufacturer': self.component_manufacturer(),
            'condition': self.component_condition(),
            'specifications': self.component_specifications(),
            'dimensions': self.component_dimensions(),
            'additional_information': '',
            'ncs_code': self.component_ncs_code(),
        }
        data.update(overrides)
        return data
