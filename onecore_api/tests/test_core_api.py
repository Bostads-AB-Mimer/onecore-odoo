import pytest
from unittest.mock import Mock, MagicMock, patch, call
import requests
from core_api import CoreApi, OneCoreException


@pytest.fixture
def mock_env():
    """Create a mock Odoo environment."""
    env = MagicMock()
    config_params = {
        "onecore_api_token": "existing_token",
        "onecore_username": "test_user",
        "onecore_password": "test_pass",
        "onecore_base_url": "https://api.example.com",
    }

    def get_param(key, default=None):
        return config_params.get(key, default)

    def set_param(key, value):
        config_params[key] = value

    env["ir.config_parameter"].sudo().get_param.side_effect = get_param
    env["ir.config_parameter"].sudo().set_param.side_effect = set_param

    return env


@pytest.fixture
def api(mock_env):
    """Create a CoreApi instance with mocked environment."""
    with patch('core_api.CoreApi._get_auth_token'):
        return CoreApi(mock_env)


class TestFilterLeaseOnLocationType:
    """Tests for filter_lease_on_location_type method."""

    def test_returns_non_list_data_unchanged(self, api):
        """Should return data unchanged if not a list."""
        data = {"type": "Bostadskontrakt"}
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert result == data

    def test_filters_bilplats_correctly(self, api):
        """Should filter P-Platskontrakt for Bilplats location type."""
        data = [
            {"type": "P-Platskontrakt", "id": 1},
            {"type": "Bostadskontrakt", "id": 2},
            {"type": "P-Platskontrakt ", "id": 3},  # with trailing space
            {"type": "Lokalkontrakt", "id": 4},
        ]
        result = api.filter_lease_on_location_type(data, "Bilplats")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_filters_lokal_correctly(self, api):
        """Should filter Lokalkontrakt for Lokal location type."""
        data = [
            {"type": "Lokalkontrakt", "id": 1},
            {"type": "Bostadskontrakt", "id": 2},
            {"type": " Lokalkontrakt ", "id": 3},  # with spaces
            {"type": "P-Platskontrakt", "id": 4},
        ]
        result = api.filter_lease_on_location_type(data, "Lokal")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_filters_bostadskontrakt_by_default(self, api):
        """Should filter Bostadskontrakt for any other location type."""
        data = [
            {"type": "Bostadskontrakt", "id": 1},
            {"type": "P-Platskontrakt", "id": 2},
            {"type": " Bostadskontrakt", "id": 3},  # with leading space
            {"type": "Lokalkontrakt", "id": 4},
        ]
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_falls_back_to_kooperativ_hyresrätt(self, api):
        """Should fall back to Kooperativ hyresrätt when no Bostadskontrakt found."""
        data = [
            {"type": "Kooperativ hyresrätt", "id": 1},
            {"type": "P-Platskontrakt", "id": 2},
            {"type": " Kooperativ hyresrätt", "id": 3},  # with leading space
            {"type": "Lokalkontrakt", "id": 4},
        ]
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_prefers_bostadskontrakt_over_kooperativ(self, api):
        """Should prefer Bostadskontrakt over Kooperativ hyresrätt when both exist."""
        data = [
            {"type": "Bostadskontrakt", "id": 1},
            {"type": "Kooperativ hyresrätt", "id": 2},
            {"type": "P-Platskontrakt", "id": 3},
        ]
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["type"] == "Bostadskontrakt"

    def test_handles_empty_list(self, api):
        """Should return empty list for empty input."""
        result = api.filter_lease_on_location_type([], "Bilplats")
        assert result == []

    def test_filters_out_non_dict_items(self, api):
        """Should filter out non-dict items from list."""
        data = [
            {"type": "Bostadskontrakt", "id": 1},
            "not a dict",
            None,
            {"type": "Bostadskontrakt", "id": 2},
        ]
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_handles_missing_type_field(self, api):
        """Should filter out items without type field."""
        data = [
            {"type": "Bostadskontrakt", "id": 1},
            {"id": 2},  # missing type
            {"type": "", "id": 3},  # empty type
            {"type": "Bostadskontrakt", "id": 4},
        ]
        result = api.filter_lease_on_location_type(data, "Bostad")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 4


class TestFilterMaintenanceUnitsByLocationType:
    """Tests for filter_maintenance_units_by_location_type method."""

    def test_filters_by_type_correctly(self, api):
        """Should filter maintenance units by exact type match."""
        units = [
            {"type": "Tvättstuga", "id": 1},
            {"type": "Miljöbod", "id": 2},
            {"type": "Lekplats", "id": 3},
            {"type": "Tvättstuga", "id": 4},
        ]
        result = list(api.filter_maintenance_units_by_location_type(units, "Tvättstuga"))
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 4

    def test_returns_empty_for_no_match(self, api):
        """Should return empty iterator when no units match."""
        units = [
            {"type": "Tvättstuga", "id": 1},
            {"type": "Miljöbod", "id": 2},
        ]
        result = list(api.filter_maintenance_units_by_location_type(units, "Lekplats"))
        assert result == []


class TestTokenManagement:
    """Tests for token management methods."""

    def test_get_persisted_token(self, api):
        """Should retrieve token from config parameters."""
        token = api._get_persisted_token()
        assert token == "existing_token"

    def test_persist_token(self, api):
        """Should save token to config parameters."""
        api._persist_token("new_token")
        assert api._get_persisted_token() == "new_token"

    @patch('core_api.requests.post')
    def test_get_auth_token_success(self, mock_post, api):
        """Should fetch and persist new token on successful auth."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "fresh_token"}
        mock_post.return_value = mock_response

        token = api._get_auth_token()

        assert token == "fresh_token"
        assert api._get_persisted_token() == "fresh_token"
        mock_post.assert_called_once_with(
            "https://api.example.com/auth/generateToken",
            json={"username": "test_user", "password": "test_pass"}
        )

    @patch('core_api.requests.post')
    def test_get_auth_token_failure(self, mock_post, api):
        """Should raise error on auth failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.HTTPError()
        mock_post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            api._get_auth_token()

    def test_init_fetches_token_if_none_exists(self):
        """Should fetch auth token during init if none persisted."""
        env = MagicMock()
        config_params = {
            "onecore_api_token": None,
            "onecore_username": "test_user",
            "onecore_password": "test_pass",
            "onecore_base_url": "https://api.example.com",
        }

        def get_param(key, default=None):
            return config_params.get(key, default)

        env["ir.config_parameter"].sudo().get_param.side_effect = get_param

        with patch('core_api.CoreApi._get_auth_token') as mock_get_auth:
            api = CoreApi(env)
            mock_get_auth.assert_called_once()

    def test_init_skips_token_fetch_if_exists(self):
        """Should not fetch auth token during init if already persisted."""
        env = MagicMock()
        config_params = {
            "onecore_api_token": "existing_token",
            "onecore_username": "test_user",
            "onecore_password": "test_pass",
            "onecore_base_url": "https://api.example.com",
        }

        def get_param(key, default=None):
            return config_params.get(key, default)

        env["ir.config_parameter"].sudo().get_param.side_effect = get_param

        with patch('core_api.CoreApi._get_auth_token') as mock_get_auth:
            api = CoreApi(env)
            mock_get_auth.assert_not_called()


class TestRequest:
    """Tests for request method with token refresh logic."""

    @patch('core_api.requests.request')
    def test_successful_request(self, mock_request, api):
        """Should make successful request with existing token."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        result = api.request("GET", "/test")

        assert result == mock_response
        mock_request.assert_called_once_with(
            "GET",
            "https://api.example.com/test",
            headers={"Authorization": "Bearer existing_token"}
        )

    @patch('core_api.requests.request')
    def test_refreshes_token_on_401(self, mock_request, api):
        """Should refresh token and retry on 401 response."""
        mock_401_response = Mock()
        mock_401_response.status_code = 401

        mock_200_response = Mock()
        mock_200_response.status_code = 200

        # First call returns 401, second call returns 200
        mock_request.side_effect = [mock_401_response, mock_200_response]

        with patch.object(api, '_get_auth_token', return_value='new_token') as mock_get_auth:
            result = api.request("GET", "/test")

        assert result == mock_200_response
        assert mock_request.call_count == 2

        # Verify _get_auth_token was called to refresh the token
        mock_get_auth.assert_called_once()

    @patch('core_api.requests.request')
    def test_raises_on_double_401(self, mock_request, api):
        """Should raise error if 401 persists after token refresh."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = requests.HTTPError()
        mock_request.return_value = mock_response

        with patch.object(api, '_get_auth_token', return_value='new_token'):
            with pytest.raises(requests.HTTPError):
                api.request("GET", "/test")

    @patch('core_api.requests.request')
    def test_passes_kwargs_to_request(self, mock_request, api):
        """Should pass through additional kwargs to requests.request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        api.request("POST", "/test", json={"key": "value"}, timeout=30)

        mock_request.assert_called_once_with(
            "POST",
            "https://api.example.com/test",
            headers={"Authorization": "Bearer existing_token"},
            json={"key": "value"},
            timeout=30
        )


class TestGetJson:
    """Tests for _get_json method."""

    def test_returns_content_from_response(self, api):
        """Should extract 'content' field from JSON response."""
        mock_response = Mock()
        mock_response.json.return_value = {"content": {"data": "value"}}

        with patch.object(api, 'request', return_value=mock_response):
            result = api._get_json("/test")

        assert result == {"data": "value"}
        mock_response.raise_for_status.assert_called_once()

    def test_raises_on_http_error(self, api):
        """Should raise HTTPError on non-2xx status."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError()

        with patch.object(api, 'request', return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                api._get_json("/test")


class TestFetchLeases:
    """Tests for fetch_leases method."""

    def test_raises_on_invalid_identifier(self, api):
        """Should raise OneCoreException for invalid identifier."""
        with pytest.raises(OneCoreException) as exc_info:
            api.fetch_leases("invalidIdentifier", "123", "Bostad")

        assert "Ogiltig söktyp" in str(exc_info.value)

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'filter_lease_on_location_type')
    def test_fetches_by_lease_id(self, mock_filter, mock_get_json, api):
        """Should fetch leases by leaseId."""
        mock_get_json.return_value = [{"type": "Bostadskontrakt"}]
        mock_filter.return_value = [{"type": "Bostadskontrakt"}]

        result = api.fetch_leases("leaseId", "123", "Bostad")

        mock_get_json.assert_called_once_with(
            "/leases/123",
            params={"includeContacts": "true", "includeUpcomingLeases": "true"}
        )
        assert isinstance(result, list)

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'filter_lease_on_location_type')
    def test_url_encodes_value(self, mock_filter, mock_get_json, api):
        """Should URL encode special characters in value."""
        mock_get_json.return_value = [{"type": "Bostadskontrakt"}]
        mock_filter.return_value = [{"type": "Bostadskontrakt"}]

        api.fetch_leases("leaseId", "test/value with spaces", "Bostad")

        # Should be URL encoded
        call_args = mock_get_json.call_args[0][0]
        assert "test%2Fvalue%20with%20spaces" in call_args

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'filter_lease_on_location_type')
    def test_applies_location_type_filter(self, mock_filter, mock_get_json, api):
        """Should apply location type filter to results."""
        raw_data = [
            {"type": "Bostadskontrakt"},
            {"type": "P-Platskontrakt"}
        ]
        mock_get_json.return_value = raw_data
        mock_filter.return_value = [{"type": "Bostadskontrakt"}]

        result = api.fetch_leases("leaseId", "123", "Bostad")

        mock_filter.assert_called_once_with(raw_data, "Bostad")

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'filter_lease_on_location_type')
    def test_wraps_non_list_result_in_list(self, mock_filter, mock_get_json, api):
        """Should wrap non-list filtered result in list."""
        mock_get_json.return_value = {"type": "Bostadskontrakt"}
        mock_filter.return_value = {"type": "Bostadskontrakt"}

        result = api.fetch_leases("leaseId", "123", "Bostad")

        assert isinstance(result, list)
        assert len(result) == 1

    @patch.object(CoreApi, '_get_json')
    def test_raises_onecore_exception_on_http_error(self, mock_get_json, api):
        """Should raise OneCoreException on HTTPError."""
        mock_get_json.side_effect = requests.HTTPError()

        with pytest.raises(OneCoreException) as exc_info:
            api.fetch_leases("leaseId", "123", "Bostad")

        assert "Kunde inte hitta något resultat" in str(exc_info.value)


class TestFetchBuilding:
    """Tests for fetch_building method."""

    @patch.object(CoreApi, '_get_json')
    def test_fetches_building_by_code(self, mock_get_json, api):
        """Should fetch building by building code."""
        mock_get_json.return_value = {"code": "B123", "name": "Building"}

        with patch.object(api, 'fetch_staircases_for_building', return_value=[]):
            result = api.fetch_building("B123", "Övrigt")

        mock_get_json.assert_called_once()
        assert "buildings/by-building-code/B123" in mock_get_json.call_args[0][0]

    @patch.object(CoreApi, '_get_json')
    def test_returns_none_when_building_not_found(self, mock_get_json, api):
        """Should return None when building is not found."""
        mock_get_json.return_value = None

        result = api.fetch_building("B999", "Övrigt")

        assert result is None

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'fetch_maintenance_units_for_building')
    @patch.object(CoreApi, 'filter_maintenance_units_by_location_type')
    def test_fetches_maintenance_units_for_tvättstuga(
        self, mock_filter, mock_fetch_units, mock_get_json, api
    ):
        """Should fetch maintenance units when location_type is Tvättstuga."""
        mock_get_json.return_value = {"code": "B123"}
        mock_fetch_units.return_value = [{"type": "Tvättstuga"}]
        mock_filter.return_value = [{"type": "Tvättstuga"}]

        with patch.object(api, 'fetch_staircases_for_building', return_value=[]):
            result = api.fetch_building("B123", "Tvättstuga")

        mock_fetch_units.assert_called_once_with("B123")
        mock_filter.assert_called_once()
        assert "maintenance_units" in result

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'fetch_staircases_for_building')
    def test_fetches_staircases_for_uppgång(
        self, mock_fetch_stairs, mock_get_json, api
    ):
        """Should fetch staircases when location_type is Uppgång."""
        mock_get_json.return_value = {"code": "B123"}
        mock_fetch_stairs.return_value = [{"code": "A"}, {"code": "B"}]

        result = api.fetch_building("B123", "Uppgång")

        mock_fetch_stairs.assert_called_once_with("B123")
        assert result["staircases"] == [{"code": "A"}, {"code": "B"}]

    @patch.object(CoreApi, '_get_json')
    def test_no_maintenance_units_for_other_types(self, mock_get_json, api):
        """Should not fetch maintenance units for other location types."""
        mock_get_json.return_value = {"code": "B123"}

        with patch.object(api, 'fetch_maintenance_units_for_building') as mock_fetch:
            with patch.object(api, 'fetch_staircases_for_building', return_value=[]):
                result = api.fetch_building("B123", "Övrigt")

        mock_fetch.assert_not_called()
        assert result["maintenance_units"] == []

    @patch.object(CoreApi, '_get_json')
    def test_no_staircases_for_other_types(self, mock_get_json, api):
        """Should not fetch staircases for other location types."""
        mock_get_json.return_value = {"code": "B123"}

        with patch.object(api, 'fetch_staircases_for_building') as mock_fetch:
            result = api.fetch_building("B123", "Tvättstuga")

        mock_fetch.assert_not_called()
        assert result["staircases"] == []


class TestFetchProperties:
    """Tests for fetch_properties method."""

    @patch.object(CoreApi, '_get_json')
    def test_searches_properties_by_name(self, mock_get_json, api):
        """Should search properties by name."""
        mock_get_json.return_value = [{"code": "P1", "name": "Property 1"}]

        with patch.object(api, 'fetch_buildings_for_property', return_value=[]):
            api.fetch_properties("Test Property", "Övrigt")

        mock_get_json.assert_called_once_with("/properties/search", params={"q": "Test Property"})

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'fetch_buildings_for_property')
    def test_fetches_buildings_for_byggnad(
        self, mock_fetch_buildings, mock_get_json, api
    ):
        """Should fetch buildings when location_type is Byggnad."""
        mock_get_json.return_value = [{"code": "P1"}]
        mock_fetch_buildings.return_value = [{"code": "B1"}]

        result = api.fetch_properties("Test", "Byggnad")

        mock_fetch_buildings.assert_called_once_with("P1")
        assert result[0]["buildings"] == [{"code": "B1"}]

    @patch.object(CoreApi, '_get_json')
    @patch.object(CoreApi, 'fetch_maintenance_units')
    @patch.object(CoreApi, 'filter_maintenance_units_by_location_type')
    def test_fetches_maintenance_units_for_tvättstuga(
        self, mock_filter, mock_fetch_units, mock_get_json, api
    ):
        """Should fetch maintenance units when location_type is Tvättstuga."""
        mock_get_json.return_value = [{"code": "P1"}]
        mock_fetch_units.return_value = [{"type": "Tvättstuga"}]
        mock_filter.return_value = [{"type": "Tvättstuga"}]

        with patch.object(api, 'fetch_buildings_for_property', return_value=[]):
            result = api.fetch_properties("Test", "Tvättstuga")

        mock_fetch_units.assert_called_once_with("P1", "Tvättstuga")
        mock_filter.assert_called_once()

    @patch.object(CoreApi, '_get_json')
    def test_no_buildings_for_maintenance_unit_types(self, mock_get_json, api):
        """Should not fetch buildings for maintenance unit types."""
        mock_get_json.return_value = [{"code": "P1"}]

        with patch.object(api, 'fetch_buildings_for_property') as mock_fetch:
            with patch.object(api, 'fetch_maintenance_units', return_value=[]):
                api.fetch_properties("Test", "Tvättstuga")

        mock_fetch.assert_not_called()

    @patch.object(CoreApi, '_get_json')
    def test_handles_multiple_properties(self, mock_get_json, api):
        """Should process multiple properties."""
        mock_get_json.return_value = [
            {"code": "P1"},
            {"code": "P2"},
            {"code": "P3"}
        ]

        with patch.object(api, 'fetch_buildings_for_property', return_value=[]):
            result = api.fetch_properties("Test", "Byggnad")

        assert len(result) == 3
        assert result[0]["property"]["code"] == "P1"
        assert result[1]["property"]["code"] == "P2"
        assert result[2]["property"]["code"] == "P3"


class TestFetchFormData:
    """Tests for fetch_form_data method."""

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    def test_fetches_residence_for_bostadskontrakt(
        self, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should fetch residence for Bostadskontrakt."""
        mock_fetch_leases.return_value = [{
            "type": "Bostadskontrakt",
            "rentalPropertyId": "R123"
        }]
        mock_fetch_residence.return_value = {
            "property": {"code": "P1"}
        }

        with patch.object(api, 'fetch_maintenance_units', return_value=[]):
            result = api.fetch_form_data("leaseId", "123", "Bostad")

        mock_fetch_residence.assert_called_once_with("R123")
        assert result[0]["rental_property"]["property"]["code"] == "P1"

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    def test_fetches_residence_for_kooperativ_hyresrätt(
        self, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should fetch residence for Kooperativ hyresrätt."""
        mock_fetch_leases.return_value = [{
            "type": "Kooperativ hyresrätt",
            "rentalPropertyId": "R123"
        }]
        mock_fetch_residence.return_value = {
            "property": {"code": "P1"}
        }

        with patch.object(api, 'fetch_maintenance_units', return_value=[]):
            result = api.fetch_form_data("leaseId", "123", "Bostad")

        mock_fetch_residence.assert_called_once_with("R123")
        assert result[0]["rental_property"]["property"]["code"] == "P1"
        assert result[0]["parking_space"] is None
        assert result[0]["facility"] is None

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_parking_space')
    def test_fetches_parking_space_for_p_platskontrakt(
        self, mock_fetch_parking, mock_fetch_leases, api
    ):
        """Should fetch parking space for P-Platskontrakt."""
        mock_fetch_leases.return_value = [{
            "type": "P-Platskontrakt",
            "rentalPropertyId": "P123"
        }]
        mock_fetch_parking.return_value = {
            "parkingId": "P123"
        }

        result = api.fetch_form_data("leaseId", "123", "Bilplats")

        mock_fetch_parking.assert_called_with("P123")

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_facility')
    def test_fetches_facility_for_lokalkontrakt(
        self, mock_fetch_facility, mock_fetch_leases, api
    ):
        """Should fetch facility for Lokalkontrakt."""
        mock_fetch_leases.return_value = [{
            "type": "Lokalkontrakt",
            "rentalPropertyId": "L123"
        }]
        mock_fetch_facility.return_value = {
            "property": {"code": "P1"}
        }

        with patch.object(api, 'fetch_maintenance_units', return_value=[]):
            result = api.fetch_form_data("leaseId", "123", "Lokal")

        mock_fetch_facility.assert_called_with("L123")

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    @patch.object(CoreApi, 'fetch_maintenance_units')
    def test_fetches_maintenance_units_for_bostadskontrakt_with_tvättstuga(
        self, mock_fetch_units, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should fetch maintenance units for Bostadskontrakt with Tvättstuga."""
        mock_fetch_leases.return_value = [{
            "type": "Bostadskontrakt",
            "rentalPropertyId": "R123"
        }]
        mock_fetch_residence.return_value = {
            "property": {"code": "P1"}
        }
        mock_fetch_units.return_value = [{"type": "Tvättstuga"}]

        result = api.fetch_form_data("leaseId", "123", "Tvättstuga")

        mock_fetch_units.assert_called_once_with("P1", "Tvättstuga")
        assert result[0]["maintenance_units"] == [{"type": "Tvättstuga"}]

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    @patch.object(CoreApi, 'fetch_maintenance_units')
    def test_fetches_maintenance_units_for_kooperativ_hyresrätt_with_tvättstuga(
        self, mock_fetch_units, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should fetch maintenance units for Kooperativ hyresrätt with Tvättstuga."""
        mock_fetch_leases.return_value = [{
            "type": "Kooperativ hyresrätt",
            "rentalPropertyId": "R123"
        }]
        mock_fetch_residence.return_value = {
            "property": {"code": "P1"}
        }
        mock_fetch_units.return_value = [{"type": "Tvättstuga"}]

        result = api.fetch_form_data("leaseId", "123", "Tvättstuga")

        mock_fetch_units.assert_called_once_with("P1", "Tvättstuga")
        assert result[0]["maintenance_units"] == [{"type": "Tvättstuga"}]

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_parking_space')
    def test_no_maintenance_units_for_p_platskontrakt(
        self, mock_fetch_parking, mock_fetch_leases, api
    ):
        """Should not fetch maintenance units for P-Platskontrakt."""
        mock_fetch_leases.return_value = [{
            "type": "P-Platskontrakt",
            "rentalPropertyId": "P123"
        }]
        mock_fetch_parking.return_value = {"parkingId": "P123"}

        with patch.object(api, 'fetch_maintenance_units') as mock_fetch_units:
            result = api.fetch_form_data("leaseId", "123", "Bilplats")

        mock_fetch_units.assert_not_called()
        assert result[0]["maintenance_units"] == []

    @patch.object(CoreApi, 'fetch_leases')
    def test_returns_none_when_no_leases(self, mock_fetch_leases, api):
        """Should return None when no leases found."""
        mock_fetch_leases.return_value = []

        result = api.fetch_form_data("leaseId", "999", "Bostad")

        assert result is None

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    def test_handles_multiple_leases(
        self, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should process multiple leases."""
        mock_fetch_leases.return_value = [
            {"type": "Bostadskontrakt", "rentalPropertyId": "R1"},
            {"type": "Bostadskontrakt", "rentalPropertyId": "R2"}
        ]
        mock_fetch_residence.side_effect = [
            {"property": {"code": "P1"}},  # R1
            {"property": {"code": "P2"}},  # R2
        ]

        with patch.object(api, 'fetch_maintenance_units', return_value=[]):
            result = api.fetch_form_data("leaseId", "123", "Bostad")

        assert len(result) == 2
        assert result[0]["rental_property"]["property"]["code"] == "P1"
        assert result[1]["rental_property"]["property"]["code"] == "P2"

    @patch.object(CoreApi, 'fetch_leases')
    def test_skips_unknown_lease_types(self, mock_fetch_leases, api):
        """Should skip leases with unknown types."""
        mock_fetch_leases.return_value = [
            {"type": "UnknownType", "rentalPropertyId": "U1"}
        ]

        result = api.fetch_form_data("leaseId", "123", "Bostad")

        assert result == []

    @patch.object(CoreApi, 'fetch_leases')
    @patch.object(CoreApi, 'fetch_residence')
    def test_handles_whitespace_in_lease_type(
        self, mock_fetch_residence, mock_fetch_leases, api
    ):
        """Should handle whitespace in lease type."""
        mock_fetch_leases.return_value = [{
            "type": " Bostadskontrakt ",
            "rentalPropertyId": "R123"
        }]
        mock_fetch_residence.return_value = {
            "property": {"code": "P1"}
        }

        with patch.object(api, 'fetch_maintenance_units', return_value=[]):
            result = api.fetch_form_data("leaseId", "123", "Bostad")

        assert len(result) == 1

    @patch.object(CoreApi, 'fetch_leases')
    def test_raises_and_logs_on_exception(self, mock_fetch_leases, api):
        """Should log and re-raise exceptions."""
        mock_fetch_leases.side_effect = Exception("Test error")

        with pytest.raises(Exception) as exc_info:
            api.fetch_form_data("leaseId", "123", "Bostad")

        assert str(exc_info.value) == "Test error"
