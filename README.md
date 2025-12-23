# Deye Force Discharger

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

**Why this matters:** During consecutive bad weather days, solar panels will not generate enough power to recharge the battery. By skipping discharge before bad weather, the battery retains enough charge to cover household needs without importing from the grid.

**How it works:**
- Fetches 7-day weather forecast from OpenWeatherMap
- Analyses conditions: rain, thunderstorms, drizzle, snow, high cloud cover (>70%)
- If bad weather is expected for X consecutive days (configurable, default 2), discharge is skipped
- Displayed in the web UI with forecast cards showing good/bad days

## Solar Output Estimates

When you configure your solar system capacity, the application displays estimated daily solar output for each forecast day. This helps you plan your energy usage and understand when discharge might be beneficial.

**How it works:**
- Enter your inverter capacity (or panel capacity if known)
- The system calculates expected output based on weather conditions
- Estimates account for cloud cover, precipitation probability, and weather type
- Displayed alongside the weather forecast cards

## Requirements

- Python 3.11+
- Deye Cloud developer account (API credentials)
- Deye hybrid inverter with battery storage

## Installation & Setup

### Quick Start

```bash
# Start the container
docker-compose up -d
```

The web interface is available at `http://<server_ip>:7777`

### First-Time Setup

When you first access the web interface with default configuration, a **setup wizard** will guide you through:

1. **Deye Cloud Configuration** - Enter your API credentials and device serial number
2. **Weather Integration** (optional) - Add OpenWeatherMap API key for weather-based features
3. **Solar System Details** - Configure your inverter/panel capacity for energy estimates

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
    "api_key": "YOUR_OPENWEATHERMAP_API_KEY",
    "city_name": "Sydney, New South Wales, AU",
    "latitude": -33.8688,
    "longitude": 151.2093,
    "bad_weather_threshold_days": 2,
    "bad_weather_conditions": ["Rain", "Thunderstorm", "Drizzle", "Snow"],
    "min_cloud_cover_percent": 70,
    "inverter_capacity_kw": 5,
    "panel_capacity_kw": 0
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

| Field | Description |
|-------|-------------|
| `enabled` | Enable/disable weather-based discharge skip (default: false) |
| `api_key` | OpenWeatherMap API key ([get free key](https://openweathermap.org/api)) |
| `city_name` | City name (selected via autocomplete in UI) |
| `latitude` | Your location latitude |
| `longitude` | Your location longitude |
| `bad_weather_threshold_days` | Number of consecutive bad days to trigger skip (default: 2) |
| `bad_weather_conditions` | Weather conditions considered "bad" for solar |
| `min_cloud_cover_percent` | Cloud cover % threshold for bad weather (default: 70) |
| `inverter_capacity_kw` | Your inverter capacity in kW (for solar estimates) |
| `panel_capacity_kw` | Your panel capacity in kW (optional, overrides inverter capacity) |

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
