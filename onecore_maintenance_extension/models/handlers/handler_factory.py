from .rental_property_handler import RentalPropertyHandler
from .parking_space_handler import ParkingSpaceHandler
from .property_handler import PropertyHandler
from .building_handler import BuildingHandler
from .facility_handler import FacilityHandler


class HandlerFactory:
    """Factory class to get appropriate handler based on search criteria.

    This factory uses a matrix-based approach to map (search_type, space_caption)
    combinations to the appropriate handler.
    """

    HANDLER_MATRIX = {
        # ============================================================================
        # DESSA RETURNERAR ALLTID BARA EN FASTIGHET
        # ============================================================================
        ("propertyName", "Fastighet"): PropertyHandler,
        ("propertyName", "Byggnad"): PropertyHandler,
        ("propertyName", "Övrigt"): PropertyHandler,
        ("propertyName", "Tvättstuga"): PropertyHandler,
        ("propertyName", "Miljöbod"): PropertyHandler,
        ("propertyName", "Lekplats"): PropertyHandler,
        # ============================================================================
        # DESSA RETURNERAR ALLTID BARA EN BYGGNAD
        # ============================================================================
        ("buildingCode", "Byggnad"): BuildingHandler,
        ("buildingCode", "Uppgång"): BuildingHandler,
        ("buildingCode", "Vind"): BuildingHandler,
        ("buildingCode", "Källare"): BuildingHandler,
        ("buildingCode", "Cykelförråd"): BuildingHandler,
        ("buildingCode", "Gården/Utomhus"): BuildingHandler,
        ("buildingCode", "Övrigt"): BuildingHandler,
        ("buildingCode", "Tvättstuga"): BuildingHandler,
        ("buildingCode", "Miljöbod"): BuildingHandler,
        ("buildingCode", "Lekplats"): BuildingHandler,
        # Tenant/lease-based searches
        # ============================================================================
        # I ALLA DESSA HÄMTAS LEASE FÖRST.
        # Sedan används propertyId för att hämta
        # - fastighet
        # - byggnad (för ärenden om byggnad, vind, källare, cykelförråd, gården/utomhus, lekplats, övrigt),
        # - parkeringsplats
        # - lägenhet (för ärenden om lägenhet, tvättstuga, miljöbod)
        # - lokal (för ärenden om lokal, tvättstuga, miljöbod)
        #
        # Alternativt får vi fastighet och byggnad när vi hämtar lägenhet/lokal/parkeringsplats
        # ============================================================================
        ("pnr", "Fastighet"): PropertyHandler,
        ("pnr", "Byggnad"): BuildingHandler,
        ("pnr", "Uppgång"): BuildingHandler,
        ("pnr", "Vind"): BuildingHandler,
        ("pnr", "Källare"): BuildingHandler,
        ("pnr", "Cykelförråd"): BuildingHandler,
        ("pnr", "Gården/Utomhus"): BuildingHandler,
        ("pnr", "Övrigt"): BuildingHandler,
        ("pnr", "Lägenhet"): RentalPropertyHandler,
        ("pnr", "Tvättstuga"): RentalPropertyHandler,
        ("pnr", "Miljöbod"): RentalPropertyHandler,
        ("pnr", "Lekplats"): RentalPropertyHandler,
        ("pnr", "Lokal"): FacilityHandler,
        ("pnr", "Bilplats"): ParkingSpaceHandler,
        # ============================================================================
        ("contactCode", "Fastighet"): PropertyHandler,
        ("contactCode", "Byggnad"): BuildingHandler,
        ("contactCode", "Uppgång"): BuildingHandler,
        ("contactCode", "Vind"): BuildingHandler,
        ("contactCode", "Källare"): BuildingHandler,
        ("contactCode", "Cykelförråd"): BuildingHandler,
        ("contactCode", "Gården/Utomhus"): BuildingHandler,
        ("contactCode", "Övrigt"): BuildingHandler,
        ("contactCode", "Lägenhet"): RentalPropertyHandler,
        ("contactCode", "Tvättstuga"): RentalPropertyHandler,
        ("contactCode", "Miljöbod"): RentalPropertyHandler,
        ("contactCode", "Lekplats"): RentalPropertyHandler,
        ("contactCode", "Lokal"): FacilityHandler,
        ("contactCode", "Bilplats"): ParkingSpaceHandler,
        # ============================================================================
        ("leaseId", "Fastighet"): PropertyHandler,
        ("leaseId", "Byggnad"): BuildingHandler,
        ("leaseId", "Uppgång"): BuildingHandler,
        ("leaseId", "Vind"): BuildingHandler,
        ("leaseId", "Källare"): BuildingHandler,
        ("leaseId", "Cykelförråd"): BuildingHandler,
        ("leaseId", "Gården/Utomhus"): BuildingHandler,
        ("leaseId", "Övrigt"): BuildingHandler,
        ("leaseId", "Lägenhet"): RentalPropertyHandler,
        ("leaseId", "Tvättstuga"): RentalPropertyHandler,
        ("leaseId", "Miljöbod"): RentalPropertyHandler,
        ("leaseId", "Lekplats"): RentalPropertyHandler,
        ("leaseId", "Lokal"): FacilityHandler,
        ("leaseId", "Bilplats"): ParkingSpaceHandler,
        # ===========================================================================
        ("rentalObjectId", "Fastighet"): PropertyHandler,
        ("rentalObjectId", "Byggnad"): BuildingHandler,
        ("rentalObjectId", "Uppgång"): BuildingHandler,
        ("rentalObjectId", "Vind"): BuildingHandler,
        ("rentalObjectId", "Källare"): BuildingHandler,
        ("rentalObjectId", "Cykelförråd"): BuildingHandler,
        ("rentalObjectId", "Gården/Utomhus"): BuildingHandler,
        ("rentalObjectId", "Övrigt"): BuildingHandler,
        ("rentalObjectId", "Lägenhet"): RentalPropertyHandler,
        ("rentalObjectId", "Tvättstuga"): RentalPropertyHandler,
        ("rentalObjectId", "Miljöbod"): RentalPropertyHandler,
        ("rentalObjectId", "Lekplats"): RentalPropertyHandler,
        ("rentalObjectId", "Lokal"): FacilityHandler,
        ("rentalObjectId", "Bilplats"): ParkingSpaceHandler,
    }

    @staticmethod
    def get_handler(maintenance_request, core_api, search_type, space_caption):
        """Get the appropriate handler based on search type and space caption.

        Uses a matrix-based lookup to determine which handler should process
        the given combination of search_type and space_caption.

        Args:
            maintenance_request: The maintenance request record
            core_api: The OneCore API instance
            search_type: Type of search (pnr, leaseId, etc.)
            space_caption: Type of space (Lägenhet, Byggnad, etc.)

        Returns:
            Appropriate handler instance for the given combination

        Raises:
            ValueError: If the combination is not supported
        """

        # Look up handler class in the matrix
        handler_key = (search_type, space_caption)
        handler_class = HandlerFactory.HANDLER_MATRIX.get(handler_key)

        if handler_class is None:
            # This should not happen if is_combination_supported is checked first
            return None

        return handler_class(maintenance_request, core_api)

    @staticmethod
    def get_supported_combinations():
        """Get all supported (search_type, space_caption) combinations.

        Returns:
            List of tuples containing supported combinations
        """
        return list(HandlerFactory.HANDLER_MATRIX.keys())

    @staticmethod
    def is_combination_supported(search_type, space_caption):
        """Check if a specific combination is supported.

        Args:
            search_type: Type of search
            space_caption: Type of space

        Returns:
            Boolean indicating if the combination is supported
        """
        return (search_type, space_caption) in HandlerFactory.HANDLER_MATRIX
