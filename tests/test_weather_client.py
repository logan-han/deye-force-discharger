import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import requests

from weather_client import WeatherClient, WeatherAnalyser, WeatherAPIError


class TestWeatherClient:
    """Tests for WeatherClient class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            api_key="test_api_key",
            city_name="Sydney, AU"
        )
        # Pre-set coordinates to avoid geocoding in tests
        self.client.latitude = -33.8688
        self.client.longitude = 151.2093
        self.client._coordinates_cached = True

    def test_init(self):
        """Test WeatherClient initialization"""
        client = WeatherClient(api_key="test_api_key", city_name="Sydney, AU")
        assert client.api_key == "test_api_key"
        assert client.city_name == "Sydney, AU"
        assert client.latitude is None
        assert client.longitude is None
        assert client._coordinates_cached is False
        assert client.base_url == "https://api.openweathermap.org/data/2.5"
        assert client._cache == {}
        assert client._cache_time is None

    def test_is_cache_valid_no_cache(self):
        """Test cache validity when no cache exists"""
        assert self.client._is_cache_valid() is False

    def test_is_cache_valid_expired(self):
        """Test cache validity when cache is expired"""
        self.client._cache_time = datetime(2020, 1, 1)
        assert self.client._is_cache_valid() is False

    def test_is_cache_valid_fresh(self):
        """Test cache validity when cache is fresh"""
        self.client._cache_time = datetime.now()
        assert self.client._is_cache_valid() is True

    @patch('weather_client.requests.get')
    def test_get_forecast_legacy_success(self, mock_get):
        """Test successful forecast fetch using legacy 5-day API"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "city": {"name": "Sydney", "timezone": 36000},  # UTC+10
            "list": [
                {
                    "dt": 1703203200,  # 2023-12-22 02:00 UTC (12:00 local)
                    "main": {"temp": 25.0},
                    "weather": [{"main": "Clear", "description": "clear sky"}],
                    "clouds": {"all": 10},
                    "pop": 0,
                    "rain": {}
                },
                {
                    "dt": 1703214000,  # 2023-12-22 05:00 UTC (15:00 local)
                    "main": {"temp": 28.0},
                    "weather": [{"main": "Clear", "description": "clear sky"}],
                    "clouds": {"all": 15},
                    "pop": 0.1,
                    "rain": {}
                },
                {
                    "dt": 1703289600,  # 2023-12-23 02:00 UTC (12:00 local next day)
                    "main": {"temp": 22.0},
                    "weather": [{"main": "Rain", "description": "light rain"}],
                    "clouds": {"all": 80},
                    "pop": 0.7,
                    "rain": {"3h": 5.2}
                }
            ]
        }
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is True
        assert result["location"] == "Sydney, AU"  # Uses city_name from client
        assert len(result["daily"]) >= 1  # At least one day aggregated
        assert result["daily"][0]["condition"] == "Clear"

    @patch('weather_client.requests.get')
    def test_get_forecast_api_error(self, mock_get):
        """Test error handling when API returns 401"""
        mock_response = Mock()
        mock_response.status_code = 401

        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        # Should return error with success=False
        assert result["success"] is False
        assert "error" in result

    @patch('weather_client.requests.get')
    def test_get_forecast_uses_cache(self, mock_get):
        """Test that forecast uses cache when valid"""
        self.client._cache["forecast"] = {"success": True, "daily": []}
        self.client._cache_time = datetime.now()

        result = self.client.get_forecast()

        mock_get.assert_not_called()
        assert result == {"success": True, "daily": []}

    @patch('weather_client.requests.get')
    def test_get_forecast_network_error(self, mock_get):
        """Test forecast fetch with network error"""
        mock_get.side_effect = requests.exceptions.RequestException("Network error")

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "error" in result

    def test_parse_onecall_forecast(self):
        """Test parsing One Call API response"""
        data = {
            "timezone": "Test/Zone",
            "current": {
                "temp": 22.0,
                "weather": [{"main": "Clouds"}],
                "clouds": 50
            },
            "daily": [
                {
                    "dt": 1703203200,
                    "temp": {"min": 15.0, "max": 25.0},
                    "weather": [{"main": "Clear", "description": "sunny", "icon": "01d"}],
                    "clouds": 5,
                    "pop": 0,
                    "uvi": 9.0
                }
            ]
        }

        result = self.client._parse_onecall_forecast(data)

        assert result["success"] is True
        assert result["location"] == "Sydney, AU"  # Uses city_name from client (fallback would be "Test/Zone")
        assert result["current"]["temp"] == 22.0
        assert len(result["daily"]) == 1
        assert result["daily"][0]["temp_min"] == 15.0
        assert result["daily"][0]["temp_max"] == 25.0

    def test_parse_legacy_forecast(self):
        """Test parsing legacy 5-day API response"""
        data = {
            "city": {"name": "TestCity"},
            "list": [
                {
                    "dt": 1703203200,
                    "main": {"temp": 20.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 10},
                    "pop": 0,
                    "rain": {}
                },
                {
                    "dt": 1703214000,
                    "main": {"temp": 25.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 15},
                    "pop": 0.2,
                    "rain": {"3h": 0.5}
                }
            ]
        }

        result = self.client._parse_legacy_forecast(data)

        assert result["success"] is True
        assert result["location"] == "Sydney, AU"  # Uses city_name from client (fallback would be "TestCity")
        assert len(result["daily"]) >= 1


class TestWeatherAnalyser:
    """Tests for WeatherAnalyser class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.analyser = WeatherAnalyser(
            bad_conditions=["Rain", "Thunderstorm", "Drizzle", "Snow"],
            min_cloud_cover=70
        )

    def test_init_default(self):
        """Test WeatherAnalyser default initialization"""
        analyser = WeatherAnalyser()
        assert analyser.bad_conditions == ["Rain", "Thunderstorm", "Drizzle", "Snow"]
        assert analyser.min_cloud_cover == 70

    def test_init_custom(self):
        """Test WeatherAnalyser custom initialization"""
        analyser = WeatherAnalyser(
            bad_conditions=["Rain"],
            min_cloud_cover=80
        )
        assert analyser.bad_conditions == ["Rain"]
        assert analyser.min_cloud_cover == 80

    def test_is_bad_weather_day_rain(self):
        """Test bad weather detection for rain"""
        day = {"condition": "Rain", "clouds": 50, "pop": 30}
        assert self.analyser._is_bad_weather_day(day) is True

    def test_is_bad_weather_day_thunderstorm(self):
        """Test bad weather detection for thunderstorm"""
        day = {"condition": "Thunderstorm", "clouds": 90, "pop": 80}
        assert self.analyser._is_bad_weather_day(day) is True

    def test_is_bad_weather_day_high_clouds(self):
        """Test bad weather detection for high cloud cover"""
        day = {"condition": "Clouds", "clouds": 85, "pop": 20}
        assert self.analyser._is_bad_weather_day(day) is True

    def test_is_bad_weather_day_high_pop(self):
        """Test bad weather detection for high precipitation probability"""
        day = {"condition": "Clouds", "clouds": 50, "pop": 75}
        assert self.analyser._is_bad_weather_day(day) is True

    def test_is_bad_weather_day_clear(self):
        """Test good weather detection for clear day"""
        day = {"condition": "Clear", "clouds": 10, "pop": 5}
        assert self.analyser._is_bad_weather_day(day) is False

    def test_is_bad_weather_day_partly_cloudy(self):
        """Test good weather for partly cloudy day"""
        day = {"condition": "Clouds", "clouds": 40, "pop": 10}
        assert self.analyser._is_bad_weather_day(day) is False

    def test_count_consecutive_bad_days_none(self):
        """Test consecutive bad days count with no bad days"""
        daily = [
            {"is_bad_weather": False},
            {"is_bad_weather": False},
            {"is_bad_weather": False}
        ]
        assert self.analyser._count_consecutive_bad_days(daily) == 0

    def test_count_consecutive_bad_days_all(self):
        """Test consecutive bad days count with all bad days"""
        daily = [
            {"is_bad_weather": True},
            {"is_bad_weather": True},
            {"is_bad_weather": True}
        ]
        assert self.analyser._count_consecutive_bad_days(daily) == 3

    def test_count_consecutive_bad_days_mixed(self):
        """Test consecutive bad days count with mixed days"""
        daily = [
            {"is_bad_weather": True},
            {"is_bad_weather": True},
            {"is_bad_weather": False},
            {"is_bad_weather": True}
        ]
        assert self.analyser._count_consecutive_bad_days(daily) == 2

    def test_count_consecutive_bad_days_starts_good(self):
        """Test consecutive bad days when first day is good"""
        daily = [
            {"is_bad_weather": False},
            {"is_bad_weather": True},
            {"is_bad_weather": True}
        ]
        assert self.analyser._count_consecutive_bad_days(daily) == 0

    def test_analyse_forecast_success(self):
        """Test forecast analysis marks bad weather days"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Rain", "clouds": 80, "pop": 70},
                {"date": "2023-12-23", "condition": "Clear", "clouds": 10, "pop": 5},
                {"date": "2023-12-24", "condition": "Thunderstorm", "clouds": 95, "pop": 90}
            ]
        }

        result = self.analyser.analyse_forecast(forecast)

        assert result["daily"][0]["is_bad_weather"] is True
        assert result["daily"][1]["is_bad_weather"] is False
        assert result["daily"][2]["is_bad_weather"] is True
        assert "bad_weather_days" in result
        assert result["consecutive_bad_days"] == 1

    def test_analyse_forecast_failure(self):
        """Test forecast analysis with failed forecast"""
        forecast = {"success": False, "error": "API error"}

        result = self.analyser.analyse_forecast(forecast)

        assert result == forecast

    def test_analyse_forecast_no_daily(self):
        """Test forecast analysis with no daily data"""
        forecast = {"success": True, "daily": None}

        result = self.analyser.analyse_forecast(forecast)

        assert result == forecast

    def test_should_skip_discharge_low_solar(self):
        """Test skip discharge when solar forecast is below threshold"""
        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today", "estimated_solar_kwh": 8.0},
                {"day_name": "Tomorrow", "estimated_solar_kwh": 3.5}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        assert should_skip is True
        assert "Low solar" in reason
        assert "3.5" in reason

    def test_should_skip_discharge_good_solar(self):
        """Test no skip when solar forecast is above threshold"""
        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today", "estimated_solar_kwh": 8.0},
                {"day_name": "Tomorrow", "estimated_solar_kwh": 12.5}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        assert should_skip is False
        assert "Good solar" in reason

    def test_should_skip_discharge_no_threshold(self):
        """Test no skip when no solar threshold configured"""
        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today", "estimated_solar_kwh": 3.0},
                {"day_name": "Tomorrow", "estimated_solar_kwh": 2.0}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=0)

        assert should_skip is False
        assert "not configured" in reason

    def test_should_skip_discharge_failed_forecast(self):
        """Test skip check with failed forecast"""
        forecast = {"success": False, "error": "API error"}

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        assert should_skip is False
        assert "unavailable" in reason

    def test_should_skip_discharge_no_solar_estimate(self):
        """Test no skip when solar estimate not available"""
        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today"},
                {"day_name": "Tomorrow"}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        assert should_skip is False
        assert "not available" in reason

    def test_should_skip_discharge_exact_threshold(self):
        """Test no skip when solar equals threshold exactly"""
        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today", "estimated_solar_kwh": 5.0},
                {"day_name": "Tomorrow", "estimated_solar_kwh": 5.0}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        assert should_skip is False
        assert "Good solar" in reason


class TestWeatherClientEdgeCases:
    """Edge case tests for WeatherClient"""

    def test_empty_daily_forecast(self):
        """Test handling of empty daily forecast"""
        client = WeatherClient("key", "Test City")
        data = {
            "timezone": "UTC",
            "current": {},
            "daily": []
        }

        result = client._parse_onecall_forecast(data)

        assert result["success"] is True
        assert result["daily"] == []

    def test_missing_weather_data(self):
        """Test handling of missing weather data in daily forecast"""
        client = WeatherClient("key", "Test City")
        data = {
            "timezone": "UTC",
            "current": {},
            "daily": [
                {
                    "dt": 1703203200,
                    "temp": {},
                    "weather": [],
                    "clouds": 0
                }
            ]
        }

        result = client._parse_onecall_forecast(data)

        assert result["success"] is True
        assert result["daily"][0]["condition"] == "Unknown"

    def test_legacy_forecast_empty_list(self):
        """Test legacy forecast with empty list"""
        client = WeatherClient("key", "Test City")
        data = {
            "city": {"name": "Test"},
            "list": []
        }

        result = client._parse_legacy_forecast(data)

        assert result["success"] is True
        assert result["daily"] == []


class TestWeatherAnalyserEdgeCases:
    """Edge case tests for WeatherAnalyser"""

    def test_empty_bad_conditions(self):
        """Test analyzer with empty bad conditions list"""
        analyser = WeatherAnalyser(bad_conditions=[], min_cloud_cover=100)
        day = {"condition": "Rain", "clouds": 50, "pop": 50}

        # Should not flag as bad since no conditions in list
        # But pop >= 70 would still trigger
        assert analyser._is_bad_weather_day(day) is False

    def test_very_low_cloud_threshold(self):
        """Test analyzer with very low cloud threshold"""
        analyser = WeatherAnalyser(bad_conditions=[], min_cloud_cover=10)
        day = {"condition": "Clear", "clouds": 15, "pop": 0}

        assert analyser._is_bad_weather_day(day) is True

    def test_empty_daily_list(self):
        """Test consecutive count with empty list"""
        analyser = WeatherAnalyser()

        assert analyser._count_consecutive_bad_days([]) == 0


class TestWeatherAPIError:
    """Tests for WeatherAPIError exception class"""

    def test_basic_error(self):
        """Test basic error creation"""
        error = WeatherAPIError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.is_temporary is False
        assert error.status_code is None

    def test_temporary_error(self):
        """Test temporary error flag"""
        error = WeatherAPIError("Timeout", is_temporary=True)
        assert error.is_temporary is True

    def test_error_with_status_code(self):
        """Test error with status code"""
        error = WeatherAPIError("Server error", is_temporary=True, status_code=503)
        assert error.status_code == 503


class TestWeatherClientAPIDown:
    """Tests for weather client when API is down"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            api_key="test_api_key",
            city_name="Sydney, AU"
        )
        # Pre-set coordinates to avoid geocoding in tests
        self.client.latitude = -33.8688
        self.client.longitude = 151.2093
        self.client._coordinates_cached = True

    @patch('weather_client.requests.get')
    def test_connection_timeout(self, mock_get):
        """Test handling of connection timeout"""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    def test_dns_resolution_failure(self, mock_get):
        """Test handling of DNS resolution failure"""
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "Failed to establish a new connection: [Errno -2] Name or service not known"
        )

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "dns" in result["error"].lower() or "hostname" in result["error"].lower()
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    def test_connection_refused(self, mock_get):
        """Test handling of connection refused error"""
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "refused" in result["error"].lower() or "connect" in result["error"].lower()
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_server_error_503(self, mock_sleep, mock_get):
        """Test handling of 503 server error with retries"""
        mock_response = Mock()
        mock_response.status_code = 503
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "server error" in result["error"].lower() or "503" in result["error"]
        assert result.get("is_temporary") is True
        # Should have retried
        assert mock_get.call_count >= 2

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_rate_limit_429(self, mock_sleep, mock_get):
        """Test handling of rate limit (429) error"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "rate limit" in result["error"].lower()
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    def test_invalid_api_key_401(self, mock_get):
        """Test handling of invalid API key (401)"""
        # First call (One Call API) returns 401
        mock_response_401 = Mock()
        mock_response_401.status_code = 401

        mock_get.return_value = mock_response_401

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "api key" in result["error"].lower() or "invalid" in result["error"].lower()
        assert result.get("is_temporary") is False

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_server_error_recovery(self, mock_sleep, mock_get):
        """Test recovery after transient server error"""
        # First call fails with 503, second succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 503

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {
            "timezone": "Test/Zone",
            "current": {"temp": 20, "weather": [{"main": "Clear"}], "clouds": 10},
            "daily": []
        }

        mock_get.side_effect = [mock_response_fail, mock_response_success]

        result = self.client.get_forecast()

        assert result["success"] is True

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_timeout_recovery(self, mock_sleep, mock_get):
        """Test recovery after timeout"""
        # First call times out, second succeeds
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {
            "timezone": "Test/Zone",
            "current": {"temp": 20, "weather": [{"main": "Clear"}], "clouds": 10},
            "daily": []
        }

        mock_get.side_effect = [
            requests.exceptions.Timeout("Timeout"),
            mock_response_success
        ]

        result = self.client.get_forecast()

        assert result["success"] is True

    @patch('weather_client.requests.get')
    def test_both_apis_down(self, mock_get):
        """Test when both One Call and legacy APIs are down"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "daily" in result
        assert result["daily"] == []

    @patch('weather_client.requests.get')
    def test_generic_request_exception(self, mock_get):
        """Test handling of generic RequestException"""
        mock_get.side_effect = requests.exceptions.RequestException("Unknown error")

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "error" in result

    @patch('weather_client.requests.get')
    def test_uses_cache_on_api_failure(self, mock_get):
        """Test that cached data is returned when API fails"""
        # Pre-populate cache
        cached_forecast = {
            "success": True,
            "daily": [{"date": "2023-12-22", "condition": "Clear"}]
        }
        self.client._cache["forecast"] = cached_forecast
        self.client._cache_time = datetime.now()

        # API call should not be made when cache is valid
        result = self.client.get_forecast()

        mock_get.assert_not_called()
        assert result == cached_forecast


class TestWeatherClientCitySearch:
    """Tests for city search functionality"""

    @patch('weather_client.requests.get')
    def test_search_cities_success(self, mock_get):
        """Test successful city search"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = [
            {
                "name": "Sydney",
                "country": "AU",
                "state": "New South Wales",
                "lat": -33.8688,
                "lon": 151.2093
            },
            {
                "name": "Sydney",
                "country": "CA",
                "state": "Nova Scotia",
                "lat": 46.1368,
                "lon": -60.1942
            }
        ]
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("test_key", "Sydney")

        assert len(result) == 2
        assert result[0]["name"] == "Sydney"
        assert result[0]["country"] == "AU"
        assert result[0]["display_name"] == "Sydney, New South Wales, AU"
        assert result[1]["display_name"] == "Sydney, Nova Scotia, CA"

    @patch('weather_client.requests.get')
    def test_search_cities_no_state(self, mock_get):
        """Test city search when state is not present"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = [
            {
                "name": "London",
                "country": "GB",
                "lat": 51.5074,
                "lon": -0.1278
            }
        ]
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("test_key", "London")

        assert len(result) == 1
        assert result[0]["display_name"] == "London, GB"

    def test_search_cities_short_query(self):
        """Test city search with query less than 2 characters"""
        result = WeatherClient.search_cities("test_key", "A")
        assert result == []

    def test_search_cities_empty_query(self):
        """Test city search with empty query"""
        result = WeatherClient.search_cities("test_key", "")
        assert result == []

    @patch('weather_client.requests.get')
    def test_search_cities_api_error(self, mock_get):
        """Test city search when API fails"""
        mock_get.side_effect = Exception("API error")

        result = WeatherClient.search_cities("test_key", "Sydney")

        assert result == []

    @patch('weather_client.requests.get')
    def test_search_cities_empty_results(self, mock_get):
        """Test city search with no results"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("test_key", "NonexistentCity12345")

        assert result == []


class TestWeatherClientSolarEstimates:
    """Tests for solar output estimation"""

    def test_estimate_solar_output_clear_day(self):
        """Test solar estimate for clear day"""
        result = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=5.0,
            clouds=10,
            condition="Clear",
            pop=5
        )

        # Clear day should have high output
        assert result > 10  # Should be around 17-18 kWh for 5kW system

    def test_estimate_solar_output_cloudy_day(self):
        """Test solar estimate for cloudy day"""
        result = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=5.0,
            clouds=80,
            condition="Clouds",
            pop=20
        )

        # Cloudy day should have reduced output
        assert result < 17  # Adjusted threshold for new formula

    def test_estimate_solar_output_rainy_day(self):
        """Test solar estimate for rainy day"""
        result = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=5.0,
            clouds=90,
            condition="Rain",
            pop=80
        )

        # Rainy day should have significantly reduced output
        assert result < 10  # Adjusted threshold for new formula

    def test_estimate_solar_output_scales_with_capacity(self):
        """Test that solar estimate scales with panel capacity"""
        result_5kw = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=5.0,
            clouds=20,
            condition="Clear",
            pop=10
        )
        result_10kw = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=10.0,
            clouds=20,
            condition="Clear",
            pop=10
        )

        # 10kW system should produce ~2x of 5kW system
        assert abs(result_10kw - result_5kw * 2) < 1

    def test_estimate_solar_output_zero_capacity(self):
        """Test solar estimate with zero capacity"""
        result = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=0,
            clouds=10,
            condition="Clear",
            pop=5
        )

        assert result == 0

    def test_estimate_solar_output_unknown_condition(self):
        """Test solar estimate with unknown weather condition"""
        result = WeatherClient.estimate_solar_output_simple(
            panel_capacity_kw=5.0,
            clouds=30,
            condition="UnknownWeather",
            pop=10
        )

        # Should use default factor of 0.65
        assert result > 0


class TestWeatherClientCityName:
    """Tests for city_name parameter functionality"""

    def test_init_with_city_name(self):
        """Test WeatherClient initialization with city_name"""
        client = WeatherClient(
            api_key="test_key",
            city_name="Sydney, New South Wales, AU"
        )

        assert client.city_name == "Sydney, New South Wales, AU"
        assert client.latitude is None
        assert client.longitude is None
        assert client._coordinates_cached is False

    @patch.object(WeatherClient, 'search_cities')
    def test_geocode_city_success(self, mock_search):
        """Test successful geocoding of city name"""
        mock_search.return_value = [{"lat": -33.8688, "lon": 151.2093, "name": "Sydney"}]

        client = WeatherClient(api_key="test_key", city_name="Sydney, AU")
        result = client._geocode_city()

        assert result is True
        assert client.latitude == -33.8688
        assert client.longitude == 151.2093
        assert client._coordinates_cached is True

    @patch.object(WeatherClient, 'search_cities')
    def test_geocode_city_failure(self, mock_search):
        """Test failed geocoding of city name"""
        mock_search.return_value = []

        client = WeatherClient(api_key="test_key", city_name="Nonexistent City")
        result = client._geocode_city()

        assert result is False
        assert client.latitude is None
        assert client._coordinates_cached is True  # Cached as failed

    def test_parse_onecall_uses_city_name(self):
        """Test that _parse_onecall_forecast uses city_name for location"""
        client = WeatherClient(
            api_key="test_key",
            city_name="Sydney, AU"
        )

        data = {
            "timezone": "Australia/Sydney",
            "current": {"temp": 25, "weather": [{"main": "Clear"}], "clouds": 10},
            "daily": []
        }

        result = client._parse_onecall_forecast(data)

        assert result["location"] == "Sydney, AU"

    def test_parse_legacy_uses_city_name(self):
        """Test that _parse_legacy_forecast uses city_name for location"""
        client = WeatherClient(
            api_key="test_key",
            city_name="Sydney, AU"
        )

        data = {
            "city": {"name": "Sydney"},
            "list": []
        }

        result = client._parse_legacy_forecast(data)

        assert result["location"] == "Sydney, AU"


class TestWeatherAnalyserWithSolarEstimates:
    """Tests for WeatherAnalyser with solar estimate integration"""

    def setup_method(self):
        """Set up test fixtures"""
        self.analyser = WeatherAnalyser(
            bad_conditions=["Rain", "Thunderstorm"],
            min_cloud_cover=70
        )

    def test_analyse_forecast_with_panel_capacity_and_hourly_data(self):
        """Test that analyse_forecast adds solar estimates when panel_capacity and hourly data provided"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5},
                {"date": "2023-12-23", "condition": "Rain", "clouds": 90, "pop": 80}
            ]
        }

        # Create a mock weather client with hourly data
        mock_weather_client = Mock()
        # Clear day returns higher estimate
        mock_weather_client.estimate_solar_output_hourly.side_effect = [20.0, 5.0]

        result = self.analyser.analyse_forecast(
            forecast,
            panel_capacity_kw=5.0,
            weather_client=mock_weather_client
        )

        assert "estimated_solar_kwh" in result["daily"][0]
        assert "estimated_solar_kwh" in result["daily"][1]
        # Clear day should have higher estimate than rainy day
        assert result["daily"][0]["estimated_solar_kwh"] > result["daily"][1]["estimated_solar_kwh"]

    def test_analyse_forecast_without_panel_capacity(self):
        """Test that analyse_forecast sets solar estimates to None when no capacity"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}
            ]
        }

        result = self.analyser.analyse_forecast(forecast)

        # Key is present but value is None
        assert result["daily"][0]["estimated_solar_kwh"] is None
        assert result["daily"][0]["has_solar_prediction"] is False

    def test_analyse_forecast_with_zero_capacity(self):
        """Test that analyse_forecast sets estimates to None for zero capacity"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}
            ]
        }

        result = self.analyser.analyse_forecast(forecast, panel_capacity_kw=0)

        # Key is present but value is None
        assert result["daily"][0]["estimated_solar_kwh"] is None
        assert result["daily"][0]["has_solar_prediction"] is False


class TestEstimateSolarOutputHourly:
    """Tests for estimate_solar_output_hourly method"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            api_key="test_api_key",
            city_name="Sydney, AU"
        )
        self.client.latitude = -33.8688
        self.client.longitude = 151.2093
        self.client._coordinates_cached = True

    def test_hourly_estimate_no_cache(self):
        """Test hourly estimate returns None when no cache"""
        self.client._cache = {}

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is None

    def test_hourly_estimate_no_hourly_data(self):
        """Test hourly estimate returns None when no hourly_data in cache"""
        self.client._cache = {"forecast": {}}

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is None

    def test_hourly_estimate_no_data_for_date(self):
        """Test hourly estimate returns None for missing date"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-23": []  # Different date
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is None

    def test_hourly_estimate_clear_day(self):
        """Test hourly estimate for clear day"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 6, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 9, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 12, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 15, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 18, "clouds": 15, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        assert result > 10  # Clear day should have decent output

    def test_hourly_estimate_rainy_day(self):
        """Test hourly estimate for rainy day"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 6, "clouds": 90, "condition": "Rain", "pop": 80},
                    {"hour": 9, "clouds": 95, "condition": "Rain", "pop": 90},
                    {"hour": 12, "clouds": 100, "condition": "Rain", "pop": 85},
                    {"hour": 15, "clouds": 90, "condition": "Rain", "pop": 70},
                    {"hour": 18, "clouds": 85, "condition": "Drizzle", "pop": 60}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        assert result < 10  # Rainy day should have low output

    def test_hourly_estimate_mixed_weather(self):
        """Test hourly estimate for mixed weather day"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 6, "clouds": 20, "condition": "Clear", "pop": 0},
                    {"hour": 9, "clouds": 40, "condition": "Clouds", "pop": 10},
                    {"hour": 12, "clouds": 80, "condition": "Rain", "pop": 60},
                    {"hour": 15, "clouds": 30, "condition": "Clear", "pop": 5},
                    {"hour": 18, "clouds": 20, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result_clear = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        # Should be between clear and rainy
        assert result_clear is not None

    def test_hourly_estimate_nighttime_hours_excluded(self):
        """Test that nighttime hours are excluded"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 0, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 3, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 21, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 12, "clouds": 10, "condition": "Clear", "pop": 0}  # Only daytime
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        # Only one daytime hour, so output should be limited
        assert result < 20

    def test_hourly_estimate_scales_with_capacity(self):
        """Test that output scales with panel capacity"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 9, "clouds": 20, "condition": "Clear", "pop": 5},
                    {"hour": 12, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 15, "clouds": 15, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result_5kw = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")
        result_10kw = self.client.estimate_solar_output_hourly(10.0, "2023-12-22")

        assert result_10kw > result_5kw
        # Should be approximately 2x
        assert abs(result_10kw / result_5kw - 2) < 0.1

    def test_hourly_estimate_different_latitudes(self):
        """Test that latitude affects base production"""
        # Equator latitude (high solar)
        self.client.latitude = 0
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 9, "clouds": 20, "condition": "Clear", "pop": 5},
                    {"hour": 12, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 15, "clouds": 15, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result_equator = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        # High latitude (lower solar)
        self.client.latitude = 60
        result_high_lat = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        # Equator should have higher production
        assert result_equator > result_high_lat

    def test_hourly_estimate_unknown_condition(self):
        """Test with unknown weather condition"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 12, "clouds": 30, "condition": "UnknownWeather", "pop": 10}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None  # Should handle gracefully

    def test_hourly_estimate_fog_condition(self):
        """Test with fog condition"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 9, "clouds": 40, "condition": "Fog", "pop": 0},
                    {"hour": 12, "clouds": 30, "condition": "Fog", "pop": 0},
                    {"hour": 15, "clouds": 20, "condition": "Mist", "pop": 0}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        # Fog reduces output significantly

    def test_hourly_estimate_thunderstorm(self):
        """Test with thunderstorm condition"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 12, "clouds": 100, "condition": "Thunderstorm", "pop": 90}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        assert result < 5  # Should be very low

    def test_hourly_estimate_default_latitude(self):
        """Test with no latitude set uses default"""
        self.client.latitude = None
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 12, "clouds": 10, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None


class TestMakeRequestWithRetry:
    """Tests for _make_request_with_retry method"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            api_key="test_api_key",
            city_name="Sydney, AU"
        )

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_retry_on_server_error_500(self, mock_sleep, mock_get):
        """Test retry on 500 server error"""
        # First two calls fail with 500, third succeeds
        mock_fail = Mock()
        mock_fail.status_code = 500

        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [mock_fail, mock_fail, mock_success]

        result = self.client._make_request_with_retry("http://test.com", {})

        assert result.status_code == 200
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_rate_limit_429_with_retry_after(self, mock_sleep, mock_get):
        """Test handling of 429 rate limit with Retry-After header"""
        mock_fail = Mock()
        mock_fail.status_code = 429
        mock_fail.headers = {"Retry-After": "30"}

        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [mock_fail, mock_success]

        result = self.client._make_request_with_retry("http://test.com", {})

        assert result.status_code == 200
        # Should wait based on Retry-After (capped at 60)
        mock_sleep.assert_called_with(30)

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_rate_limit_retry_after_capped(self, mock_sleep, mock_get):
        """Test that Retry-After is capped at 60 seconds"""
        mock_fail = Mock()
        mock_fail.status_code = 429
        mock_fail.headers = {"Retry-After": "300"}  # 5 minutes

        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [mock_fail, mock_success]

        result = self.client._make_request_with_retry("http://test.com", {})

        # Should wait max 60 seconds
        mock_sleep.assert_called_with(60)

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_exponential_backoff_on_server_error(self, mock_sleep, mock_get):
        """Test exponential backoff timing"""
        mock_fail = Mock()
        mock_fail.status_code = 503

        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [mock_fail, mock_fail, mock_success]

        result = self.client._make_request_with_retry("http://test.com", {})

        # First retry waits 1s (2^0), second waits 2s (2^1)
        assert mock_sleep.call_args_list[0][0][0] == 1
        assert mock_sleep.call_args_list[1][0][0] == 2

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_max_retries_exceeded_rate_limit(self, mock_sleep, mock_get):
        """Test that WeatherAPIError is raised after max retries on 429"""
        mock_fail = Mock()
        mock_fail.status_code = 429
        mock_fail.headers = {}

        mock_get.return_value = mock_fail

        with pytest.raises(WeatherAPIError) as exc_info:
            self.client._make_request_with_retry("http://test.com", {})

        assert "rate limit" in str(exc_info.value).lower()
        assert exc_info.value.is_temporary is True
        assert exc_info.value.status_code == 429

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_max_retries_exceeded_server_error(self, mock_sleep, mock_get):
        """Test that WeatherAPIError is raised after max retries on 5xx"""
        mock_fail = Mock()
        mock_fail.status_code = 503

        mock_get.return_value = mock_fail

        with pytest.raises(WeatherAPIError) as exc_info:
            self.client._make_request_with_retry("http://test.com", {})

        assert exc_info.value.is_temporary is True
        assert exc_info.value.status_code == 503

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_timeout_retry(self, mock_sleep, mock_get):
        """Test retry on timeout"""
        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [
            requests.exceptions.Timeout("Timeout"),
            mock_success
        ]

        result = self.client._make_request_with_retry("http://test.com", {})

        assert result.status_code == 200
        assert mock_get.call_count == 2

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_connection_error_dns_failure(self, mock_sleep, mock_get):
        """Test retry on DNS resolution failure"""
        mock_success = Mock()
        mock_success.status_code = 200

        mock_get.side_effect = [
            requests.exceptions.ConnectionError("Name or service not known"),
            mock_success
        ]

        result = self.client._make_request_with_retry("http://test.com", {})

        assert result.status_code == 200

    @patch('weather_client.requests.get')
    def test_connection_refused_no_retry(self, mock_get):
        """Test connection refused raises immediately"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with pytest.raises(WeatherAPIError) as exc_info:
            self.client._make_request_with_retry("http://test.com", {}, max_retries=0)

        assert "refused" in str(exc_info.value).lower()
        assert exc_info.value.is_temporary is True

    @patch('weather_client.requests.get')
    def test_generic_request_exception(self, mock_get):
        """Test generic RequestException raises WeatherAPIError"""
        mock_get.side_effect = requests.exceptions.RequestException("Generic error")

        with pytest.raises(WeatherAPIError) as exc_info:
            self.client._make_request_with_retry("http://test.com", {})

        assert exc_info.value.is_temporary is False


class TestGeocodeCityEdgeCases:
    """Additional tests for _geocode_city"""

    def test_geocode_with_empty_city_name(self):
        """Test geocoding with empty city name"""
        client = WeatherClient(api_key="test_key", city_name="")

        result = client._geocode_city()

        assert result is False
        assert client._coordinates_cached is True

    @patch.object(WeatherClient, 'search_cities')
    def test_geocode_caches_result(self, mock_search):
        """Test that geocoding result is cached"""
        mock_search.return_value = [{"lat": 51.5, "lon": -0.1}]

        client = WeatherClient(api_key="test_key", city_name="London")

        # First call
        result1 = client._geocode_city()
        # Second call should use cache
        result2 = client._geocode_city()

        assert result1 is True
        assert result2 is True
        # search_cities should only be called once
        mock_search.assert_called_once()

    @patch.object(WeatherClient, 'search_cities')
    def test_geocode_caches_failure(self, mock_search):
        """Test that geocoding failure is cached"""
        mock_search.return_value = []

        client = WeatherClient(api_key="test_key", city_name="NonexistentCity")

        # First call fails
        result1 = client._geocode_city()
        # Second call should use cached failure
        result2 = client._geocode_city()

        assert result1 is False
        assert result2 is False
        # search_cities should only be called once
        mock_search.assert_called_once()


class TestLegacyForecastTimezoneHandling:
    """Tests for timezone handling in legacy forecast parsing"""

    def test_parse_legacy_forecast_with_timezone(self):
        """Test that legacy forecast uses timezone offset correctly"""
        client = WeatherClient(api_key="test_key", city_name="Tokyo")
        client.latitude = 35.6762
        client.longitude = 139.6503

        # Tokyo is UTC+9 (32400 seconds)
        data = {
            "city": {"name": "Tokyo", "timezone": 32400},
            "list": [
                {
                    "dt": 1703203200,  # 2023-12-22 02:00 UTC (11:00 JST)
                    "main": {"temp": 10.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 10},
                    "pop": 0
                }
            ]
        }

        result = client._parse_legacy_forecast(data)

        assert result["success"] is True
        # Should have parsed the date in local time
        assert len(result["daily"]) >= 1

    def test_parse_legacy_forecast_negative_timezone(self):
        """Test legacy forecast with negative timezone (Americas)"""
        client = WeatherClient(api_key="test_key", city_name="New York")
        client.latitude = 40.7128
        client.longitude = -74.0060

        # New York is UTC-5 (-18000 seconds)
        data = {
            "city": {"name": "New York", "timezone": -18000},
            "list": [
                {
                    "dt": 1703203200,  # 2023-12-22 02:00 UTC (21:00 EST previous day)
                    "main": {"temp": 5.0},
                    "weather": [{"main": "Clouds"}],
                    "clouds": {"all": 40},
                    "pop": 0.1
                }
            ]
        }

        result = client._parse_legacy_forecast(data)

        assert result["success"] is True

    def test_parse_legacy_forecast_stores_hourly_data(self):
        """Test that legacy forecast stores hourly data for solar calculation"""
        client = WeatherClient(api_key="test_key", city_name="Sydney")
        client.latitude = -33.8688
        client.longitude = 151.2093

        data = {
            "city": {"name": "Sydney", "timezone": 36000},  # UTC+10
            "list": [
                {
                    "dt": 1703203200,
                    "main": {"temp": 25.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 10},
                    "pop": 0
                },
                {
                    "dt": 1703214000,
                    "main": {"temp": 28.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 15},
                    "pop": 0.1
                }
            ]
        }

        result = client._parse_legacy_forecast(data)

        # Check that hourly_data was cached
        assert "hourly_data" in client._cache
        assert len(client._cache["hourly_data"]) >= 1

    def test_parse_legacy_aggregates_conditions(self):
        """Test that legacy forecast aggregates conditions correctly"""
        client = WeatherClient(api_key="test_key", city_name="Test")
        client.latitude = 0
        client.longitude = 0

        # Same day, multiple conditions - most common should win
        data = {
            "city": {"name": "Test", "timezone": 0},
            "list": [
                {"dt": 1703203200, "main": {"temp": 20}, "weather": [{"main": "Clear"}], "clouds": {"all": 10}, "pop": 0},
                {"dt": 1703214000, "main": {"temp": 22}, "weather": [{"main": "Clear"}], "clouds": {"all": 15}, "pop": 0},
                {"dt": 1703224800, "main": {"temp": 21}, "weather": [{"main": "Rain"}], "clouds": {"all": 80}, "pop": 0.5},
                {"dt": 1703235600, "main": {"temp": 19}, "weather": [{"main": "Clear"}], "clouds": {"all": 20}, "pop": 0}
            ]
        }

        result = client._parse_legacy_forecast(data)

        # Clear appears 3 times, Rain once - Clear should be the main condition
        assert result["daily"][0]["condition"] == "Clear"


class TestWeatherAnalyserBadWeatherDetection:
    """Tests for bad weather detection in WeatherAnalyser"""

    def test_analyse_forecast_rain_is_bad(self):
        """Test that rain condition is detected as bad weather"""
        analyser = WeatherAnalyser(bad_conditions=["Rain"], min_cloud_cover=70)

        forecast = {
            "success": True,
            "daily": [
                {
                    "date": "2023-12-22",
                    "condition": "Rain",
                    "clouds": 90,
                    "pop": 80
                }
            ]
        }

        result = analyser.analyse_forecast(forecast)

        assert result["daily"][0]["is_bad_weather"] is True

    def test_analyse_forecast_clear_is_good(self):
        """Test that clear condition is detected as good weather"""
        analyser = WeatherAnalyser(bad_conditions=["Rain"], min_cloud_cover=70)

        forecast = {
            "success": True,
            "daily": [
                {
                    "date": "2023-12-22",
                    "condition": "Clear",
                    "clouds": 10,
                    "pop": 0
                }
            ]
        }

        result = analyser.analyse_forecast(forecast)

        assert result["daily"][0]["is_bad_weather"] is False

    def test_analyse_forecast_high_clouds_is_bad(self):
        """Test that high cloud cover triggers bad weather"""
        analyser = WeatherAnalyser(bad_conditions=["Rain"], min_cloud_cover=70)

        forecast = {
            "success": True,
            "daily": [
                {
                    "date": "2023-12-22",
                    "condition": "Clouds",
                    "clouds": 85,  # Above min_cloud_cover threshold
                    "pop": 20
                }
            ]
        }

        result = analyser.analyse_forecast(forecast)

        assert result["daily"][0]["is_bad_weather"] is True


class TestWeatherClientForbiddenResponse:
    """Tests for 403 Forbidden response handling"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(api_key="test_key", city_name="Sydney")
        self.client.latitude = -33.8688
        self.client.longitude = 151.2093
        self.client._coordinates_cached = True

    @patch('weather_client.requests.get')
    def test_forbidden_403_response(self, mock_get):
        """Test handling of 403 Forbidden response"""
        mock_response = Mock()
        mock_response.status_code = 403

        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "forbidden" in result["error"].lower()
        assert result.get("is_temporary") is False


class TestShouldSkipDischargeSingleDay:
    """Tests for should_skip_discharge with single day forecast"""

    def test_single_day_forecast_uses_today(self):
        """Test that single day forecast uses today for check"""
        analyser = WeatherAnalyser()

        forecast = {
            "success": True,
            "daily": [
                {"day_name": "Today", "estimated_solar_kwh": 3.0}
            ]
        }

        should_skip, reason = analyser.should_skip_discharge(forecast, min_solar_kwh=5.0)

        # Should skip because today's (only day) solar is below threshold
        assert should_skip is True
        assert "3.0" in reason


class TestWeatherClientNoCity:
    """Tests for WeatherClient with no city configured"""

    @patch('weather_client.requests.get')
    def test_get_forecast_no_city(self, mock_get):
        """Test get_forecast fails gracefully with no city"""
        client = WeatherClient(api_key="test_key", city_name="")

        result = client.get_forecast()

        assert result["success"] is False
        assert "could not geocode" in result["error"].lower()
