"""Validation functions for maintenance request search fields."""

validators = {
    "leaseId": lambda id: len(id) >= 8,
    "rentalObjectId": lambda id: len(id) >= 8,
    "contactCode": lambda code: len(code) >= 6,
    "pnr": lambda pnr: len(pnr) == 12 and str(pnr)[:2] in ["19", "20"],
    "buildingCode": lambda code: len(code) >= 6,
    "propertyName": lambda name: len(name) >= 3,
}