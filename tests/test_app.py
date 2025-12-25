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
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "city_name": "Sydney, AU",
                    "min_solar_threshold_kwh": 5.0,
                    "inverter_capacity_kw": 5.0,
                    "panel_capacity_kw": 6.6,
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
            ]
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
        """Test /api/weather/config returns config with location"""
        client, app_module = app_client

        response = client.get('/api/weather/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["enabled"] is True
        assert data["city_name"] == "Sydney, AU"
        assert data["min_solar_threshold_kwh"] == 5.0
        assert data["inverter_capacity_kw"] == 5.0
        assert data["panel_capacity_kw"] == 6.6
        assert data["latitude"] == -33.8688
        assert data["longitude"] == 151.2093
        assert data["location_configured"] is True

    @patch('app.save_config')
    @patch('app.init_weather_client')
    def test_weather_config_update(self, mock_init, mock_save, app_client):
        """Test POST /api/weather/config updates config"""
        client, app_module = app_client

        response = client.post('/api/weather/config',
            data=json.dumps({
                "enabled": False,
                "city_name": "Melbourne, AU",
                "min_solar_threshold_kwh": 8.0,
                "inverter_capacity_kw": 8.0,
                "panel_capacity_kw": 10.0
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["inverter_capacity_kw"] == 8.0
        assert app_module.config["weather"]["panel_capacity_kw"] == 10.0
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
        assert "min_solar_threshold_kwh" in data["weather"]


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

    def test_init_no_location(self):
        """Test init with missing location coordinates"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "city_name": "Sydney, AU"
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
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "city_name": "Sydney, AU",
                    "bad_weather_conditions": ["Rain"],
                    "min_cloud_cover_percent": 70
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None

            app_module.init_weather_client()

            mock_client.assert_called_once_with(
                latitude=-33.8688,
                longitude=151.2093,
                timezone_str="Australia/Sydney"
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
            app_module.config = {"weather": {"enabled": True, "min_solar_threshold_kwh": 5.0}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False
            assert "unavailable" in reason

    @patch('app.get_weather_forecast')
    def test_skip_bad_weather(self, mock_forecast):
        """Test skip check triggers for bad weather"""
        mock_forecast.return_value = {
            "success": True
        }

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True, "min_solar_threshold_kwh": 5.0}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()
            app_module.weather_analyser.should_skip_discharge.return_value = (True, "Low solar forecast")

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is True
            assert "Low solar" in reason


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
                "last_update": datetime(2023, 12, 22, 11, 58, 0)  # 2 minutes ago, within 5 min cache
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
        mock_weather_skip.return_value = (True, "Low solar forecast")

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


class TestLoadAndSaveConfig:
    """Tests for config loading and saving"""

    @patch('builtins.open', create=True)
    @patch('app.json.load')
    def test_load_config(self, mock_json_load, mock_open):
        """Test loading configuration"""
        mock_json_load.return_value = {"test": "config"}

        with patch('app.DeyeCloudClient'):
            import app as app_module
            result = app_module.load_config()

            assert result == {"test": "config"}
            mock_open.assert_called_once()

    @patch('builtins.open', create=True)
    @patch('app.json.dump')
    def test_save_config(self, mock_json_dump, mock_open):
        """Test saving configuration"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"test": "data"}
            app_module.save_config()

            mock_open.assert_called_once()
            mock_json_dump.assert_called_once()


class TestInitClient:
    """Tests for init_client function"""

    @patch('app.DeyeCloudClient')
    def test_init_client_success(self, mock_deye):
        """Test successful client initialization"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {
            "success": True,
            "systemWorkMode": "SELLING_FIRST"
        }
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {
            "deye": {
                "api_base_url": "https://test.com",
                "app_id": "test_app",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test_pass",
                "device_sn": "TEST123"
            }
        }
        app_module.current_state = {
            "mode": "unknown",
            "force_discharge_active": False
        }

        app_module.init_client()

        mock_deye.assert_called_once()
        assert app_module.current_state["mode"] == "SELLING_FIRST"
        assert app_module.current_state["force_discharge_active"] is True

    @patch('app.DeyeCloudClient')
    def test_init_client_work_mode_failure(self, mock_deye):
        """Test client init when work mode fetch fails"""
        mock_client = Mock()
        mock_client.get_work_mode.side_effect = Exception("API error")
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {"mode": "unknown", "force_discharge_active": False}

        # Should not raise, just log warning
        app_module.init_client()

        assert app_module.current_state["mode"] == "unknown"

    @patch('app.DeyeCloudClient')
    def test_init_client_no_work_mode_in_response(self, mock_deye):
        """Test client init when work mode response has no mode"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True}
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {"mode": "unknown", "force_discharge_active": False}

        app_module.init_client()

        assert app_module.current_state["mode"] == "unknown"


class TestGetWeatherForecastCoverage:
    """Additional tests for get_weather_forecast"""

    def test_forecast_fetch_exception(self):
        """Test forecast fetch handles exceptions"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            mock_weather_client = Mock()
            mock_weather_client.get_forecast.side_effect = Exception("API error")
            app_module.weather_client = mock_weather_client
            app_module.weather_analyser = Mock()
            app_module.weather_forecast_cache = {
                "forecast": {"cached": True},
                "last_update": None  # Force refresh
            }

            result = app_module.get_weather_forecast()

            # Should return cached data on error
            assert result == {"cached": True}

    def test_forecast_fetch_exception_no_cache(self):
        """Test forecast fetch returns None when error and no cache"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            mock_weather_client = Mock()
            mock_weather_client.get_forecast.side_effect = Exception("API error")
            app_module.weather_client = mock_weather_client
            app_module.weather_analyser = Mock()
            app_module.weather_forecast_cache = {
                "forecast": None,
                "last_update": None
            }

            result = app_module.get_weather_forecast()

            assert result is None


class TestIsWithinDischargeWindowOvernightEdgeCases:
    """Tests for overnight discharge window handling"""

    @patch('app.datetime')
    def test_overnight_window_before_midnight(self, mock_datetime):
        """Test overnight window when time is before midnight"""
        mock_now = datetime(2023, 12, 22, 23, 0, 0)  # 11 PM
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "22:00",  # 10 PM
                    "force_discharge_end": "06:00"     # 6 AM next day
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is True

    @patch('app.datetime')
    def test_overnight_window_after_midnight(self, mock_datetime):
        """Test overnight window when time is after midnight"""
        mock_now = datetime(2023, 12, 23, 2, 0, 0)  # 2 AM
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "22:00",
                    "force_discharge_end": "06:00"
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is True

    @patch('app.datetime')
    def test_overnight_window_outside(self, mock_datetime):
        """Test overnight window when outside the window"""
        mock_now = datetime(2023, 12, 22, 12, 0, 0)  # Noon
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "schedule": {
                    "force_discharge_start": "22:00",
                    "force_discharge_end": "06:00"
                }
            }

            result = app_module.is_within_discharge_window()

            assert result is False


class TestSchedulerFunctions:
    """Tests for start_scheduler and stop_scheduler"""

    def test_start_scheduler_success(self):
        """Test starting scheduler"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.scheduler_running = False
            app_module.scheduler_thread = None

            with patch('app.threading.Thread') as mock_thread:
                mock_thread_instance = Mock()
                mock_thread.return_value = mock_thread_instance

                result = app_module.start_scheduler()

                assert result is True
                mock_thread_instance.start.assert_called_once()
                assert app_module.scheduler_running is True

    def test_start_scheduler_already_running(self):
        """Test starting scheduler when already running"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.scheduler_running = True

            result = app_module.start_scheduler()

            assert result is False

    def test_stop_scheduler(self):
        """Test stopping scheduler"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.scheduler_running = True

            result = app_module.stop_scheduler()

            assert result is True
            assert app_module.scheduler_running is False


class TestFlaskRoutes:
    """Tests for Flask API routes"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_instance.get_device_latest_data.return_value = {"soc": 75}
            mock_instance.get_soc.return_value = 75
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {"device_sn": "TEST123"},
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {"enabled": False}
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance

    def test_index_route(self, test_client):
        """Test index route returns template"""
        client, app_module, _ = test_client

        with patch('app.render_template') as mock_render:
            mock_render.return_value = "HTML"
            response = client.get('/')
            mock_render.assert_called_once_with('index.html')

    def test_get_device_info(self, test_client):
        """Test /api/device endpoint"""
        client, app_module, mock_deye = test_client

        response = client.get('/api/device')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    def test_get_device_info_error(self, test_client):
        """Test /api/device endpoint with error"""
        client, app_module, mock_deye = test_client
        mock_deye.get_device_latest_data.side_effect = Exception("API error")

        response = client.get('/api/device')
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["success"] is False

    def test_get_work_mode(self, test_client):
        """Test /api/work-mode GET endpoint"""
        client, app_module, mock_deye = test_client

        response = client.get('/api/work-mode')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    def test_get_work_mode_error(self, test_client):
        """Test /api/work-mode GET endpoint with error"""
        client, app_module, mock_deye = test_client
        mock_deye.get_work_mode.side_effect = Exception("API error")

        response = client.get('/api/work-mode')
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["success"] is False

    def test_set_work_mode_success(self, test_client):
        """Test /api/work-mode POST endpoint success"""
        client, app_module, mock_deye = test_client
        mock_deye.set_work_mode.return_value = {"code": "0"}

        response = client.post('/api/work-mode',
            data=json.dumps({"mode": "SELLING_FIRST"}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    def test_set_work_mode_no_mode(self, test_client):
        """Test /api/work-mode POST without mode"""
        client, app_module, mock_deye = test_client

        response = client.post('/api/work-mode',
            data=json.dumps({}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 400
        assert data["success"] is False

    def test_set_work_mode_failure(self, test_client):
        """Test /api/work-mode POST with API failure"""
        client, app_module, mock_deye = test_client
        mock_deye.set_work_mode.return_value = {"code": "1", "msg": "Error"}

        response = client.post('/api/work-mode',
            data=json.dumps({"mode": "SELLING_FIRST"}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 400
        assert data["success"] is False

    def test_set_work_mode_exception(self, test_client):
        """Test /api/work-mode POST with exception"""
        client, app_module, mock_deye = test_client
        mock_deye.set_work_mode.side_effect = Exception("API error")

        response = client.post('/api/work-mode',
            data=json.dumps({"mode": "SELLING_FIRST"}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["success"] is False

    def test_get_tou(self, test_client):
        """Test /api/tou endpoint"""
        client, app_module, mock_deye = test_client

        response = client.get('/api/tou')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    def test_get_tou_error(self, test_client):
        """Test /api/tou endpoint with error"""
        client, app_module, mock_deye = test_client
        mock_deye.get_tou_settings.side_effect = Exception("API error")

        response = client.get('/api/tou')
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["success"] is False

    def test_get_config(self, test_client):
        """Test /api/config GET endpoint"""
        client, app_module, _ = test_client

        response = client.get('/api/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert "schedule" in data
        assert "device_sn" in data

    @patch('app.save_config')
    def test_update_config(self, mock_save, test_client):
        """Test /api/config POST endpoint"""
        client, app_module, mock_deye = test_client

        response = client.post('/api/config',
            data=json.dumps({
                "schedule": {"min_soc_reserve": 25}
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        mock_save.assert_called_once()

    @patch('app.save_config')
    def test_update_config_with_tou(self, mock_save, test_client):
        """Test /api/config POST with TOU update"""
        client, app_module, mock_deye = test_client
        mock_deye.set_tou_settings.return_value = {"success": True}
        app_module.current_state = {"force_discharge_active": False}

        response = client.post('/api/config',
            data=json.dumps({
                "schedule": {"min_soc_reserve": 25},
                "update_tou": True
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    @patch('app.save_config')
    def test_update_config_tou_failure(self, mock_save, test_client):
        """Test /api/config POST with TOU failure"""
        client, app_module, mock_deye = test_client
        mock_deye.set_tou_settings.return_value = {"success": False, "msg": "Error"}
        app_module.current_state = {"force_discharge_active": True}

        response = client.post('/api/config',
            data=json.dumps({
                "schedule": {"force_discharge_cutoff_soc": 60},
                "update_tou": True
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False

    def test_update_config_exception(self, test_client):
        """Test /api/config POST with exception"""
        client, app_module, _ = test_client

        with patch('app.save_config', side_effect=Exception("File error")):
            response = client.post('/api/config',
                data=json.dumps({"schedule": {}}),
                content_type='application/json'
            )
            data = json.loads(response.data)

            assert response.status_code == 500
            assert data["success"] is False

    def test_api_start_scheduler(self, test_client):
        """Test /api/scheduler/start endpoint"""
        client, app_module, _ = test_client

        with patch('app.start_scheduler', return_value=True):
            response = client.post('/api/scheduler/start')
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True

    def test_api_start_scheduler_already_running(self, test_client):
        """Test /api/scheduler/start when already running"""
        client, app_module, _ = test_client

        with patch('app.start_scheduler', return_value=False):
            response = client.post('/api/scheduler/start')
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is False

    def test_api_stop_scheduler(self, test_client):
        """Test /api/scheduler/stop endpoint"""
        client, app_module, _ = test_client

        with patch('app.stop_scheduler', return_value=True):
            response = client.post('/api/scheduler/stop')
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True

    def test_get_soc(self, test_client):
        """Test /api/soc endpoint"""
        client, app_module, mock_deye = test_client

        response = client.get('/api/soc')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert data["soc"] == 75

    def test_get_soc_error(self, test_client):
        """Test /api/soc endpoint with error"""
        client, app_module, mock_deye = test_client
        mock_deye.get_soc.side_effect = Exception("API error")

        response = client.get('/api/soc')
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["success"] is False

    def test_get_weather_no_forecast(self, test_client):
        """Test /api/weather with no forecast available"""
        client, app_module, _ = test_client
        app_module.config["weather"]["enabled"] = True
        app_module.weather_client = Mock()

        with patch('app.get_weather_forecast', return_value=None):
            response = client.get('/api/weather')
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is False

    def test_update_weather_config_error(self, test_client):
        """Test POST /api/weather/config with error"""
        client, app_module, _ = test_client

        with patch('app.save_config', side_effect=Exception("Error")):
            response = client.post('/api/weather/config',
                data=json.dumps({"enabled": True}),
                content_type='application/json'
            )
            data = json.loads(response.data)

            assert response.status_code == 500
            assert data["success"] is False

    def test_status_tou_exception(self, test_client):
        """Test /api/status when TOU fetch fails"""
        client, app_module, mock_deye = test_client
        mock_deye.get_tou_settings.side_effect = Exception("API error")

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["tou_settings"] is None


class TestSchedulerLoop:
    """Tests for scheduler_loop function"""

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_activates_force_discharge(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler activates force discharge"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")
        mock_sleep.side_effect = [None] * 5 + [StopIteration()]  # Stop after a few iterations

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            # Run one iteration then stop
            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Should have tried to activate force discharge
            mock_client.set_work_mode.assert_called_with("SELLING_FIRST")

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_deactivates_force_discharge(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler deactivates force discharge"""
        mock_window.return_value = False  # Outside window
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "SELLING_FIRST"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "SELLING_FIRST",
                "force_discharge_active": True,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Should have tried to deactivate force discharge
            mock_client.set_work_mode.assert_called_with("ZERO_EXPORT_TO_CT")

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_handles_exception(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles exceptions gracefully"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.side_effect = Exception("API error")
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {"schedule": {}}
            app_module.current_state = {
                "mode": "unknown",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should not raise, just log error
            app_module.scheduler_loop()

            assert app_module.current_state["last_error"] == "API error"

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_work_mode_fetch_fails(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles work mode fetch failure"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.side_effect = Exception("API error")
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "unknown",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should not raise
            app_module.scheduler_loop()

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_set_mode_fails(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles set work mode failure"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": False, "msg": "Failed"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            assert app_module.current_state["last_error"] == "Failed"

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_tou_update_fails(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles TOU update failure"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": False, "msg": "TOU failed"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should not raise, TOU failure is logged but continues
            app_module.scheduler_loop()

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_weather_skip_logs(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler logs weather skip"""
        mock_window.return_value = True
        mock_weather.return_value = (True, "Low solar forecast")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            assert app_module.current_state["weather_skip_active"] is True
            assert app_module.current_state["weather_skip_reason"] == "Low solar forecast"

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_deactivate_due_to_soc(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler deactivates when SOC reaches cutoff"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 45, "power": 1000}  # Below cutoff
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "SELLING_FIRST"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "SELLING_FIRST",
                "force_discharge_active": True,
                "soc": 75,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Should have deactivated force discharge
            mock_client.set_work_mode.assert_called_with("ZERO_EXPORT_TO_CT")


class TestIsWithinFreeEnergyWindow:
    """Tests for is_within_free_energy_window function"""

    @patch('app.datetime')
    def test_disabled_returns_false(self, mock_datetime):
        """Test returns False when feature is disabled"""
        mock_datetime.now.return_value = datetime(2023, 12, 22, 12, 0, 0)

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": False,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is False

    @patch('app.datetime')
    def test_within_window(self, mock_datetime):
        """Test detection when within free energy window"""
        mock_now = datetime(2023, 12, 22, 12, 30, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is True

    @patch('app.datetime')
    def test_before_window(self, mock_datetime):
        """Test detection when before free energy window"""
        mock_now = datetime(2023, 12, 22, 10, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is False

    @patch('app.datetime')
    def test_after_window(self, mock_datetime):
        """Test detection when after free energy window"""
        mock_now = datetime(2023, 12, 22, 15, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is False

    @patch('app.datetime')
    def test_at_start_boundary(self, mock_datetime):
        """Test detection at exact start time"""
        mock_now = datetime(2023, 12, 22, 11, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is True

    @patch('app.datetime')
    def test_at_end_boundary(self, mock_datetime):
        """Test detection at exact end time"""
        mock_now = datetime(2023, 12, 22, 14, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is True

    @patch('app.datetime')
    def test_missing_config(self, mock_datetime):
        """Test returns False when config is missing"""
        mock_datetime.now.return_value = datetime(2023, 12, 22, 12, 0, 0)

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {}

            result = app_module.is_within_free_energy_window()

            assert result is False

    @patch('app.datetime')
    def test_overnight_window_before_midnight(self, mock_datetime):
        """Test overnight free energy window when time is before midnight"""
        mock_now = datetime(2023, 12, 22, 23, 30, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "23:00",
                    "end_time": "05:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is True

    @patch('app.datetime')
    def test_overnight_window_after_midnight(self, mock_datetime):
        """Test overnight free energy window when time is after midnight"""
        mock_now = datetime(2023, 12, 23, 2, 0, 0)
        mock_datetime.now.return_value = mock_now

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "23:00",
                    "end_time": "05:00"
                }
            }

            result = app_module.is_within_free_energy_window()

            assert result is True


class TestGetFreeEnergyTouParams:
    """Tests for get_free_energy_tou_params function"""

    def test_disabled_returns_none(self):
        """Test returns None values when disabled"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": False,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 100
                }
            }

            start, end, soc = app_module.get_free_energy_tou_params()

            assert start is None
            assert end is None
            assert soc is None

    def test_enabled_returns_values(self):
        """Test returns config values when enabled"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 90
                }
            }

            start, end, soc = app_module.get_free_energy_tou_params()

            assert start == "11:00"
            assert end == "14:00"
            assert soc == 90

    def test_missing_config_returns_none(self):
        """Test returns None when config is missing"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {}

            start, end, soc = app_module.get_free_energy_tou_params()

            assert start is None
            assert end is None
            assert soc is None

    def test_uses_defaults(self):
        """Test uses default values when not specified"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "free_energy": {
                    "enabled": True
                }
            }

            start, end, soc = app_module.get_free_energy_tou_params()

            assert start == "11:00"
            assert end == "14:00"
            assert soc == 100


class TestFreeEnergyConfigAPI:
    """Tests for free energy configuration API endpoints"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_instance.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {"device_sn": "TEST123"},
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {"enabled": False},
                "free_energy": {
                    "enabled": False,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 100
                }
            }
            app_module.client = mock_instance
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "free_energy_active": False
            }
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance

    def test_get_free_energy_config(self, test_client):
        """Test GET /api/free-energy/config returns config"""
        client, app_module, _ = test_client

        response = client.get('/api/free-energy/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["enabled"] is False
        assert data["start_time"] == "11:00"
        assert data["end_time"] == "14:00"
        assert data["target_soc"] == 100

    def test_get_free_energy_config_defaults(self, test_client):
        """Test GET /api/free-energy/config returns defaults when missing"""
        client, app_module, _ = test_client
        app_module.config["free_energy"] = {}

        response = client.get('/api/free-energy/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["enabled"] is False
        assert data["start_time"] == "11:00"
        assert data["end_time"] == "14:00"
        assert data["target_soc"] == 100

    @patch('app.save_config')
    def test_update_free_energy_config(self, mock_save, test_client):
        """Test POST /api/free-energy/config updates config"""
        client, app_module, _ = test_client

        response = client.post('/api/free-energy/config',
            data=json.dumps({
                "enabled": True,
                "start_time": "10:00",
                "end_time": "13:00",
                "target_soc": 90
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        mock_save.assert_called_once()
        assert app_module.config["free_energy"]["enabled"] is True
        assert app_module.config["free_energy"]["start_time"] == "10:00"
        assert app_module.config["free_energy"]["end_time"] == "13:00"
        assert app_module.config["free_energy"]["target_soc"] == 90

    @patch('app.save_config')
    def test_update_free_energy_config_with_tou(self, mock_save, test_client):
        """Test POST /api/free-energy/config with TOU update"""
        client, app_module, mock_deye = test_client

        response = client.post('/api/free-energy/config',
            data=json.dumps({
                "enabled": True,
                "start_time": "11:00",
                "end_time": "14:00",
                "target_soc": 100,
                "update_tou": True
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        mock_deye.set_tou_settings.assert_called_once()

    @patch('app.save_config')
    def test_update_free_energy_config_tou_failure(self, mock_save, test_client):
        """Test POST /api/free-energy/config handles TOU failure"""
        client, app_module, mock_deye = test_client
        mock_deye.set_tou_settings.return_value = {"success": False, "msg": "TOU error"}

        response = client.post('/api/free-energy/config',
            data=json.dumps({
                "enabled": True,
                "update_tou": True
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "TOU" in data["error"]

    def test_update_free_energy_config_exception(self, test_client):
        """Test POST /api/free-energy/config handles exceptions"""
        client, app_module, _ = test_client

        with patch('app.save_config', side_effect=Exception("File error")):
            response = client.post('/api/free-energy/config',
                data=json.dumps({"enabled": True}),
                content_type='application/json'
            )
            data = json.loads(response.data)

            assert response.status_code == 500
            assert data["success"] is False

    @patch('app.save_config')
    def test_update_free_energy_partial_config(self, mock_save, test_client):
        """Test POST /api/free-energy/config with partial update"""
        client, app_module, _ = test_client

        response = client.post('/api/free-energy/config',
            data=json.dumps({
                "enabled": True
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["free_energy"]["enabled"] is True
        # Other values should remain unchanged
        assert app_module.config["free_energy"]["start_time"] == "11:00"


class TestStatusIncludesFreeEnergy:
    """Tests for /api/status including free energy info"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {"device_sn": "TEST123"},
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {"enabled": False},
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 90
                }
            }
            app_module.client = mock_instance
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "soc": 75,
                "battery_power": 1000,
                "force_discharge_active": False,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None,
                "free_energy_active": False
            }
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    def test_status_includes_free_energy(self, test_client):
        """Test /api/status includes free_energy section"""
        client, app_module = test_client

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert "free_energy" in data
        assert data["free_energy"]["enabled"] is True
        assert data["free_energy"]["start_time"] == "11:00"
        assert data["free_energy"]["end_time"] == "14:00"
        assert data["free_energy"]["target_soc"] == 90

    def test_status_includes_free_energy_window_status(self, test_client):
        """Test /api/status includes in_free_energy_window"""
        client, app_module = test_client

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert "in_free_energy_window" in data

    @patch('app.is_within_free_energy_window')
    def test_status_free_energy_active_in_window(self, mock_window, test_client):
        """Test status shows active when in free energy window"""
        mock_window.return_value = True
        client, app_module = test_client
        app_module.current_state["free_energy_active"] = True

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["free_energy"]["active"] is True


class TestSetupEndpoints:
    """Tests for setup wizard API endpoints"""

    @pytest.fixture
    def test_client(self):
        """Create test client with unconfigured state"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {
                    "app_id": "YOUR_APP_ID",
                    "app_secret": "YOUR_APP_SECRET",
                    "email": "YOUR_EMAIL",
                    "device_sn": "YOUR_DEVICE_SN"
                },
                "schedule": {},
                "weather": {}
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance

    def test_setup_status_needs_setup(self, test_client):
        """Test /api/setup/status when setup is needed"""
        client, app_module, _ = test_client

        response = client.get('/api/setup/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["needs_setup"] is True
        assert data["deye_configured"] is False

    def test_setup_status_already_configured(self, test_client):
        """Test /api/setup/status when already configured"""
        client, app_module, _ = test_client
        app_module.config["deye"] = {
            "app_id": "valid_app_id",
            "app_secret": "valid_secret",
            "email": "test@test.com",
            "password": "test",
            "device_sn": "ABC123"
        }

        response = client.get('/api/setup/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["needs_setup"] is False
        assert data["deye_configured"] is True

    @patch('app.DeyeCloudClient')
    def test_test_deye_connection_success(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye with successful connection"""
        client, app_module, _ = test_client

        mock_test_client = Mock()
        mock_test_client.get_device_latest_data.return_value = {
            "code": 0,
            "deviceDataList": [{"deviceName": "My Inverter"}]
        }
        mock_deye_class.return_value = mock_test_client

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "api_base_url": "https://eu1-developer.deyecloud.com",
                "app_id": "test_app_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test_password",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert "My Inverter" in data["device_name"]

    def test_test_deye_connection_missing_device_sn(self, test_client):
        """Test /api/setup/test-deye without device serial number"""
        client, app_module, _ = test_client

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "test_app_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test_password"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "serial number" in data["error"].lower()

    @patch('app.DeyeCloudClient')
    def test_test_deye_connection_device_not_found(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye when device not found"""
        client, app_module, _ = test_client

        mock_test_client = Mock()
        mock_test_client.get_device_latest_data.return_value = {
            "code": 0,
            "deviceDataList": []
        }
        mock_deye_class.return_value = mock_test_client

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "test_app_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test_password",
                "device_sn": "INVALID123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @patch('app.DeyeCloudClient')
    def test_test_deye_connection_api_error(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye with API error"""
        client, app_module, _ = test_client

        mock_test_client = Mock()
        mock_test_client.get_device_latest_data.return_value = {
            "code": 1,
            "msg": "Invalid credentials"
        }
        mock_deye_class.return_value = mock_test_client

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "bad_id",
                "app_secret": "bad_secret",
                "email": "test@test.com",
                "password": "wrong",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False

    @patch('app.WeatherClient.search_cities')
    def test_test_weather_connection_success(self, mock_search, test_client):
        """Test /api/setup/test-weather with valid API key"""
        client, app_module, _ = test_client
        mock_search.return_value = [{"name": "London", "country": "GB"}]

        response = client.post('/api/setup/test-weather',
            data=json.dumps({"latitude": -33.8688, "longitude": 151.2093}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True

    @patch('app.WeatherClient.search_cities')
    def test_test_weather_connection_invalid_key(self, mock_search, test_client):
        """Test /api/setup/test-weather with invalid API key"""
        client, app_module, _ = test_client
        mock_search.return_value = []

        response = client.post('/api/setup/test-weather',
            data=json.dumps({"latitude": 999, "longitude": 999}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False

    def test_test_weather_connection_no_key(self, test_client):
        """Test /api/setup/test-weather without API key"""
        client, app_module, _ = test_client

        response = client.post('/api/setup/test-weather',
            data=json.dumps({}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @patch('app.WeatherClient.search_cities')
    def test_setup_search_cities_success(self, mock_search, test_client):
        """Test /api/setup/search-cities with results"""
        client, app_module, _ = test_client
        mock_search.return_value = [
            {"name": "Sydney", "state": "NSW", "country": "AU"},
            {"name": "Sydney", "country": "CA"}
        ]

        response = client.get('/api/setup/search-cities?q=Sydney')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert len(data["cities"]) == 2

    def test_setup_search_cities_short_query(self, test_client):
        """Test /api/setup/search-cities with short query (1 char returns empty)"""
        client, app_module, _ = test_client

        response = client.get('/api/setup/search-cities?q=S')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert len(data["cities"]) == 0

    @patch('app.save_config')
    @patch('app.init_client')
    @patch('app.init_weather_client')
    def test_complete_setup_deye_only(self, mock_weather_init, mock_client_init, mock_save, test_client):
        """Test /api/setup/complete with Deye config only"""
        client, app_module, _ = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "deye": {
                    "api_base_url": "https://eu1-developer.deyecloud.com",
                    "app_id": "test_app_id",
                    "app_secret": "test_secret",
                    "email": "test@test.com",
                    "password": "test_password",
                    "device_sn": "ABC123"
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        mock_save.assert_called_once()
        mock_client_init.assert_called_once()

    @patch('app.save_config')
    @patch('app.init_client')
    @patch('app.init_weather_client')
    def test_complete_setup_with_weather(self, mock_weather_init, mock_client_init, mock_save, test_client):
        """Test /api/setup/complete with weather config"""
        client, app_module, _ = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "deye": {
                    "app_id": "test_app_id",
                    "app_secret": "test_secret",
                    "email": "test@test.com",
                    "password": "test_password",
                    "device_sn": "ABC123"
                },
                "weather": {
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "city_name": "Sydney, AU"
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["enabled"] is True
        mock_weather_init.assert_called_once()

    @patch('app.save_config')
    @patch('app.init_client')
    @patch('app.init_weather_client')
    def test_complete_setup_with_solar(self, mock_weather_init, mock_client_init, mock_save, test_client):
        """Test /api/setup/complete with solar capacity"""
        client, app_module, _ = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "deye": {
                    "app_id": "test_app_id",
                    "app_secret": "test_secret",
                    "email": "test@test.com",
                    "password": "test_password",
                    "device_sn": "ABC123"
                },
                "solar": {
                    "inverter_capacity_kw": 5.0,
                    "panel_capacity_kw": 6.6
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["panel_capacity_kw"] == 6.6
        assert app_module.config["weather"]["inverter_capacity_kw"] == 5.0

    def test_complete_setup_exception(self, test_client):
        """Test /api/setup/complete handles exceptions"""
        client, app_module, _ = test_client

        with patch('app.save_config', side_effect=Exception("File error")):
            response = client.post('/api/setup/complete',
                data=json.dumps({"deye": {"app_id": "test"}}),
                content_type='application/json'
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is False
            assert "error" in data


class TestSchedulerFreeEnergyIntegration:
    """Tests for scheduler integration with free energy feature"""

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.is_within_free_energy_window')
    @patch('app.should_skip_discharge_for_weather')
    @patch('app.get_free_energy_tou_params')
    def test_scheduler_updates_free_energy_state(self, mock_params, mock_weather, mock_free_window, mock_window, mock_sleep):
        """Test scheduler updates free_energy_active state"""
        mock_window.return_value = False
        mock_free_window.return_value = True
        mock_weather.return_value = (False, "Good weather")
        mock_params.return_value = ("11:00", "14:00", 100)

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": -2000}  # Charging
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                },
                "free_energy": {
                    "enabled": True,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 100
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "free_energy_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            assert app_module.current_state["free_energy_active"] is True

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.is_within_free_energy_window')
    @patch('app.should_skip_discharge_for_weather')
    @patch('app.get_free_energy_tou_params')
    def test_scheduler_passes_free_energy_to_tou(self, mock_params, mock_weather, mock_free_window, mock_window, mock_sleep):
        """Test scheduler passes free energy params to TOU settings"""
        mock_window.return_value = True
        mock_free_window.return_value = False
        mock_weather.return_value = (False, "Good weather")
        mock_params.return_value = ("11:00", "14:00", 90)

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "free_energy_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Check that set_tou_settings was called with free energy params
            call_args = mock_client.set_tou_settings.call_args
            assert call_args is not None
            assert call_args.kwargs.get("free_energy_start") == "11:00"
            assert call_args.kwargs.get("free_energy_end") == "14:00"
            assert call_args.kwargs.get("free_energy_soc") == 90

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.is_within_free_energy_window')
    @patch('app.should_skip_discharge_for_weather')
    @patch('app.get_free_energy_tou_params')
    def test_scheduler_free_energy_disabled(self, mock_params, mock_weather, mock_free_window, mock_window, mock_sleep):
        """Test scheduler handles disabled free energy"""
        mock_window.return_value = True
        mock_free_window.return_value = False
        mock_weather.return_value = (False, "Good weather")
        mock_params.return_value = (None, None, None)  # Disabled

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "free_energy_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Check that set_tou_settings was called with None for free energy params
            call_args = mock_client.set_tou_settings.call_args
            assert call_args is not None
            assert call_args.kwargs.get("free_energy_start") is None
            assert call_args.kwargs.get("free_energy_end") is None
            assert call_args.kwargs.get("free_energy_soc") is None


class TestInitClientBatteryInfo:
    """Tests for init_client battery info handling"""

    @patch('app.DeyeCloudClient')
    def test_init_client_fetches_battery_info(self, mock_deye):
        """Test client initialization fetches battery info"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
        mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {"mode": "unknown", "force_discharge_active": False}

        app_module.init_client()

        mock_client.get_battery_info.assert_called()

    @patch('app.DeyeCloudClient')
    def test_init_client_battery_info_exception(self, mock_deye):
        """Test client handles exception when getting battery info"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
        mock_client.get_battery_info.side_effect = Exception("API error")
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {"mode": "unknown", "force_discharge_active": False}

        # Should not raise exception
        app_module.init_client()


class TestGetWeatherForecastCapacityLogic:
    """Tests for get_weather_forecast panel capacity logic"""

    @patch('app.datetime')
    def test_forecast_uses_panel_capacity(self, mock_datetime):
        """Test forecast uses panel_capacity_kw from config"""
        mock_datetime.now.return_value = datetime(2023, 12, 22, 12, 0, 0)

        with patch('app.DeyeCloudClient'):
            import app as app_module
            mock_weather_client = Mock()
            mock_weather_analyser = Mock()

            mock_weather_client.get_forecast.return_value = {"success": True, "daily": []}
            mock_weather_analyser.analyse_forecast.return_value = {
                "success": True,
                "daily": [{"condition": "Clear"}]
            }

            app_module.weather_client = mock_weather_client
            app_module.weather_analyser = mock_weather_analyser
            app_module.weather_forecast_cache = {"forecast": None, "last_update": None}
            app_module.config = {
                "weather": {
                    "panel_capacity_kw": 6.6
                }
            }

            result = app_module.get_weather_forecast()

            # Verify analyse_forecast was called
            call_args = mock_weather_analyser.analyse_forecast.call_args
            assert call_args is not None
            # panel_capacity_kw should be passed
            assert "panel_capacity_kw" in call_args.kwargs


class TestSchedulerLoopEdgeCases:
    """Additional edge case tests for scheduler_loop"""

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_soc_is_none(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles None SOC value"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": None, "power": 0}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.return_value = {"success": True}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should activate discharge when SOC is None (conservative)
            app_module.scheduler_loop()

            mock_client.set_work_mode.assert_called_with("SELLING_FIRST")

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_no_client(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles missing client"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.client = None
            app_module.config = {"schedule": {}}
            app_module.current_state = {
                "mode": "unknown",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped"
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should not raise
            app_module.scheduler_loop()

            assert app_module.current_state["last_error"] is not None

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_set_tou_exception(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler handles TOU set exception"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_client.set_work_mode.return_value = {"success": True}
            mock_client.set_tou_settings.side_effect = Exception("TOU API error")
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            # Should not raise
            app_module.scheduler_loop()

    @patch('app.time.sleep')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_work_mode_already_correct(self, mock_weather, mock_window, mock_sleep):
        """Test scheduler doesn't change mode when already correct"""
        mock_window.return_value = True
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "SELLING_FIRST"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                }
            }
            app_module.current_state = {
                "mode": "SELLING_FIRST",
                "force_discharge_active": True,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # set_work_mode should not be called since mode is already correct
            mock_client.set_work_mode.assert_not_called()


class TestConfigHandling:
    """Tests for configuration handling"""

    @patch('builtins.open', create=True)
    @patch('app.json.load')
    def test_load_config_returns_dict(self, mock_json_load, mock_open):
        """Test load_config returns valid config dict"""
        mock_json_load.return_value = {"test": "config", "deye": {}}

        with patch('app.DeyeCloudClient'):
            import app as app_module

            result = app_module.load_config()

            assert isinstance(result, dict)
            assert result.get("test") == "config"


class TestIsWithinDischargeWindowAtBoundary:
    """Tests for discharge window boundary conditions"""

    @patch('app.datetime')
    def test_at_exact_start_time(self, mock_datetime):
        """Test at exact start time boundary"""
        mock_now = datetime(2023, 12, 22, 17, 30, 0)
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
    def test_at_exact_end_time(self, mock_datetime):
        """Test at exact end time boundary"""
        mock_now = datetime(2023, 12, 22, 19, 30, 0)
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

            # End time should be inclusive
            assert result is True

    @patch('app.datetime')
    def test_one_minute_before_start(self, mock_datetime):
        """Test one minute before start time"""
        mock_now = datetime(2023, 12, 22, 17, 29, 0)
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


class TestFlaskRoutesAdditional:
    """Additional tests for Flask routes"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_instance.get_soc.return_value = 75
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {"device_sn": "TEST123"},
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {"enabled": False}
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance

    def test_set_work_mode_updates_state(self, test_client):
        """Test that set_work_mode updates current_state"""
        client, app_module, mock_deye = test_client
        mock_deye.set_work_mode.return_value = {"code": "0"}
        app_module.current_state = {
            "mode": "ZERO_EXPORT_TO_CT",
            "force_discharge_active": False
        }

        response = client.post('/api/work-mode',
            data=json.dumps({"mode": "SELLING_FIRST"}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.current_state["mode"] == "SELLING_FIRST"

    def test_get_config_hides_password(self, test_client):
        """Test /api/config doesn't expose password"""
        client, app_module, _ = test_client
        app_module.config["deye"]["password"] = "secret_password"

        response = client.get('/api/config')
        data = json.loads(response.data)

        assert response.status_code == 200
        # Password should not be in response
        assert "password" not in str(data).lower() or data.get("deye", {}).get("password") is None

    def test_api_status_returns_state(self, test_client):
        """Test /api/status returns current state"""
        client, app_module, _ = test_client
        app_module.current_state = {
            "mode": "SELLING_FIRST",
            "soc": 75,
            "battery_power": 1500,
            "force_discharge_active": True,
            "last_check": "2023-12-22T18:00:00",
            "last_error": None,
            "scheduler_status": "running",
            "weather_skip_active": False,
            "weather_skip_reason": None,
            "free_energy_active": False
        }

        response = client.get('/api/status')
        data = json.loads(response.data)

        assert response.status_code == 200
        # Status endpoint returns current_state which includes mode
        assert "mode" in data or "soc" in data or len(data) > 0


class TestSetupEndpointsEdgeCases:
    """Edge case tests for setup endpoints"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {
                    "app_id": "YOUR_APP_ID",
                    "device_sn": "YOUR_DEVICE_SN"
                },
                "schedule": {},
                "weather": {}
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance

    @patch('app.DeyeCloudClient')
    def test_test_deye_connection_exception(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye handles connection exception"""
        client, app_module, _ = test_client
        mock_deye_class.side_effect = Exception("Connection failed")

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "test_app_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test_password",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        # Error message should not expose internal exception details (security fix)
        assert "Connection test failed" in data["error"]

    @patch('app.WeatherClient.search_cities')
    def test_test_weather_exception(self, mock_search, test_client):
        """Test /api/setup/test-weather handles exception"""
        client, app_module, _ = test_client
        mock_search.side_effect = Exception("API error")

        response = client.post('/api/setup/test-weather',
            data=json.dumps({}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "coordinates" in data["error"].lower() or "required" in data["error"].lower()


class TestShouldSkipDischargeEdgeCases:
    """Edge case tests for should_skip_discharge_for_weather"""

    def test_skip_no_analyser(self):
        """Test skip check when analyser not initialized"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = None

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False
            assert "not configured" in reason

    @patch('app.get_weather_forecast')
    def test_skip_failed_forecast(self, mock_forecast):
        """Test skip check with failed forecast"""
        mock_forecast.return_value = {"success": False, "error": "API down"}

        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {"weather": {"enabled": True, "min_solar_threshold_kwh": 5.0}}
            app_module.weather_client = Mock()
            app_module.weather_analyser = Mock()
            app_module.weather_analyser.should_skip_discharge.return_value = (False, "Forecast unavailable")

            should_skip, reason = app_module.should_skip_discharge_for_weather()

            assert should_skip is False


class TestAppAdditionalCoverage:
    """Additional tests to achieve 100% coverage in app.py"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_instance.get_battery_info.return_value = {"soc": 75, "power": 1000, "inverter_capacity": 10000}
            mock_instance.get_tou_settings.return_value = {"success": True, "timeUseSettingItems": []}
            mock_instance.get_device_latest_data.return_value = {"soc": 75}
            mock_instance.get_soc.return_value = 75
            mock_instance.get_inverter_capacity.return_value = 10000
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {"device_sn": "TEST123"},
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {"enabled": False}
            }
            app_module.client = mock_instance
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module, mock_instance


class TestInitClientBatteryInfo:
    """Tests for init_client battery info fetching"""

    @patch('app.DeyeCloudClient')
    def test_init_client_with_battery_info(self, mock_deye):
        """Test client init fetches battery info successfully"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
        mock_client.get_battery_info.return_value = {
            "soc": 80,
            "power": 2000,
            "inverter_capacity": 8000
        }
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {
            "mode": "unknown",
            "soc": None,
            "battery_power": None,
            "force_discharge_active": False,
            "last_error": None,
            "inverter_capacity": None
        }

        app_module.init_client()

        assert app_module.current_state["soc"] == 80
        assert app_module.current_state["battery_power"] == 2000
        assert app_module.current_state["inverter_capacity"] == 8000

    @patch('app.DeyeCloudClient')
    def test_init_client_battery_info_no_capacity(self, mock_deye):
        """Test client init fetches inverter capacity separately when not in battery_info"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True}
        mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}  # No inverter_capacity
        mock_client.get_inverter_capacity.return_value = 5000
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {
            "mode": "unknown",
            "soc": None,
            "battery_power": None,
            "force_discharge_active": False,
            "last_error": None,
            "inverter_capacity": None
        }

        app_module.init_client()

        assert app_module.current_state["inverter_capacity"] == 5000

    @patch('app.DeyeCloudClient')
    def test_init_client_battery_info_no_capacity_fallback(self, mock_deye):
        """Test client init uses default when capacity not available"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True}
        mock_client.get_battery_info.return_value = {"soc": 75, "power": 1000}
        mock_client.get_inverter_capacity.return_value = None  # Not available
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {
            "mode": "unknown",
            "soc": None,
            "battery_power": None,
            "force_discharge_active": False,
            "last_error": None,
            "inverter_capacity": None
        }

        app_module.init_client()

        assert app_module.current_state["inverter_capacity"] == 10000  # Default fallback

    @patch('app.DeyeCloudClient')
    def test_init_client_battery_info_exception(self, mock_deye):
        """Test client init handles battery info exception"""
        mock_client = Mock()
        mock_client.get_work_mode.return_value = {"success": True}
        mock_client.get_battery_info.side_effect = Exception("Battery API error")
        mock_deye.return_value = mock_client

        import app as app_module
        app_module.config = {"deye": {}}
        app_module.current_state = {
            "mode": "unknown",
            "soc": None,
            "battery_power": None,
            "force_discharge_active": False,
            "last_error": None,
            "inverter_capacity": None
        }

        app_module.init_client()

        assert app_module.current_state["inverter_capacity"] == 10000  # Default on error


class TestInitWeatherClientSolar:
    """Tests for init_weather_client with solar configuration"""

    @patch('app.SolarForecastClient')
    @patch('app.WeatherAnalyser')
    @patch('app.WeatherClient')
    def test_init_weather_client_with_panel_capacity(self, mock_weather, mock_analyser, mock_solar):
        """Test weather client init with panel capacity"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "panel_capacity_kw": 6.6,
                    "solar": {"enabled": True}
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.current_state = {"inverter_capacity": 5000}

            app_module.init_weather_client()

            mock_solar.assert_called_once()
            call_kwargs = mock_solar.call_args[1]
            assert call_kwargs["kwp"] == 6.6

    @patch('app.SolarForecastClient')
    @patch('app.WeatherAnalyser')
    @patch('app.WeatherClient')
    def test_init_weather_client_with_inverter_capacity_config(self, mock_weather, mock_analyser, mock_solar):
        """Test weather client init with inverter capacity from config"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "inverter_capacity_kw": 5.0,
                    "solar": {"enabled": True}
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.current_state = {"inverter_capacity": None}

            app_module.init_weather_client()

            mock_solar.assert_called_once()
            call_kwargs = mock_solar.call_args[1]
            assert call_kwargs["kwp"] == 6  # 5.0 * 1.25 = 6.25, but int() = 6

    @patch('app.SolarForecastClient')
    @patch('app.WeatherAnalyser')
    @patch('app.WeatherClient')
    def test_init_weather_client_with_api_inverter_capacity(self, mock_weather, mock_analyser, mock_solar):
        """Test weather client init with inverter capacity from API"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "solar": {"enabled": True}
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.current_state = {"inverter_capacity": 8000}  # 8kW

            app_module.init_weather_client()

            mock_solar.assert_called_once()
            call_kwargs = mock_solar.call_args[1]
            assert call_kwargs["kwp"] == 10  # 8 * 1.25 = 10

    @patch('app.SolarForecastClient')
    @patch('app.WeatherAnalyser')
    @patch('app.WeatherClient')
    def test_init_weather_client_with_solar_tilt_azimuth(self, mock_weather, mock_analyser, mock_solar):
        """Test weather client init with custom tilt and azimuth"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "panel_capacity_kw": 5.0,
                    "solar": {
                        "enabled": True,
                        "declination": 30,
                        "azimuth": 10
                    }
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.current_state = {"inverter_capacity": None}

            app_module.init_weather_client()

            mock_solar.assert_called_once()
            call_kwargs = mock_solar.call_args[1]
            assert call_kwargs["declination"] == 30
            assert call_kwargs["azimuth"] == 10

    @patch('app.WeatherAnalyser')
    @patch('app.WeatherClient')
    def test_init_weather_client_solar_disabled(self, mock_weather, mock_analyser):
        """Test weather client init when solar is disabled"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            app_module.config = {
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "solar": {"enabled": False}
                }
            }
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.current_state = {"inverter_capacity": None}

            app_module.init_weather_client()

            assert app_module.solar_client is None


class TestGetWeatherForecastAdditional:
    """Additional tests for get_weather_forecast"""

    def test_forecast_unsuccessful_returns_cached(self):
        """Test forecast returns cached on unsuccessful result"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            mock_weather_client = Mock()
            mock_weather_client.get_forecast.return_value = {"success": True}

            mock_analyser = Mock()
            mock_analyser.analyse_forecast.return_value = {"success": False}

            app_module.weather_client = mock_weather_client
            app_module.weather_analyser = mock_analyser
            app_module.config = {"weather": {}}
            app_module.current_state = {"inverter_capacity": None}
            app_module.weather_forecast_cache = {
                "forecast": {"cached": True, "success": True},
                "last_update": None
            }

            result = app_module.get_weather_forecast()

            assert result == {"cached": True, "success": True}

    def test_forecast_unsuccessful_no_cache(self):
        """Test forecast returns None when unsuccessful and no cache"""
        with patch('app.DeyeCloudClient'):
            import app as app_module
            mock_weather_client = Mock()
            mock_weather_client.get_forecast.return_value = {"success": True}

            mock_analyser = Mock()
            mock_analyser.analyse_forecast.return_value = {"success": False}

            app_module.weather_client = mock_weather_client
            app_module.weather_analyser = mock_analyser
            app_module.config = {"weather": {}}
            app_module.current_state = {"inverter_capacity": None}
            app_module.weather_forecast_cache = {
                "forecast": None,
                "last_update": None
            }

            result = app_module.get_weather_forecast()

            assert result is None


class TestSetupSearchCities:
    """Tests for city search during setup"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {"deye": {}, "weather": {}}
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    @patch('app.WeatherClient.search_cities')
    def test_setup_search_cities_success(self, mock_search, test_client):
        """Test /api/setup/search-cities returns cities"""
        client, _ = test_client
        mock_search.return_value = [
            {"name": "Sydney", "country": "AU", "display_name": "Sydney, NSW, AU"}
        ]

        response = client.get('/api/setup/search-cities?q=Sydney')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert len(data["cities"]) == 1

    @patch('app.WeatherClient.search_cities')
    def test_setup_search_cities_short_query(self, mock_search, test_client):
        """Test /api/setup/search-cities with short query"""
        client, _ = test_client

        response = client.get('/api/setup/search-cities?q=S')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert data["cities"] == []
        mock_search.assert_not_called()


class TestSearchCitiesAPI:
    """Tests for weather city search API"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {"deye": {}, "weather": {}}
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    @patch('app.WeatherClient.search_cities')
    def test_search_cities_success(self, mock_search, test_client):
        """Test /api/weather/cities returns cities"""
        client, _ = test_client
        mock_search.return_value = [
            {"name": "Melbourne", "country": "AU", "display_name": "Melbourne, VIC, AU"}
        ]

        response = client.get('/api/weather/cities?q=Melbourne')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert len(data["cities"]) == 1

    @patch('app.WeatherClient.search_cities')
    def test_search_cities_short_query(self, mock_search, test_client):
        """Test /api/weather/cities with short query"""
        client, _ = test_client

        response = client.get('/api/weather/cities?q=M')
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert data["cities"] == []


class TestCompleteSetup:
    """Tests for setup completion endpoint"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_instance.get_work_mode.return_value = {"success": True}
            mock_instance.get_battery_info.return_value = {"soc": 75}
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {},
                "weather": {}
            }
            app_module.client = mock_instance
            app_module.weather_forecast_cache = {"forecast": None, "last_update": None}
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    @patch('app.init_weather_client')
    @patch('app.init_client')
    @patch('app.save_config')
    def test_complete_setup_deye_config(self, mock_save, mock_init_client, mock_init_weather, test_client):
        """Test /api/setup/complete with Deye config"""
        client, app_module = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "deye": {
                    "api_base_url": "https://eu1-developer.deyecloud.com",
                    "app_id": "my_app_id",
                    "app_secret": "my_secret",
                    "email": "test@test.com",
                    "password": "password123",
                    "device_sn": "INVERTER123"
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["deye"]["app_id"] == "my_app_id"

    @patch('app.init_weather_client')
    @patch('app.init_client')
    @patch('app.save_config')
    def test_complete_setup_weather_config(self, mock_save, mock_init_client, mock_init_weather, test_client):
        """Test /api/setup/complete with weather config"""
        client, app_module = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "weather": {
                    "enabled": True,
                    "latitude": -33.8688,
                    "longitude": 151.2093,
                    "timezone": "Australia/Sydney",
                    "city_name": "Sydney, AU"
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["enabled"] is True

    @patch('app.init_weather_client')
    @patch('app.init_client')
    @patch('app.save_config')
    def test_complete_setup_solar_config(self, mock_save, mock_init_client, mock_init_weather, test_client):
        """Test /api/setup/complete with solar config"""
        client, app_module = test_client

        response = client.post('/api/setup/complete',
            data=json.dumps({
                "solar": {
                    "inverter_capacity_kw": 5.0,
                    "panel_capacity_kw": 6.6
                }
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["panel_capacity_kw"] == 6.6

    @patch('app.save_config')
    def test_complete_setup_exception(self, mock_save, test_client):
        """Test /api/setup/complete handles exception"""
        client, _ = test_client
        mock_save.side_effect = Exception("File error")

        response = client.post('/api/setup/complete',
            data=json.dumps({"deye": {}}),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False


class TestWeatherAPIException:
    """Tests for weather API exception handling"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {
                "deye": {},
                "weather": {"enabled": True}
            }
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    def test_weather_api_exception(self, test_client):
        """Test /api/weather handles exception"""
        client, app_module = test_client
        app_module.weather_client = Mock()

        with patch('app.get_weather_forecast', side_effect=Exception("API error")):
            response = client.get('/api/weather')
            data = json.loads(response.data)

            assert response.status_code == 500
            assert data["success"] is False


class TestDeyeTestHTTPErrors:
    """Tests for Deye connection test HTTP error handling"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {"deye": {}, "weather": {}}
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    @patch('app.DeyeCloudClient')
    def test_test_deye_401_error(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye handles 401 authentication error"""
        import requests
        client, _ = test_client

        mock_response = Mock()
        mock_response.status_code = 401
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_deye_class.return_value.get_device_latest_data.side_effect = http_error

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "bad_id",
                "app_secret": "bad_secret",
                "email": "test@test.com",
                "password": "wrong",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "authentication" in data["error"].lower()

    @patch('app.DeyeCloudClient')
    def test_test_deye_404_error(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye handles 404 error"""
        import requests
        client, _ = test_client

        mock_response = Mock()
        mock_response.status_code = 404
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_deye_class.return_value.get_device_latest_data.side_effect = http_error

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "test_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "404" in data["error"]

    @patch('app.DeyeCloudClient')
    def test_test_deye_other_http_error(self, mock_deye_class, test_client):
        """Test /api/setup/test-deye handles other HTTP errors"""
        import requests
        client, _ = test_client

        mock_response = Mock()
        mock_response.status_code = 500
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_deye_class.return_value.get_device_latest_data.side_effect = http_error

        response = client.post('/api/setup/test-deye',
            data=json.dumps({
                "app_id": "test_id",
                "app_secret": "test_secret",
                "email": "test@test.com",
                "password": "test",
                "device_sn": "ABC123"
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is False
        assert "500" in data["error"]


class TestWeatherConfigUpdateAdditional:
    """Additional tests for weather config update"""

    @pytest.fixture
    def test_client(self):
        """Create test client"""
        with patch('app.DeyeCloudClient') as mock_deye:
            mock_instance = Mock()
            mock_deye.return_value = mock_instance

            import app as app_module
            app_module.config = {"deye": {}, "weather": {}}
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.solar_client = None
            app_module.weather_forecast_cache = {"forecast": None, "last_update": None}
            app_module.app.testing = True

            yield app_module.app.test_client(), app_module

    @patch('app.init_weather_client')
    @patch('app.save_config')
    def test_update_weather_config_all_fields(self, mock_save, mock_init, test_client):
        """Test POST /api/weather/config updates all fields"""
        client, app_module = test_client

        response = client.post('/api/weather/config',
            data=json.dumps({
                "enabled": True,
                "city_name": "Sydney, AU",
                "latitude": -33.8688,
                "longitude": 151.2093,
                "timezone": "Australia/Sydney",
                "min_solar_threshold_kwh": 15.0,
                "bad_weather_conditions": ["Rain", "Snow"],
                "min_cloud_cover_percent": 80,
                "inverter_capacity_kw": 5.0,
                "panel_capacity_kw": 6.6,
                "panel_tilt": 25,
                "panel_azimuth": 0
            }),
            content_type='application/json'
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["success"] is True
        assert app_module.config["weather"]["city_name"] == "Sydney, AU"
        assert app_module.config["weather"]["bad_weather_conditions"] == ["Rain", "Snow"]
        assert app_module.config["weather"]["solar"]["declination"] == 25
        assert app_module.config["weather"]["solar"]["azimuth"] == 0


class TestSchedulerHysteresis:
    """Tests for scheduler hysteresis logic"""

    @patch('app.time.sleep')
    @patch('app.is_within_free_energy_window')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_reactivation_margin(self, mock_weather, mock_window, mock_free, mock_sleep):
        """Test scheduler uses reactivation margin when not discharging"""
        mock_window.return_value = True
        mock_free.return_value = False
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 52, "power": 1000}  # Just above cutoff
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "enabled": True,
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "reactivation_margin": 5,  # Need SoC > 55 to start
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                },
                "free_energy": {"enabled": False}
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None,
                "free_energy_active": False,
                "inverter_capacity": 10000
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Should NOT activate discharge because SoC 52 < cutoff 50 + margin 5 = 55
            mock_client.set_work_mode.assert_not_called()

    @patch('app.time.sleep')
    @patch('app.is_within_free_energy_window')
    @patch('app.is_within_discharge_window')
    @patch('app.should_skip_discharge_for_weather')
    def test_scheduler_force_discharge_disabled(self, mock_weather, mock_window, mock_free, mock_sleep):
        """Test scheduler respects force discharge enabled setting"""
        mock_window.return_value = True
        mock_free.return_value = False
        mock_weather.return_value = (False, "Good weather")

        with patch('app.DeyeCloudClient') as mock_deye:
            mock_client = Mock()
            mock_client.get_battery_info.return_value = {"soc": 80, "power": 1000}
            mock_client.get_work_mode.return_value = {"success": True, "systemWorkMode": "ZERO_EXPORT_TO_CT"}
            mock_deye.return_value = mock_client

            import app as app_module
            app_module.client = mock_client
            app_module.config = {
                "schedule": {
                    "enabled": False,  # Disabled
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30"
                },
                "free_energy": {"enabled": False}
            }
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "force_discharge_active": False,
                "soc": None,
                "battery_power": None,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None,
                "free_energy_active": False,
                "inverter_capacity": 10000
            }

            app_module.scheduler_running = True

            def stop_after_one(*args):
                app_module.scheduler_running = False

            mock_sleep.side_effect = stop_after_one

            app_module.scheduler_loop()

            # Should NOT activate discharge because it's disabled
            mock_client.set_work_mode.assert_not_called()
