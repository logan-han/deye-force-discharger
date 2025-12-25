# Deye Force Discharger

[![Docker Hub](https://img.shields.io/docker/v/loganhan123/deye-force-discharger?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/loganhan123/deye-force-discharger)
[![Docker Pulls](https://img.shields.io/docker/pulls/loganhan123/deye-force-discharger)](https://hub.docker.com/r/loganhan123/deye-force-discharger)
[![codecov](https://codecov.io/gh/logan-han/deye-force-discharger/graph/badge.svg)](https://codecov.io/gh/logan-han/deye-force-discharger)

A Python application to automate battery discharge scheduling for Deye hybrid inverters via the Deye Cloud API.

![Web Interface](screenshot.png)

## Background

This project was built for **AC-coupled Deye hybrid inverter setups** where solar input comes from a separate inverter.

In this configuration, the Deye inverter typically operates in **"Zero Export to CT"** mode to:

- Power household loads from the battery
- Charge the battery from the AC-coupled solar system

When running in "Zero Export to CT" mode, the inverter does not allow force battery discharge to the grid. This means you cannot export stored battery energy during peak electricity pricing windows.

## How It Works

The scheduler monitors the current time, battery SoC, and weather forecast, controlling both the work mode and TOU settings:

1. **Within discharge window** (e.g., 17:30-19:30) **and SoC above cutoff** **and good weather forecast**:
   - Switches to `SELLING_FIRST` mode
   - Sets TOU window SoC to the cutoff value (e.g., 50%)
   - Battery discharges to grid until cutoff is reached

2. **Outside window or SoC at/below cutoff or bad weather forecast**:
   - Switches to `ZERO_EXPORT_TO_CT` mode
   - Sets TOU SoC to reserve value (e.g., 20%) for all periods
   - Normal zero-export operation resumes

## Weather-Based Discharge Skip

The system can automatically skip battery discharge when bad weather is forecasted. This helps preserve battery charge for cloudy/rainy days when solar generation will be insufficient.

**Why this matters:** During bad weather, solar panels will not generate enough power to recharge the battery. By skipping discharge before bad weather, the battery retains enough charge to cover household needs without importing from the grid.

**How it works:**
- Fetches 4-day weather forecast from Open-Meteo (free, no API key required)
- Gets solar production forecasts from forecast.solar for accurate predictions
- Compares tomorrow's solar forecast against your minimum threshold (configurable)
- If solar production is expected to be below threshold, discharge is skipped
- Displayed in the web UI with forecast cards showing solar estimates

## Solar Output Estimates

When you configure your solar system details, the application displays estimated daily solar output for each forecast day. This helps you plan your energy usage and understand when discharge might be beneficial.

**How it works:**
- Enter your panel capacity (kWp), tilt angle, and direction
- The system fetches accurate predictions from [forecast.solar](https://forecast.solar) API
- Falls back to weather-based estimation if forecast.solar is unavailable
- Estimates account for your specific location, panel configuration, and weather conditions
- Displayed alongside the weather forecast cards

## Requirements

- Python 3.11+
- Deye Cloud developer account (API credentials)
- Deye hybrid inverter with battery storage

## Installation & Setup

### Quick Start with Docker Hub

```bash
# Pull and run the container
docker run -d \
  --name deye-force-discharger \
  -p 7777:7777 \
  -v $(pwd)/config.json:/app/config.json \
  -e TZ=Australia/Sydney \
  --restart unless-stopped \
  loganhan123/deye-force-discharger:latest
```

### Using Docker Compose

```bash
# Start the container
docker-compose up -d
```

The web interface is available at `http://<server_ip>:7777`

### First-Time Setup

When you first access the web interface with default configuration, a **setup wizard** will guide you through:

1. **Deye Cloud Configuration** - Enter your API credentials and device serial number
2. **Location Setup** (optional) - Search and select your location for weather forecasts (no API key required!)
3. **Solar System Details** - Configure your panel capacity, tilt angle, and direction for accurate solar forecasts

Each step includes a **Test Connection** button to verify your settings before proceeding.

## Configuration

You can also manually edit `config.json`:

```json
{
  "deye": {
    "api_base_url": "https://eu1-developer.deyecloud.com",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET",
    "email": "your@email.com",
    "password": "YOUR_PASSWORD",
    "device_sn": "YOUR_DEVICE_SERIAL"
  },
  "schedule": {
    "force_discharge_start": "17:30",
    "force_discharge_end": "19:30",
    "min_soc_reserve": 20,
    "force_discharge_cutoff_soc": 50,
    "max_discharge_power": 10000
  },
  "weather": {
    "enabled": true,
    "latitude": -33.8688,
    "longitude": 151.2093,
    "timezone": "Australia/Sydney",
    "city_name": "Sydney, New South Wales, AU",
    "min_solar_threshold_kwh": 15,
    "panel_capacity_kw": 6.6
  },
  "free_energy": {
    "enabled": false,
    "start_time": "11:00",
    "end_time": "14:00",
    "target_soc": 100
  }
}
```

### Configuration Options

| Field | Description |
|-------|-------------|
| `api_base_url` | Deye Cloud API endpoint (varies by region) |
| `app_id` | Your Deye Cloud app ID |
| `app_secret` | Your Deye Cloud app secret |
| `email` | Deye Cloud account email |
| `password` | Your Deye Cloud password |
| `device_sn` | Your inverter serial number |
| `force_discharge_start` | Start time for force discharge (HH:MM) |
| `force_discharge_end` | End time for force discharge (HH:MM) |
| `min_soc_reserve` | Minimum battery SoC reserve (used outside discharge window) |
| `force_discharge_cutoff_soc` | SoC at which to stop force discharge (e.g., 50%) |
| `max_discharge_power` | Maximum discharge power in watts (e.g., 10000) |

### Weather Configuration (Optional)

Weather and solar forecasts use free APIs (no API keys required!):
- **Open-Meteo** for weather forecasts
- **forecast.solar** for solar production predictions

Panel tilt and direction are automatically calculated from your location for optimal positioning.

| Field | Description |
|-------|-------------|
| `enabled` | Enable/disable weather-based discharge skip (default: false) |
| `latitude` | Your location latitude |
| `longitude` | Your location longitude |
| `timezone` | Your timezone (e.g., "Australia/Sydney") or "auto" |
| `city_name` | City name (for display, selected via autocomplete in UI) |
| `min_solar_threshold_kwh` | Minimum expected solar kWh to allow discharge (default: 15) |
| `panel_capacity_kw` | Your panel capacity in kWp (optional - auto-estimated from inverter if not set) |

### Free Energy Window (Optional)

| Field | Description |
|-------|-------------|
| `enabled` | Enable/disable free energy window charging |
| `start_time` | Start time for free energy period (HH:MM) |
| `end_time` | End time for free energy period (HH:MM) |
| `target_soc` | Target SoC to charge to during free energy window |

## Getting Deye Cloud API Credentials

1. Register at [Deye Cloud Developer Portal](https://developer.deyecloud.com)
2. Create an application to get your `app_id` and `app_secret`
3. Find your device serial number in the Deye app or on the inverter

## Android Widget

I have also created an Android app for this and some extra features like showing SoC & charge/discharge status in a 1x1 widget.

Worth considering if you do not have a place to host this.

Drop me an email if you want to be a tester. (logan_at_han.life)
