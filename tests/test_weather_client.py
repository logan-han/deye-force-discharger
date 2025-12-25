import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import requests

from weather_client import WeatherClient, WeatherAnalyser, SolarForecastClient, WeatherAPIError


class TestWeatherClient:
    """Tests for WeatherClient class (Open-Meteo API)"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            latitude=-33.8688,
            longitude=151.2093,
            timezone_str="Australia/Sydney"
        )

    def test_init(self):
        """Test WeatherClient initialization"""
        client = WeatherClient(latitude=-33.8688, longitude=151.2093)
        assert client.latitude == -33.8688
        assert client.longitude == 151.2093
        assert client.timezone_str == "auto"
        assert client.base_url == "https://api.open-meteo.com/v1/forecast"
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
    def test_get_forecast_success(self, mock_get):
        """Test successful forecast fetch using Open-Meteo API"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "daily": {
                "time": ["2023-12-22", "2023-12-23"],
                "temperature_2m_max": [28.0, 25.0],
                "temperature_2m_min": [18.0, 16.0],
                "weather_code": [0, 61],
                "precipitation_sum": [0.0, 5.2],
                "precipitation_probability_max": [10, 80]
            },
            "hourly": {
                "time": ["2023-12-22T09:00", "2023-12-22T12:00", "2023-12-22T15:00"],
                "cloud_cover": [10, 15, 20],
                "precipitation_probability": [0, 5, 10],
                "weather_code": [0, 1, 2]
            }
        }
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is True
        assert len(result["daily"]) >= 1
        assert result["daily"][0]["condition"] == "Clear"

    @patch('weather_client.requests.get')
    def test_get_forecast_api_error(self, mock_get):
        """Test error handling when API returns 400"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"reason": "Invalid coordinates"}

        mock_get.return_value = mock_response

        result = self.client.get_forecast()

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

    def test_weather_code_to_condition_clear(self):
        """Test weather code 0 returns Clear"""
        assert self.client._weather_code_to_condition(0) == "Clear"

    def test_weather_code_to_condition_clouds(self):
        """Test weather codes 1-3 return Clouds"""
        assert self.client._weather_code_to_condition(1) == "Clouds"
        assert self.client._weather_code_to_condition(2) == "Clouds"
        assert self.client._weather_code_to_condition(3) == "Clouds"

    def test_weather_code_to_condition_rain(self):
        """Test weather codes 61-65 return Rain"""
        assert self.client._weather_code_to_condition(61) == "Rain"
        assert self.client._weather_code_to_condition(63) == "Rain"
        assert self.client._weather_code_to_condition(65) == "Rain"

    def test_weather_code_to_condition_thunderstorm(self):
        """Test weather codes 95-99 return Thunderstorm"""
        assert self.client._weather_code_to_condition(95) == "Thunderstorm"
        assert self.client._weather_code_to_condition(96) == "Thunderstorm"
        assert self.client._weather_code_to_condition(99) == "Thunderstorm"


class TestWeatherClientCitySearch:
    """Tests for city search functionality (Open-Meteo Geocoding)"""

    @patch('weather_client.requests.get')
    def test_search_cities_success(self, mock_get):
        """Test successful city search"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "name": "Sydney",
                    "country": "Australia",
                    "admin1": "New South Wales",
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney"
                },
                {
                    "name": "Sydney",
                    "country": "Canada",
                    "admin1": "Nova Scotia",
                    "latitude": 46.1368,
                    "longitude": -60.1942,
                    "timezone": "America/Halifax"
                }
            ]
        }
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("Sydney")

        assert len(result) == 2
        assert result[0]["name"] == "Sydney"
        assert result[0]["country"] == "Australia"
        assert result[0]["display_name"] == "Sydney, New South Wales, Australia"
        assert result[0]["timezone"] == "Australia/Sydney"

    @patch('weather_client.requests.get')
    def test_search_cities_no_state(self, mock_get):
        """Test city search when state is not present"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "name": "London",
                    "country": "United Kingdom",
                    "latitude": 51.5074,
                    "longitude": -0.1278
                }
            ]
        }
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("London")

        assert len(result) == 1
        assert result[0]["display_name"] == "London, United Kingdom"

    def test_search_cities_short_query(self):
        """Test city search with query less than 2 characters"""
        result = WeatherClient.search_cities("A")
        assert result == []

    def test_search_cities_empty_query(self):
        """Test city search with empty query"""
        result = WeatherClient.search_cities("")
        assert result == []

    @patch('weather_client.requests.get')
    def test_search_cities_api_error(self, mock_get):
        """Test city search when API fails"""
        mock_get.side_effect = Exception("API error")

        result = WeatherClient.search_cities("Sydney")

        assert result == []

    @patch('weather_client.requests.get')
    def test_search_cities_no_results(self, mock_get):
        """Test city search with no results"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        result = WeatherClient.search_cities("NonexistentCity12345")

        assert result == []


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


class TestSolarForecastClient:
    """Tests for SolarForecastClient (forecast.solar API)"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = SolarForecastClient(
            latitude=-33.8688,
            longitude=151.2093,
            declination=35,
            azimuth=0,
            kwp=6.6
        )

    def test_init(self):
        """Test SolarForecastClient initialization"""
        client = SolarForecastClient(
            latitude=-33.8688,
            longitude=151.2093,
            declination=35,
            azimuth=0,
            kwp=6.6
        )
        assert client.latitude == -33.8688
        assert client.longitude == 151.2093
        assert client.declination == 35
        assert client.azimuth == 0
        assert client.kwp == 6.6
        assert client.base_url == "https://api.forecast.solar"

    @patch('weather_client.requests.get')
    def test_get_forecast_success(self, mock_get):
        """Test successful solar forecast fetch"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "watt_hours_day": {
                    "2023-12-22": 25000,
                    "2023-12-23": 22000
                },
                "watts": {},
                "watt_hours": {}
            },
            "message": {
                "code": 0,
                "type": "success",
                "ratelimit": {"remaining": 10}
            }
        }
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is True
        assert len(result["daily"]) == 2
        assert result["daily"][0]["estimated_kwh"] == 25.0
        assert result["daily"][1]["estimated_kwh"] == 22.0

    @patch('weather_client.requests.get')
    def test_get_forecast_rate_limited(self, mock_get):
        """Test handling of rate limit error"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is False
        assert "rate limit" in result["error"].lower()
        assert result["is_temporary"] is True

    @patch('weather_client.requests.get')
    def test_get_forecast_invalid_location(self, mock_get):
        """Test handling of invalid location error"""
        mock_response = Mock()
        mock_response.status_code = 422
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is False
        assert result["is_temporary"] is False

    @patch('weather_client.requests.get')
    def test_get_forecast_uses_cache(self, mock_get):
        """Test that forecast uses cache when valid"""
        self.client._cache["forecast"] = {"success": True, "daily": []}
        self.client._cache_time = datetime.now()

        result = self.client.get_forecast()

        mock_get.assert_not_called()
        assert result == {"success": True, "daily": []}

    @patch('weather_client.requests.get')
    def test_get_daily_estimate(self, mock_get):
        """Test getting daily estimate for specific date"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "watt_hours_day": {
                    "2023-12-22": 25000,
                    "2023-12-23": 22000
                },
                "watts": {},
                "watt_hours": {}
            },
            "message": {}
        }
        mock_get.return_value = mock_response

        result = self.client.get_daily_estimate("2023-12-22")

        assert result == 25.0


class TestWeatherClientSolarEstimates:
    """Tests for weather-based solar output estimation"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            latitude=-33.8688,
            longitude=151.2093
        )

    def test_hourly_estimate_no_cache(self):
        """Test hourly estimate returns None when no cache"""
        self.client._cache = {}

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is None

    def test_hourly_estimate_clear_day(self):
        """Test hourly estimate for clear day"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 6, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 7, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 8, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 9, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 10, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 11, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 12, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 13, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 14, "clouds": 5, "condition": "Clear", "pop": 0},
                    {"hour": 15, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 16, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 17, "clouds": 10, "condition": "Clear", "pop": 0},
                    {"hour": 18, "clouds": 15, "condition": "Clear", "pop": 0}
                ]
            }
        }

        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")

        assert result is not None
        assert result > 15  # Clear day should have good output

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
            latitude=-33.8688,
            longitude=151.2093
        )

    @patch('weather_client.requests.get')
    def test_connection_timeout(self, mock_get):
        """Test handling of connection timeout"""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = self.client.get_forecast()

        assert result["success"] is False
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    def test_dns_resolution_failure(self, mock_get):
        """Test handling of DNS resolution failure"""
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "Failed to establish a new connection: [Errno -2] Name or service not known"
        )

        result = self.client.get_forecast()

        assert result["success"] is False
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
        assert result.get("is_temporary") is True
        # Should have retried
        assert mock_get.call_count >= 2

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_server_error_recovery(self, mock_sleep, mock_get):
        """Test recovery after transient server error"""
        mock_response_fail = Mock()
        mock_response_fail.status_code = 503

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {
            "daily": {"time": [], "temperature_2m_max": [], "temperature_2m_min": [], "weather_code": [], "precipitation_sum": [], "precipitation_probability_max": []},
            "hourly": {"time": [], "cloud_cover": [], "precipitation_probability": [], "weather_code": []}
        }

        mock_get.side_effect = [mock_response_fail, mock_response_success]

        result = self.client.get_forecast()

        assert result["success"] is True


class TestWeatherAnalyserWithSolarClient:
    """Tests for WeatherAnalyser with SolarForecastClient integration"""

    def setup_method(self):
        """Set up test fixtures"""
        self.analyser = WeatherAnalyser(
            bad_conditions=["Rain", "Thunderstorm"],
            min_cloud_cover=70
        )

    def test_analyse_forecast_uses_solar_client(self):
        """Test that analyse_forecast uses solar client when available"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5},
                {"date": "2023-12-23", "condition": "Rain", "clouds": 90, "pop": 80}
            ]
        }

        # Create a mock solar client
        mock_solar_client = Mock()
        mock_solar_client.get_forecast.return_value = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "estimated_kwh": 25.0},
                {"date": "2023-12-23", "estimated_kwh": 8.0}
            ]
        }

        result = self.analyser.analyse_forecast(
            forecast,
            solar_client=mock_solar_client
        )

        assert result["daily"][0]["estimated_solar_kwh"] == 25.0
        assert result["daily"][0]["solar_source"] == "forecast.solar"
        assert result["daily"][1]["estimated_solar_kwh"] == 8.0

    def test_analyse_forecast_falls_back_to_weather_estimate(self):
        """Test that analyse_forecast falls back to weather estimate when solar client unavailable"""
        forecast = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}
            ]
        }

        # Create a mock weather client with hourly data
        mock_weather_client = Mock()
        mock_weather_client.estimate_solar_output_hourly.return_value = 20.0

        result = self.analyser.analyse_forecast(
            forecast,
            panel_capacity_kw=5.0,
            weather_client=mock_weather_client
        )

        assert result["daily"][0]["estimated_solar_kwh"] == 20.0
        assert result["daily"][0]["solar_source"] == "weather_estimate"


class TestWeatherClientAdditionalCoverage:
    """Additional tests for WeatherClient to achieve full coverage"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            latitude=-33.8688,
            longitude=151.2093,
            timezone_str="Australia/Sydney"
        )

    def test_weather_code_to_condition_fog(self):
        """Test weather codes 45, 48 return Fog"""
        assert self.client._weather_code_to_condition(45) == "Fog"
        assert self.client._weather_code_to_condition(48) == "Fog"

    def test_weather_code_to_condition_drizzle(self):
        """Test weather codes 51-57 return Drizzle"""
        assert self.client._weather_code_to_condition(51) == "Drizzle"
        assert self.client._weather_code_to_condition(53) == "Drizzle"
        assert self.client._weather_code_to_condition(55) == "Drizzle"
        assert self.client._weather_code_to_condition(56) == "Drizzle"  # Freezing drizzle
        assert self.client._weather_code_to_condition(57) == "Drizzle"

    def test_weather_code_to_condition_freezing_rain(self):
        """Test weather codes 66, 67 return Rain (freezing rain)"""
        assert self.client._weather_code_to_condition(66) == "Rain"
        assert self.client._weather_code_to_condition(67) == "Rain"

    def test_weather_code_to_condition_snow(self):
        """Test weather codes 71-77, 85, 86 return Snow"""
        assert self.client._weather_code_to_condition(71) == "Snow"
        assert self.client._weather_code_to_condition(73) == "Snow"
        assert self.client._weather_code_to_condition(75) == "Snow"
        assert self.client._weather_code_to_condition(77) == "Snow"
        assert self.client._weather_code_to_condition(85) == "Snow"
        assert self.client._weather_code_to_condition(86) == "Snow"

    def test_weather_code_to_condition_showers(self):
        """Test weather codes 80-82 return Rain (showers)"""
        assert self.client._weather_code_to_condition(80) == "Rain"
        assert self.client._weather_code_to_condition(81) == "Rain"
        assert self.client._weather_code_to_condition(82) == "Rain"

    def test_weather_code_to_condition_unknown(self):
        """Test unknown weather code returns Clouds"""
        assert self.client._weather_code_to_condition(999) == "Clouds"

    def test_condition_to_icon(self):
        """Test icon mapping for all conditions"""
        assert self.client._condition_to_icon("Clear") == "01d"
        assert self.client._condition_to_icon("Clouds") == "03d"
        assert self.client._condition_to_icon("Rain") == "10d"
        assert self.client._condition_to_icon("Drizzle") == "09d"
        assert self.client._condition_to_icon("Thunderstorm") == "11d"
        assert self.client._condition_to_icon("Snow") == "13d"
        assert self.client._condition_to_icon("Fog") == "50d"
        assert self.client._condition_to_icon("Unknown") == "01d"  # Default fallback

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_rate_limit_429_with_retry(self, mock_sleep, mock_get):
        """Test handling of 429 rate limit with retry"""
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "5"}

        mock_response_ok = Mock()
        mock_response_ok.status_code = 200
        mock_response_ok.raise_for_status = Mock()
        mock_response_ok.json.return_value = {
            "daily": {"time": [], "temperature_2m_max": [], "temperature_2m_min": [], "weather_code": [], "precipitation_sum": [], "precipitation_probability_max": []},
            "hourly": {"time": [], "cloud_cover": [], "precipitation_probability": [], "weather_code": []}
        }

        mock_get.side_effect = [mock_response_429, mock_response_ok]

        result = self.client.get_forecast()
        assert result["success"] is True

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_rate_limit_429_all_retries_exhausted(self, mock_sleep, mock_get):
        """Test 429 rate limit when all retries are exhausted"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_get.return_value = mock_response

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_connection_refused_error(self, mock_sleep, mock_get):
        """Test handling of connection refused error"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result.get("is_temporary") is True

    @patch('weather_client.requests.get')
    @patch('weather_client.time.sleep')
    def test_generic_connection_error_with_retry(self, mock_sleep, mock_get):
        """Test handling of generic connection error with retry"""
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("Random network error"),
            requests.exceptions.ConnectionError("Random network error"),
            requests.exceptions.ConnectionError("Random network error")
        ]

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result.get("is_temporary") is True

    def test_estimate_solar_output_no_date_data(self):
        """Test hourly solar estimate when date has no data"""
        self.client._cache = {"hourly_data": {"2023-12-22": []}}
        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-23")
        assert result is None

    def test_estimate_solar_output_empty_hourly_data(self):
        """Test hourly solar estimate with empty hourly data for date"""
        self.client._cache = {"hourly_data": {"2023-12-22": []}}
        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is None

    def test_estimate_solar_output_latitude_ranges(self):
        """Test hourly solar estimate for different latitude ranges"""
        hourly_data = [
            {"hour": h, "clouds": 10, "condition": "Clear", "pop": 0}
            for h in range(6, 19)
        ]

        # Test equatorial (lat < 15)
        client = WeatherClient(latitude=10, longitude=100)
        client._cache = {"hourly_data": {"2023-12-22": hourly_data}}
        result = client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is not None and result > 20

        # Test tropical (15 <= lat < 25)
        client = WeatherClient(latitude=20, longitude=100)
        client._cache = {"hourly_data": {"2023-12-22": hourly_data}}
        result = client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is not None

        # Test temperate (35 <= lat < 45)
        client = WeatherClient(latitude=40, longitude=100)
        client._cache = {"hourly_data": {"2023-12-22": hourly_data}}
        result = client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is not None

        # Test high latitude (lat >= 45)
        client = WeatherClient(latitude=50, longitude=100)
        client._cache = {"hourly_data": {"2023-12-22": hourly_data}}
        result = client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is not None

    def test_estimate_solar_output_bad_conditions(self):
        """Test hourly solar estimate with various bad weather conditions"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 9, "clouds": 50, "condition": "Thunderstorm", "pop": 80},
                    {"hour": 12, "clouds": 60, "condition": "Snow", "pop": 70},
                    {"hour": 15, "clouds": 70, "condition": "Fog", "pop": 40}
                ]
            }
        }
        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")
        assert result is not None
        assert result < 10  # Should be low due to bad conditions

    def test_estimate_solar_output_nighttime_hours_ignored(self):
        """Test that nighttime hours are not counted in solar estimate"""
        self.client._cache = {
            "hourly_data": {
                "2023-12-22": [
                    {"hour": 0, "clouds": 0, "condition": "Clear", "pop": 0},
                    {"hour": 3, "clouds": 0, "condition": "Clear", "pop": 0},
                    {"hour": 5, "clouds": 0, "condition": "Clear", "pop": 0},
                    {"hour": 19, "clouds": 0, "condition": "Clear", "pop": 0},
                    {"hour": 22, "clouds": 0, "condition": "Clear", "pop": 0},
                ]
            }
        }
        result = self.client.estimate_solar_output_hourly(5.0, "2023-12-22")
        # Should return None because no daylight hours in data
        assert result is None


class TestSolarForecastClientAdditionalCoverage:
    """Additional tests for SolarForecastClient"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = SolarForecastClient(
            latitude=-33.8688,
            longitude=151.2093,
            kwp=6.6
        )

    def test_init_auto_tilt_and_azimuth(self):
        """Test auto-calculation of tilt and azimuth"""
        # Southern hemisphere (should face north, azimuth=0)
        client = SolarForecastClient(latitude=-33.8688, longitude=151.2093, kwp=5.0)
        assert client.declination == 25  # Default optimal tilt
        assert client.azimuth == 0  # North-facing for southern hemisphere

        # Northern hemisphere (should face south, azimuth=180)
        client = SolarForecastClient(latitude=40.7128, longitude=-74.0060, kwp=5.0)
        assert client.azimuth == 180  # South-facing for northern hemisphere

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
    def test_get_forecast_bad_request_400(self, mock_get):
        """Test handling of 400 bad request error"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": {"text": "Bad request"}}
        mock_get.return_value = mock_response

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result["is_temporary"] is False

    @patch('weather_client.requests.get')
    def test_get_forecast_timeout(self, mock_get):
        """Test handling of request timeout"""
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result["is_temporary"] is True

    @patch('weather_client.requests.get')
    def test_get_forecast_request_exception(self, mock_get):
        """Test handling of generic request exception"""
        mock_get.side_effect = requests.exceptions.RequestException("Network error")

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result["is_temporary"] is True

    @patch('weather_client.requests.get')
    def test_get_forecast_unexpected_exception(self, mock_get):
        """Test handling of unexpected exception"""
        mock_get.side_effect = ValueError("Unexpected error")

        result = self.client.get_forecast()
        assert result["success"] is False
        assert result["is_temporary"] is False

    @patch('weather_client.requests.get')
    def test_get_daily_estimate_forecast_fails(self, mock_get):
        """Test get_daily_estimate when forecast fetch fails"""
        mock_get.side_effect = requests.exceptions.Timeout()

        result = self.client.get_daily_estimate("2023-12-22")
        assert result is None

    @patch('weather_client.requests.get')
    def test_get_daily_estimate_date_not_found(self, mock_get):
        """Test get_daily_estimate when date is not in forecast"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {"watt_hours_day": {"2023-12-22": 25000}, "watts": {}, "watt_hours": {}},
            "message": {}
        }
        mock_get.return_value = mock_response

        result = self.client.get_daily_estimate("2023-12-25")  # Date not in response
        assert result is None

    @patch('weather_client.requests.get')
    def test_get_daily_estimate_default_tomorrow(self, mock_get):
        """Test get_daily_estimate defaults to tomorrow"""
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {"watt_hours_day": {tomorrow: 30000}, "watts": {}, "watt_hours": {}},
            "message": {}
        }
        mock_get.return_value = mock_response

        result = self.client.get_daily_estimate()  # No date specified
        assert result == 30.0


class TestWeatherAnalyserAdditionalCoverage:
    """Additional tests for WeatherAnalyser"""

    def setup_method(self):
        """Set up test fixtures"""
        self.analyser = WeatherAnalyser()

    def test_analyse_forecast_unsuccessful(self):
        """Test analyse_forecast with unsuccessful forecast"""
        forecast = {"success": False, "error": "API error"}
        result = self.analyser.analyse_forecast(forecast)
        assert result["success"] is False

    def test_analyse_forecast_empty_daily(self):
        """Test analyse_forecast with empty daily array"""
        forecast = {"success": True, "daily": []}
        result = self.analyser.analyse_forecast(forecast)
        assert result["daily"] == []

    def test_analyse_forecast_solar_client_fails(self):
        """Test analyse_forecast falls back when solar client fails"""
        forecast = {
            "success": True,
            "daily": [{"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}]
        }

        mock_solar_client = Mock()
        mock_solar_client.get_forecast.return_value = {"success": False}

        result = self.analyser.analyse_forecast(
            forecast,
            solar_client=mock_solar_client
        )

        assert result["daily"][0].get("has_solar_prediction") is False

    def test_analyse_forecast_weather_estimate_returns_none(self):
        """Test analyse_forecast when weather estimate returns None"""
        forecast = {
            "success": True,
            "daily": [{"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}]
        }

        mock_weather_client = Mock()
        mock_weather_client.estimate_solar_output_hourly.return_value = None

        result = self.analyser.analyse_forecast(
            forecast,
            panel_capacity_kw=5.0,
            weather_client=mock_weather_client
        )

        assert result["daily"][0]["has_solar_prediction"] is False

    def test_analyse_forecast_no_solar_prediction_available(self):
        """Test analyse_forecast without any solar prediction source"""
        forecast = {
            "success": True,
            "daily": [{"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}]
        }

        result = self.analyser.analyse_forecast(forecast)

        assert result["daily"][0]["has_solar_prediction"] is False
        assert result["daily"][0]["estimated_solar_kwh"] is None

    def test_analyse_forecast_bad_weather_based_on_solar(self):
        """Test bad weather detection based on solar threshold"""
        forecast = {
            "success": True,
            "daily": [{"date": "2023-12-22", "condition": "Clear", "clouds": 10, "pop": 5}]
        }

        mock_solar_client = Mock()
        mock_solar_client.get_forecast.return_value = {
            "success": True,
            "daily": [{"date": "2023-12-22", "estimated_kwh": 3.0}]  # Below threshold
        }

        result = self.analyser.analyse_forecast(
            forecast,
            solar_client=mock_solar_client,
            min_solar_threshold=10.0
        )

        assert result["daily"][0]["is_bad_weather"] is True

    def test_should_skip_discharge_unsuccessful_forecast(self):
        """Test should_skip_discharge with unsuccessful forecast"""
        forecast = {"success": False}
        should_skip, reason = self.analyser.should_skip_discharge(forecast)
        assert should_skip is False
        assert "unavailable" in reason

    def test_should_skip_discharge_no_threshold(self):
        """Test should_skip_discharge without threshold"""
        forecast = {"success": True, "daily": [{"estimated_solar_kwh": 5.0}]}
        should_skip, reason = self.analyser.should_skip_discharge(forecast)
        assert should_skip is False
        assert "not configured" in reason

    def test_should_skip_discharge_zero_threshold(self):
        """Test should_skip_discharge with zero threshold"""
        forecast = {"success": True, "daily": [{"estimated_solar_kwh": 5.0}]}
        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=0)
        assert should_skip is False

    def test_should_skip_discharge_no_solar_prediction(self):
        """Test should_skip_discharge when solar prediction not available"""
        forecast = {
            "success": True,
            "daily": [{"day_name": "Today"}, {"day_name": "Tomorrow", "estimated_solar_kwh": None}]
        }
        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=10.0)
        assert should_skip is False
        assert "not available" in reason

    def test_should_skip_discharge_single_day_forecast(self):
        """Test should_skip_discharge with only today in forecast"""
        forecast = {
            "success": True,
            "daily": [{"day_name": "Today", "estimated_solar_kwh": 5.0}]
        }
        should_skip, reason = self.analyser.should_skip_discharge(forecast, min_solar_kwh=10.0)
        assert should_skip is True  # Falls back to today when no tomorrow

    def test_is_bad_weather_drizzle(self):
        """Test bad weather detection for drizzle"""
        day = {"condition": "Drizzle", "clouds": 50, "pop": 30}
        assert self.analyser._is_bad_weather_day(day) is True

    def test_is_bad_weather_snow(self):
        """Test bad weather detection for snow"""
        day = {"condition": "Snow", "clouds": 50, "pop": 30}
        assert self.analyser._is_bad_weather_day(day) is True


class TestWeatherClientParseForecast:
    """Tests for _parse_forecast function edge cases"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(latitude=-33.8688, longitude=151.2093)

    def test_parse_forecast_handles_missing_hourly_data(self):
        """Test parsing handles missing hourly data gracefully"""
        data = {
            "daily": {
                "time": ["2023-12-22"],
                "temperature_2m_max": [28.0],
                "temperature_2m_min": [18.0],
                "weather_code": [0],
                "precipitation_sum": [0.0],
                "precipitation_probability_max": [10]
            },
            "hourly": {
                "time": [],
                "cloud_cover": [],
                "precipitation_probability": [],
                "weather_code": []
            }
        }

        result = self.client._parse_forecast(data)
        assert result["success"] is True
        assert len(result["daily"]) == 1

    def test_parse_forecast_handles_partial_hourly_data(self):
        """Test parsing handles partial hourly data"""
        data = {
            "daily": {
                "time": ["2023-12-22"],
                "temperature_2m_max": [28.0],
                "temperature_2m_min": [18.0],
                "weather_code": [0],
                "precipitation_sum": [0.0],
                "precipitation_probability_max": [10]
            },
            "hourly": {
                "time": ["2023-12-22T12:00"],
                "cloud_cover": [],  # Shorter than time array
                "precipitation_probability": [],
                "weather_code": []
            }
        }

        result = self.client._parse_forecast(data)
        assert result["success"] is True

    def test_parse_forecast_limits_to_4_days(self):
        """Test parsing limits forecast to 4 days"""
        data = {
            "daily": {
                "time": ["2023-12-22", "2023-12-23", "2023-12-24", "2023-12-25", "2023-12-26", "2023-12-27"],
                "temperature_2m_max": [28.0, 27.0, 26.0, 25.0, 24.0, 23.0],
                "temperature_2m_min": [18.0, 17.0, 16.0, 15.0, 14.0, 13.0],
                "weather_code": [0, 1, 2, 3, 4, 5],
                "precipitation_sum": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "precipitation_probability_max": [10, 20, 30, 40, 50, 60]
            },
            "hourly": {"time": [], "cloud_cover": [], "precipitation_probability": [], "weather_code": []}
        }

        result = self.client._parse_forecast(data)
        assert len(result["daily"]) == 4
