"""Shared pytest fixtures and configuration"""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_weather_config():
    """Sample weather configuration for tests"""
    return {
        "enabled": True,
        "api_key": "test_api_key",
        "city_name": "Sydney, AU",
        "min_solar_threshold_kwh": 5.0,
        "panel_capacity_kw": 6.6,
        "bad_weather_conditions": ["Rain", "Thunderstorm", "Drizzle", "Snow"],
        "min_cloud_cover_percent": 70
    }


@pytest.fixture
def sample_schedule_config():
    """Sample schedule configuration for tests"""
    return {
        "force_discharge_start": "17:30",
        "force_discharge_end": "19:30",
        "min_soc_reserve": 20,
        "force_discharge_cutoff_soc": 50,
        "max_discharge_power": 10000
    }


@pytest.fixture
def sample_deye_config():
    """Sample Deye configuration for tests"""
    return {
        "api_base_url": "https://test-api.deyecloud.com",
        "app_id": "test_app_id",
        "app_secret": "test_secret",
        "email": "test@test.com",
        "password": "test_password",
        "device_sn": "TEST123456"
    }


@pytest.fixture
def sample_forecast_good():
    """Sample good weather forecast"""
    return {
        "success": True,
        "location": "Sydney",
        "daily": [
            {
                "date": "2023-12-22",
                "day_name": "Friday",
                "is_today": True,
                "temp_min": 18.0,
                "temp_max": 28.0,
                "condition": "Clear",
                "description": "clear sky",
                "icon": "01d",
                "clouds": 10,
                "pop": 5,
                "rain": 0,
                "uvi": 9.0,
                "is_bad_weather": False
            },
            {
                "date": "2023-12-23",
                "day_name": "Saturday",
                "is_today": False,
                "temp_min": 20.0,
                "temp_max": 30.0,
                "condition": "Clouds",
                "description": "partly cloudy",
                "icon": "03d",
                "clouds": 30,
                "pop": 10,
                "rain": 0,
                "uvi": 8.0,
                "is_bad_weather": False
            }
        ],
        "consecutive_bad_days": 0,
        "bad_weather_days": []
    }


@pytest.fixture
def sample_forecast_bad():
    """Sample bad weather forecast"""
    return {
        "success": True,
        "location": "Sydney",
        "daily": [
            {
                "date": "2023-12-22",
                "day_name": "Friday",
                "is_today": True,
                "temp_min": 15.0,
                "temp_max": 20.0,
                "condition": "Rain",
                "description": "heavy rain",
                "icon": "10d",
                "clouds": 90,
                "pop": 80,
                "rain": 15.5,
                "uvi": 2.0,
                "is_bad_weather": True
            },
            {
                "date": "2023-12-23",
                "day_name": "Saturday",
                "is_today": False,
                "temp_min": 14.0,
                "temp_max": 18.0,
                "condition": "Thunderstorm",
                "description": "thunderstorm",
                "icon": "11d",
                "clouds": 95,
                "pop": 90,
                "rain": 25.0,
                "uvi": 1.0,
                "is_bad_weather": True
            },
            {
                "date": "2023-12-24",
                "day_name": "Sunday",
                "is_today": False,
                "temp_min": 16.0,
                "temp_max": 22.0,
                "condition": "Drizzle",
                "description": "light drizzle",
                "icon": "09d",
                "clouds": 80,
                "pop": 60,
                "rain": 5.0,
                "uvi": 3.0,
                "is_bad_weather": True
            }
        ],
        "consecutive_bad_days": 3,
        "bad_weather_days": ["2023-12-22", "2023-12-23", "2023-12-24"]
    }
