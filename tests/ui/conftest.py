"""Playwright UI test fixtures and configuration"""
import pytest
import threading
import time
import socket
from unittest.mock import Mock, patch


def find_free_port():
    """Find an available port for the test server"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))  # Bind to localhost only, not all interfaces
        s.listen(1)
        port = s.getsockname()[1]
    return port


@pytest.fixture(scope="session")
def mock_deye_client():
    """Create a mock Deye client for UI tests"""
    mock_client = Mock()
    mock_client.get_work_mode.return_value = {
        "success": True,
        "systemWorkMode": "ZERO_EXPORT_TO_CT"
    }
    mock_client.get_battery_info.return_value = {
        "soc": 75,
        "power": 1500,
        "inverter_capacity": 10000
    }
    mock_client.get_tou_settings.return_value = {
        "success": True,
        "touAction": 1,
        "timeUseSettingItems": [
            {
                "timeRange": "00:00-17:30",
                "socTarget": 20,
                "power": 10000,
                "gridCharge": False
            },
            {
                "timeRange": "17:30-19:30",
                "socTarget": 50,
                "power": 10000,
                "gridCharge": False
            },
            {
                "timeRange": "19:30-00:00",
                "socTarget": 20,
                "power": 10000,
                "gridCharge": False
            }
        ]
    }
    mock_client.get_device_latest_data.return_value = {
        "success": True,
        "code": 0,
        "deviceDataList": [{"deviceName": "Test Inverter", "soc": 75}]
    }
    mock_client.get_soc.return_value = 75
    mock_client.set_work_mode.return_value = {"success": True, "code": "0"}
    mock_client.set_tou_settings.return_value = {"success": True}
    mock_client.get_inverter_capacity.return_value = 10000
    return mock_client


@pytest.fixture(scope="session")
def app_server(mock_deye_client):
    """Start Flask app in background thread for Playwright tests"""
    port = find_free_port()
    server_started = threading.Event()

    def run_server():
        with patch('app.DeyeCloudClient') as mock_deye_class:
            mock_deye_class.return_value = mock_deye_client

            import app as app_module

            # Configure app for testing with valid credentials (no setup wizard)
            app_module.config = {
                "deye": {
                    "api_base_url": "https://test.deyecloud.com",
                    "app_id": "test_app_id",
                    "app_secret": "test_secret",
                    "email": "test@test.com",
                    "password": "test_password",
                    "device_sn": "TEST123"
                },
                "schedule": {
                    "enabled": True,
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50,
                    "max_discharge_power": 10000
                },
                "weather": {
                    "enabled": True,
                    "api_key": "test_weather_key",
                    "city_name": "Sydney, AU",
                    "min_solar_threshold_kwh": 15,
                    "panel_capacity_kw": 6.6
                },
                "free_energy": {
                    "enabled": False,
                    "start_time": "11:00",
                    "end_time": "14:00",
                    "target_soc": 100
                }
            }
            app_module.client = mock_deye_client
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.scheduler_running = False
            app_module.current_state = {
                "mode": "ZERO_EXPORT_TO_CT",
                "soc": 75,
                "battery_power": 1500,
                "force_discharge_active": False,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None,
                "free_energy_active": False,
                "inverter_capacity": 10000
            }

            app_module.app.testing = False
            server_started.set()
            app_module.app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    server_started.wait(timeout=10)
    time.sleep(0.5)  # Extra time for Flask to fully initialize

    yield f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def app_server_needs_setup(mock_deye_client):
    """Start Flask app that requires setup wizard"""
    port = find_free_port()
    server_started = threading.Event()

    def run_server():
        with patch('app.DeyeCloudClient') as mock_deye_class:
            mock_deye_class.return_value = mock_deye_client

            import app as app_module

            # Configure app as unconfigured (needs setup)
            app_module.config = {
                "deye": {
                    "api_base_url": "https://eu1-developer.deyecloud.com",
                    "app_id": "YOUR_APP_ID",
                    "app_secret": "YOUR_APP_SECRET",
                    "email": "YOUR_EMAIL",
                    "password": "",
                    "device_sn": "YOUR_DEVICE_SN"
                },
                "schedule": {
                    "force_discharge_start": "17:30",
                    "force_discharge_end": "19:30",
                    "min_soc_reserve": 20,
                    "force_discharge_cutoff_soc": 50
                },
                "weather": {}
            }
            app_module.client = None
            app_module.weather_client = None
            app_module.weather_analyser = None
            app_module.scheduler_running = False
            app_module.current_state = {
                "mode": "unknown",
                "soc": None,
                "battery_power": None,
                "force_discharge_active": False,
                "last_check": None,
                "last_error": None,
                "scheduler_status": "stopped",
                "weather_skip_active": False,
                "weather_skip_reason": None,
                "free_energy_active": False,
                "inverter_capacity": None
            }

            app_module.app.testing = False
            server_started.set()
            app_module.app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    server_started.wait(timeout=10)
    time.sleep(0.5)

    yield f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for tests"""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True
    }


@pytest.fixture
def ensure_configured_state(app_server):
    """
    Ensure the app config is in configured state before test.

    This is needed because app_server and app_server_needs_setup fixtures
    share the same module-level config variable. When app_server_needs_setup
    runs, it overwrites the config with placeholder values. This fixture
    resets the config to valid values before tests that need the configured state.
    """
    import app as app_module
    app_module.config = {
        "deye": {
            "api_base_url": "https://test.deyecloud.com",
            "app_id": "test_app_id",
            "app_secret": "test_secret",
            "email": "test@test.com",
            "password": "test_password",
            "device_sn": "TEST123"
        },
        "schedule": {
            "enabled": True,
            "force_discharge_start": "17:30",
            "force_discharge_end": "19:30",
            "min_soc_reserve": 20,
            "force_discharge_cutoff_soc": 50,
            "max_discharge_power": 10000
        },
        "weather": {
            "enabled": True,
            "api_key": "test_weather_key",
            "city_name": "Sydney, AU",
            "min_solar_threshold_kwh": 15,
            "panel_capacity_kw": 6.6
        },
        "free_energy": {
            "enabled": False,
            "start_time": "11:00",
            "end_time": "14:00",
            "target_soc": 100
        }
    }
    yield app_server


@pytest.fixture
def ensure_needs_setup_state(app_server_needs_setup):
    """
    Ensure the app config is in unconfigured state before test.

    This is needed because app_server and app_server_needs_setup fixtures
    share the same module-level config variable. When ensure_configured_state
    or app_server runs, it overwrites the config with valid values. This fixture
    resets the config to placeholder values before tests that need the setup wizard.
    """
    import app as app_module
    app_module.config = {
        "deye": {
            "api_base_url": "https://eu1-developer.deyecloud.com",
            "app_id": "YOUR_APP_ID",
            "app_secret": "YOUR_APP_SECRET",
            "email": "YOUR_EMAIL",
            "password": "",
            "device_sn": "YOUR_DEVICE_SN"
        },
        "schedule": {
            "force_discharge_start": "17:30",
            "force_discharge_end": "19:30",
            "min_soc_reserve": 20,
            "force_discharge_cutoff_soc": 50
        },
        "weather": {}
    }
    app_module.client = None
    yield app_server_needs_setup
