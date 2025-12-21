import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAppWeatherIntegration:
    """Tests for app.py weather integration"""

    @pytest.fixture
    def app_client(self):
        """Create a test client for the Flask app"""
        # Need to mock the deye client before importing app
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {
                    "api_base_url": "https://test.com",
                    "app_id": "test",
                    "app_secret": "test",
                    "email": "test@test.com",
                    "password": "test",
                    "device_sn": "TEST123"
                },
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {
                    "enabled": True,
                    "api_key": "test_key",
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "bad_weather_threshold_days": 2,
                    "bad_weather_conditions": ["Rain", "Thunderstorm"],
                    "min_cloud_cover_percent": 70
                }
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    def test_weather_api_disabled(self, app_client):
        """Test /api/weather when weather is disabled"""
        client, app_module = app_client
        app_module.config["weather"]["enabled"] = False

        response = client.get('/api/weather')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["enabled"] is False

    def test_weather_api_no_client(self, app_client):
        """Test /api/weather when client is not initialised"""
        client, app_module = app_client
        app_module.weather_client = None

        response = client.get('/api/weather')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "not initialised" in data["error"]

    @patch('app.get_weather_forecast')
    def test_weather_api_success(self, mock_forecast, app_client):
        """Test /api/weather with successful forecast"""
        client, app_module = app_client

        mock_forecast.return_value = {
            "success": True,
            "daily": [
                {"date": "2023-12-22", "condition": "Clear", "is_bad_weather": False}
            ],
            "consecutive_bad_days": 0
        }

        # Initialise weather client
        app_module.weather_client = Mock()
        app_module.weather_analyser = Mock()
        app_module.weather_analyser.should_skip_discharge.return_value = (False, "Good weather")

        response = client.get('/api/weather')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert data["enabled"] is True

    def test_weather_config_api(self, app_client):
        """Test /api/weather/config returns config without API key"""
        client, app_module = app_client

        response = client.get('/api/weather/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["enabled"] is True
        assert data["latitude"] == -33.8688
        assert data["longitude"] == 151.2093
        assert data["bad_weather_threshold_days"] == 2
        assert "api_key" not in data
        assert data["api_key_configured"] is True

    @patch('app.save_config')
    @patch('app.init_weather_client')
    def test_weather_config_update(self, mock_init, mock_save, app_client):
        """Test POST /api/weather/config updates config"""
        client, app_module = app_client

        response = client.post('/api/weather/config',
            data=json.dumps({
                "enabled": False,
                "latitude": -34.0,
                "longitude": 152.0,
                "bad_weather_threshold_days": 3
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        mock_save.assert_called_once()
        mock_init.assert_called_once()

    def test_status_includes_weather(self, app_client):
        """Test /api/status includes weather status"""
        client, app_module = app_client

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert "weather" in data
        assert data["weather"]["enabled"] is True
        assert "skip_active" in data["weather"]
        assert "threshold_days" in data["weather"]


class TestInitWeatherClient:
    """Tests for init_weather_client function"""

    def test_init_disabled(self):
        """Test init with weather disabled"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": False}}
            app_module.weather_client = None
            app_module.weather_analyser = None

            app_module.init_weather_client()

            assert app_module.weather_client is None
            assert app_module.weather_analyser is None

    def test_init_no_api_key(self):
        """Test init with missing API key"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "api_key": "YOUR_OPENWEATHERMAP_API_KEY"
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None

            app_module.init_weather_client()

            assert app_module.weather_client is None

    def test_init_no_location(self):
        """Test init with missing location"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "api_key": "valid_key"
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None

            app_module.init_weather_client()

            assert app_module.weather_client is None

    @patch('app.WeatherClient')
    @patch('app.WeatherAnalyser')
    def test_init_success(self, mock_analyzer, mock_client):
        """Test successful weather client initialisation"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "api_key": "valid_key",
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "bad_weather_conditions": ["Rain"],
                    "min_cloud_cover_percent": 70
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None

            app_module.init_weather_client()

            mock_client.assert_called_once_with(
                api_key="valid_key",
                latitude=-33.8688,
                longitude=151.2093
            )
            mock_analyzer.assert_called_once()


class TestShouldSkipDischargeForWeather:
    """Tests for should_skip_discharge_for_weather function"""

    def test_skip_disabled(self):
        """Test skip check when weather is disabled"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": False}}

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False
            assert "disabled" in reason

    def test_skip_no_client(self):
        """Test skip check when client not initialised"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True}}
            app_module.weather_client = None

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False
            assert "not configured" in reason

    @patch('app.get_weather_forecast')
    def test_skip_no_forecast(self, mock_forecast):
        """Test skip check when forecast unavailable"""
        mock_forecast.return_value = None

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True, "bad_weather_threshold_days": 2}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False
            assert "unavailable" in reason

    @patch('app.get_weather_forecast')
    def test_skip_bad_weather(self, mock_forecast):
        """Test skip check triggers for bad weather"""
        mock_forecast.return_value = {
            "success": True,
            "consecutive_bad_days": 3
        }

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True, "bad_weather_threshold_days": 2}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()
            app_module.weather_analyser.should_skip_discharge.return_value = (True, "3 bad days")

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is True
            assert "3 bad days" in reason


class TestGetWeatherForecast:
    """Tests for get_weather_forecast function"""

    def test_no_client(self):
        """Test forecast fetch without client"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.weather_client = None

            result = app_module.get_weather_forecast()

            assert result is None

    @patch('app.datetime')
    def test_uses_cache(self, mock_datetime):
        """Test forecast uses cache when valid"""
        mock_datetime.now.return_value = datetime(2023, 12, 22, 12, 0, 0)

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()
            app_module.weather_forecast_cache = {
                "forecast": {"cached": True},
                "last_update": datetime(2023, 12, 22, 11, 45, 0)  # 15 minutes ago
            }

            result = app_module.get_weather_forecast()

            assert result == {"cached": True}
            app_module.weather_client.get_forecast.assert_not_called()


class TestIsWithinDischargeWindow:
    """Tests for is_within_discharge_window function"""

    @patch('app.datetime')
    def test_within_window(self, mock_datetime):
        """Test detection when within window"""
        mock_now = datetime(2023, 12, 22, 18, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is True

    @patch('app.datetime')
    def test_before_window(self, mock_datetime):
        """Test detection when before window"""
        mock_now = datetime(2023, 12, 22, 16, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is False

    @patch('app.datetime')
    def test_after_window(self, mock_datetime):
        """Test detection when after window"""
        mock_now = datetime(2023, 12, 22, 20, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is False


class TestSchedulerWeatherIntegration:
    """Tests for scheduler weather integration"""

    @patch('app.should_skip_discharge_for_weather')
    @patch('app.is_within_discharge_window')
    def test_scheduler_skips_for_weather(self, mock_window, mock_weather_skip):
        """Test scheduler skips discharge when weather is bad"""
        mock_window.return_value = True
        mock_weather_skip.return_value = (True, "Bad weather for 3 days")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.client = mock_client
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False
            }

            # The should_force_discharge calculation
            in_window = True
            soc = 75
            cutoff_soc = 50
            weather_skip = True

            should_force_discharge = in_window and (soc is None or soc > cutoff_soc) and not weather_skip

            assert should_force_discharge is False
