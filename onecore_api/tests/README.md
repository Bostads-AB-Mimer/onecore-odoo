# OneCore API Tests

Comprehensive test suite for the `core_api.py` module using pytest.

## Installation

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

## Running Tests

Run all tests:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=. --cov-report=html
```

Run specific test class:

```bash
pytest tests/test_core_api.py::TestFilterLeaseOnLocationType
```

Run specific test:

```bash
pytest tests/test_core_api.py::TestFilterLeaseOnLocationType::test_filters_bilplats_correctly
```

Run tests with verbose output:

```bash
pytest -v
```

Run only unit tests:

```bash
pytest -m unit
```

## Test Coverage

The test suite covers:

- **Filter methods**: `filter_lease_on_location_type`, `filter_maintenance_units_by_location_type`
- **Token management**: Token persistence, refresh logic, authentication
- **HTTP request handling**: Request retry logic, error handling, 401 response handling
- **Data fetching**: All fetch methods with various scenarios and edge cases
- **Error handling**: Exception raising and error message validation
- **Edge cases**: Empty lists, None values, malformed data, missing fields

## Test Structure

Tests are organized by class:

- `TestFilterLeaseOnLocationType`: Filtering logic for different lease types
- `TestFilterMaintenanceUnitsByLocationType`: Maintenance unit filtering
- `TestTokenManagement`: Token persistence and authentication
- `TestRequest`: HTTP request and retry logic
- `TestGetJson`: JSON response parsing
- `TestFetchLeases`: Lease fetching with different identifiers
- `TestFetchBuilding`: Building data with conditional fetching
- `TestFetchProperties`: Property search and aggregation
- `TestFetchFormData`: Complex form data orchestration
- `TestOneCoreException`: Custom exception class

## Coverage Report

After running tests with coverage, open `htmlcov/index.html` in a browser to view the detailed coverage report.
