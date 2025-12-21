import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import requests

from weather_client import WeatherClient, WeatherAnalyser


class TestWeatherClient:
    """Tests for WeatherClient class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = WeatherClient(
            api_key="test_api_key",
            latitude=-33.8688,
            longitude=151.2093
        )

    def test_init(self):
        """Test WeatherClient initialization"""
        assert self.client.api_key == "test_api_key"
        assert self.client.latitude == -33.8688
        assert self.client.longitude == 151.2093
        assert self.client.base_url == "https://api.openweathermap.org/data/2.5"
        assert self.client._cache == {}
        assert self.client._cache_time is None

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
    def test_get_forecast_onecall_success(self, mock_get):
        """Test successful forecast fetch using One Call API"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "timezone": "Australia/Sydney",
            "current": {
                "temp": 25.5,
                "weather": [{"main": "Clear", "description": "clear sky"}],
                "clouds": 10
            },
            "daily": [
                {
                    "dt": 1703203200,
                    "temp": {"min": 18.0, "max": 28.0},
                    "weather": [{"main": "Clear", "description": "clear sky", "icon": "01d"}],
                    "clouds": 10,
                    "pop": 0,
                    "rain": 0,
                    "uvi": 8.5
                },
                {
                    "dt": 1703289600,
                    "temp": {"min": 20.0, "max": 30.0},
                    "weather": [{"main": "Rain", "description": "light rain", "icon": "10d"}],
                    "clouds": 80,
                    "pop": 0.7,
                    "rain": 5.2,
                    "uvi": 4.0
                }
            ]
        }
        mock_get.return_value = mock_response

        result = self.client.get_forecast()

        assert result["success"] is True
        assert result["location"] == "Australia/Sydney"
        assert len(result["daily"]) == 2
        assert result["daily"][0]["condition"] == "Clear"
        assert result["daily"][1]["condition"] == "Rain"

    @patch('weather_client.requests.get')
    def test_get_forecast_fallback_to_legacy(self, mock_get):
        """Test fallback to legacy API when One Call fails"""
        # First call fails with 401
        mock_response_fail = Mock()
        mock_response_fail.status_code = 401

        # Second call succeeds with legacy API
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.raise_for_status = Mock()
        mock_response_success.json.return_value = {
            "city": {"name": "Sydney"},
            "list": [
                {
                    "dt": 1703203200,
                    "main": {"temp": 25.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 10},
                    "pop": 0,
                    "rain": {}
                },
                {
                    "dt": 1703214000,
                    "main": {"temp": 28.0},
                    "weather": [{"main": "Clear"}],
                    "clouds": {"all": 15},
                    "pop": 0.1,
                    "rain": {}
                }
            ]
        }

        mock_get.side_effect = [mock_response_fail, mock_response_success]

        result = self.client.get_forecast()

        assert result["success"] is True
        assert result["location"] == "Sydney"

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
        assert result["location"] == "Test/Zone"
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
        assert result["location"] == "TestCity"
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
                {"condition": "Rain", "clouds": 80, "pop": 70},
                {"condition": "Clear", "clouds": 10, "pop": 5},
                {"condition": "Thunderstorm", "clouds": 95, "pop": 90}
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

    def test_should_skip_discharge_yes(self):
        """Test skip discharge when bad weather exceeds threshold"""
        forecast = {
            "success": True,
            "consecutive_bad_days": 3,
            "bad_weather_days": ["2023-12-22", "2023-12-23", "2023-12-24"],
            "daily": [
                {"is_bad_weather": True},
                {"is_bad_weather": True},
                {"is_bad_weather": True}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, threshold_days=2)

        assert should_skip is True
        assert "3 days" in reason

    def test_should_skip_discharge_no(self):
        """Test no skip when good weather"""
        forecast = {
            "success": True,
            "consecutive_bad_days": 1,
            "bad_weather_days": ["2023-12-22"],
            "daily": [
                {"is_bad_weather": True},
                {"is_bad_weather": False},
                {"is_bad_weather": False}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, threshold_days=2)

        assert should_skip is False
        assert "Good weather" in reason

    def test_should_skip_discharge_threshold_match(self):
        """Test skip when bad days exactly match threshold"""
        forecast = {
            "success": True,
            "consecutive_bad_days": 2,
            "bad_weather_days": ["2023-12-22", "2023-12-23"],
            "daily": [
                {"is_bad_weather": True},
                {"is_bad_weather": True},
                {"is_bad_weather": False}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, threshold_days=2)

        assert should_skip is True

    def test_should_skip_discharge_failed_forecast(self):
        """Test skip check with failed forecast"""
        forecast = {"success": False, "error": "API error"}

        should_skip, reason = self.analyser.should_skip_discharge(forecast, threshold_days=2)

        assert should_skip is False
        assert "unavailable" in reason

    def test_should_skip_discharge_non_consecutive_bad_days(self):
        """Test skip when non-consecutive bad days exceed threshold in window"""
        forecast = {
            "success": True,
            "consecutive_bad_days": 0,
            "bad_weather_days": [],
            "daily": [
                {"is_bad_weather": True},
                {"is_bad_weather": True},
                {"is_bad_weather": False}
            ]
        }

        should_skip, reason = self.analyser.should_skip_discharge(forecast, threshold_days=2)

        assert should_skip is True
        assert "2 bad weather days" in reason


class TestWeatherClientEdgeCases:
    """Edge case tests for WeatherClient"""

    def test_empty_daily_forecast(self):
        """Test handling of empty daily forecast"""
        client = WeatherClient("key", 0, 0)
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
        client = WeatherClient("key", 0, 0)
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
        client = WeatherClient("key", 0, 0)
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
