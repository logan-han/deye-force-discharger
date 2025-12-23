import json
import logging
import requests
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from deye_client import DeyeCloudClient
from weather_client import WeatherClient, WeatherAnalyser, SolarForecastClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Work modes for AC-coupled setup
MODE_NORMAL = "ZERO_EXPORT_TO_CT"
MODE_FORCE_DISCHARGE = "SELLING_FIRST"

# Global state
config = {}
client: DeyeCloudClient = None
weather_client: WeatherClient = None
weather_analyser: WeatherAnalyser = None
solar_client: SolarForecastClient = None
scheduler_thread: threading.Thread = None
scheduler_running = False
current_state = {
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
    "inverter_capacity": None  # Max discharge power in watts from API
}
weather_forecast_cache = {
    "forecast": None,
    "last_update": None
}


def load_config():
    """Load configuration from file"""
    global config
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    logger.info("Configuration loaded")
    return config


def save_config():
    """Save configuration to file"""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    logger.info("Configuration saved")


def init_client():
    """Initialise Deye client"""
    global client, current_state
    deye_config = config.get("deye", {})
    client = DeyeCloudClient(
        api_base_url=deye_config.get("api_base_url"),
        app_id=deye_config.get("app_id"),
        app_secret=deye_config.get("app_secret"),
        email=deye_config.get("email"),
        password=deye_config.get("password"),
        device_sn=deye_config.get("device_sn")
    )
    logger.info("Deye client initialised")

    # Clear any previous errors on reinit
    current_state["last_error"] = None

    # Fetch initial mode
    try:
        mode_data = client.get_work_mode()
        if mode_data.get("success"):
            work_mode = mode_data.get("systemWorkMode")
            if work_mode:
                current_state["mode"] = work_mode
                current_state["force_discharge_active"] = (work_mode == MODE_FORCE_DISCHARGE)
                logger.info(f"Initial work mode: {work_mode}")
    except Exception as e:
        logger.warning(f"Could not fetch initial work mode: {e}")

    # Fetch inverter capacity and battery info
    try:
        battery_info = client.get_battery_info()
        if battery_info.get("soc") is not None:
            current_state["soc"] = battery_info["soc"]
            logger.info(f"Initial SoC: {battery_info['soc']}%")
        if battery_info.get("power") is not None:
            current_state["battery_power"] = battery_info["power"]
            logger.info(f"Initial battery power: {battery_info['power']}W")
        if battery_info.get("inverter_capacity"):
            current_state["inverter_capacity"] = battery_info["inverter_capacity"]
            logger.info(f"Inverter capacity: {battery_info['inverter_capacity']}W")
        else:
            # Try dedicated method if not in battery_info
            capacity = client.get_inverter_capacity()
            if capacity:
                current_state["inverter_capacity"] = capacity
                logger.info(f"Inverter capacity: {capacity}W")
            else:
                current_state["inverter_capacity"] = 10000
                logger.warning("Could not get inverter capacity from API, using default 10000W")
    except Exception as e:
        current_state["inverter_capacity"] = 10000
        logger.warning(f"Could not fetch initial battery info: {e}")


def init_weather_client():
    """Initialise weather client if enabled"""
    global weather_client, weather_analyser, solar_client

    weather_config = config.get("weather", {})

    if not weather_config.get("enabled", False):
        logger.info("Weather feature disabled")
        return

    latitude = weather_config.get("latitude")
    longitude = weather_config.get("longitude")

    if latitude is None or longitude is None:
        logger.warning("Weather location not configured - weather feature disabled")
        return

    timezone_str = weather_config.get("timezone", "auto")

    weather_client = WeatherClient(
        latitude=latitude,
        longitude=longitude,
        timezone_str=timezone_str
    )

    bad_conditions = weather_config.get("bad_weather_conditions", ["Rain", "Thunderstorm", "Drizzle", "Snow"])
    min_cloud_cover = weather_config.get("min_cloud_cover_percent", 70)

    weather_analyser = WeatherAnalyser(
        bad_conditions=bad_conditions,
        min_cloud_cover=min_cloud_cover
    )

    # Initialize solar forecast client if solar config is present
    solar_config = weather_config.get("solar", {})
    if solar_config.get("enabled", True):
        # Use panel capacity if set, otherwise estimate from inverter capacity (typical 1.25x oversizing)
        panel_kw = weather_config.get("panel_capacity_kw", 0)
        inverter_kw = weather_config.get("inverter_capacity_kw", 0)
        # Also check inverter capacity from current_state (from Deye API)
        api_inverter_kw = (current_state.get("inverter_capacity") or 0) / 1000

        if panel_kw and panel_kw > 0:
            kwp = panel_kw
        elif inverter_kw and inverter_kw > 0:
            kwp = inverter_kw * 1.25  # Common panel oversizing ratio
        elif api_inverter_kw and api_inverter_kw > 0:
            kwp = api_inverter_kw * 1.25
        else:
            kwp = 5.0  # Default fallback

        # Let SolarForecastClient calculate optimal tilt/azimuth from location if not specified
        declination = solar_config.get("declination")  # None = auto-calculate
        azimuth = solar_config.get("azimuth")  # None = auto-calculate

        if kwp and kwp > 0:
            solar_client = SolarForecastClient(
                latitude=latitude,
                longitude=longitude,
                declination=declination,
                azimuth=azimuth,
                kwp=kwp
            )
            logger.info(f"Solar forecast client initialised for {kwp:.1f}kWp system (tilt={solar_client.declination}, azimuth={solar_client.azimuth})")

    location_str = weather_config.get("city_name") or "configured location"
    logger.info(f"Weather client initialised for {location_str}")


def get_weather_forecast():
    """Get weather forecast with caching"""
    global weather_forecast_cache

    if not weather_client or not weather_analyser:
        return None

    # Check cache (update every 5 minutes - matches frontend refresh)
    cache_age = None
    if weather_forecast_cache["last_update"]:
        cache_age = (datetime.now() - weather_forecast_cache["last_update"]).total_seconds()

    if cache_age is None or cache_age > 300:  # 5 minutes
        try:
            forecast = weather_client.get_forecast()
            # Get panel capacity for solar estimates (fallback if forecast.solar unavailable)
            weather_config = config.get("weather", {})
            panel_kw = weather_config.get("panel_capacity_kw", 0)
            inverter_kw = weather_config.get("inverter_capacity_kw", 0)
            # Also check inverter capacity from Deye API (stored in watts)
            api_inverter_kw = (current_state.get("inverter_capacity") or 0) / 1000
            if panel_kw > 0:
                capacity_kw = panel_kw
            elif inverter_kw > 0:
                capacity_kw = inverter_kw * 1.25  # Typical panel oversizing ratio
            elif api_inverter_kw > 0:
                capacity_kw = api_inverter_kw * 1.25  # Use API inverter capacity with oversizing ratio
            else:
                capacity_kw = 0
            logger.info(f"Solar capacity for forecast: {capacity_kw} kW (panel={panel_kw}, inverter_config={inverter_kw}, inverter_api={api_inverter_kw})")
            # Analyse forecast with solar predictions (uses forecast.solar if available, falls back to weather-based)
            forecast = weather_analyser.analyse_forecast(
                forecast,
                panel_capacity_kw=capacity_kw if capacity_kw > 0 else None,
                weather_client=weather_client,
                solar_client=solar_client,
                min_solar_threshold=weather_config.get("min_solar_threshold_kwh", 15)
            )
            # Only cache successful forecasts
            if forecast.get("success", True):
                # Remove any internal error details before caching
                forecast.pop("error", None)
                weather_forecast_cache["forecast"] = forecast
                weather_forecast_cache["last_update"] = datetime.now()
                logger.info("Weather forecast updated successfully")
            else:
                logger.warning("Weather forecast returned unsuccessful result")
                if weather_forecast_cache["forecast"]:
                    return weather_forecast_cache["forecast"]
                return None
        except Exception as e:
            logger.error(f"Failed to fetch weather forecast: {e}")
            # Return cached data if available
            if weather_forecast_cache["forecast"]:
                return weather_forecast_cache["forecast"]
            return None

    return weather_forecast_cache["forecast"]


def should_skip_discharge_for_weather() -> tuple:
    """Check if discharge should be skipped due to weather forecast"""
    weather_config = config.get("weather", {})

    if not weather_config.get("enabled", False):
        return False, "Weather check disabled"

    if not weather_client or not weather_analyser:
        return False, "Weather not configured"

    forecast = get_weather_forecast()
    if not forecast:
        return False, "Weather data unavailable"

    min_solar_kwh = weather_config.get("min_solar_threshold_kwh", 0)
    return weather_analyser.should_skip_discharge(forecast, min_solar_kwh)


def is_within_discharge_window() -> bool:
    """Check if current time is within force discharge window"""
    schedule = config.get("schedule", {})
    start_time_str = schedule.get("force_discharge_start", "17:30")
    end_time_str = schedule.get("force_discharge_end", "19:30")

    now = datetime.now()
    start_parts = start_time_str.split(":")
    end_parts = end_time_str.split(":")

    start_time = now.replace(
        hour=int(start_parts[0]),
        minute=int(start_parts[1]),
        second=0,
        microsecond=0
    )
    end_time = now.replace(
        hour=int(end_parts[0]),
        minute=int(end_parts[1]),
        second=0,
        microsecond=0
    )

    # Handle overnight windows (e.g., 22:00 to 06:00)
    if end_time <= start_time:
        end_time += timedelta(days=1)
        if now < start_time:
            now += timedelta(days=1)

    return start_time <= now <= end_time


def is_within_free_energy_window() -> bool:
    """Check if current time is within free energy window"""
    free_energy = config.get("free_energy", {})

    if not free_energy.get("enabled", False):
        return False

    start_time_str = free_energy.get("start_time", "11:00")
    end_time_str = free_energy.get("end_time", "14:00")

    now = datetime.now()
    start_parts = start_time_str.split(":")
    end_parts = end_time_str.split(":")

    start_time = now.replace(
        hour=int(start_parts[0]),
        minute=int(start_parts[1]),
        second=0,
        microsecond=0
    )
    end_time = now.replace(
        hour=int(end_parts[0]),
        minute=int(end_parts[1]),
        second=0,
        microsecond=0
    )

    # Handle overnight windows
    if end_time <= start_time:
        end_time += timedelta(days=1)
        if now < start_time:
            now += timedelta(days=1)

    return start_time <= now <= end_time


def get_free_energy_tou_params():
    """Get free energy TOU parameters if enabled"""
    free_energy = config.get("free_energy", {})

    if not free_energy.get("enabled", False):
        return None, None, None

    return (
        free_energy.get("start_time", "11:00"),
        free_energy.get("end_time", "14:00"),
        free_energy.get("target_soc", 100)
    )


def scheduler_loop():
    """Main scheduler loop for automatic mode switching"""
    global current_state, scheduler_running

    logger.info("Scheduler started")
    current_state["scheduler_status"] = "running"

    while scheduler_running:
        try:
            schedule = config.get("schedule", {})

            # Get SoC settings
            min_soc_reserve = schedule.get("min_soc_reserve", 20)
            cutoff_soc = schedule.get("force_discharge_cutoff_soc", 50)
            max_power = current_state.get("inverter_capacity") or 10000

            # Get current battery info
            battery_info = client.get_battery_info()
            soc = battery_info.get("soc")
            current_state["soc"] = soc
            current_state["battery_power"] = battery_info.get("power")
            current_state["last_check"] = datetime.now().isoformat()

            # Clear any stale errors on successful data fetch
            if soc is not None:
                current_state["last_error"] = None

            in_window = is_within_discharge_window()
            in_free_energy_window = is_within_free_energy_window()
            current_state["free_energy_active"] = in_free_energy_window

            # Check weather forecast for skip condition
            weather_skip, weather_reason = should_skip_discharge_for_weather()
            current_state["weather_skip_active"] = weather_skip
            current_state["weather_skip_reason"] = weather_reason

            # Get free energy TOU params
            free_energy_start, free_energy_end, free_energy_soc = get_free_energy_tou_params()

            # Check if force discharge is enabled
            force_discharge_enabled = schedule.get("enabled", True)

            # Determine if we should be in force discharge mode
            # Force discharge when: enabled AND in window AND SoC above cutoff AND NOT weather skip
            should_force_discharge = force_discharge_enabled and in_window and (soc is None or soc > cutoff_soc) and not weather_skip
            logger.debug(f"Scheduler check: discharge={'active' if should_force_discharge else 'inactive'}")

            if weather_skip and in_window:
                logger.debug("Skipping discharge due to weather conditions")

            window_start = schedule.get("force_discharge_start", "17:30")
            window_end = schedule.get("force_discharge_end", "19:30")

            # Fetch actual work mode from inverter
            try:
                mode_data = client.get_work_mode()
                if mode_data.get("success"):
                    actual_mode = mode_data.get("systemWorkMode")
                    if actual_mode:
                        current_state["mode"] = actual_mode
                        current_state["force_discharge_active"] = (actual_mode == MODE_FORCE_DISCHARGE)
            except Exception as e:
                logger.warning(f"Could not fetch work mode: {e}")

            if should_force_discharge and not current_state["force_discharge_active"]:
                # Activate force discharge: SELLING_FIRST with cutoff SoC in window
                logger.info(f"Activating force discharge (SoC: {soc}% -> {cutoff_soc}%)")

                # Set work mode
                mode_result = client.set_work_mode(MODE_FORCE_DISCHARGE)
                if mode_result.get("success"):
                    # Wait for command to complete before sending TOU
                    time.sleep(5)
                    # Set TOU with cutoff SoC during window
                    tou_result = client.set_tou_settings(
                        window_start=window_start,
                        window_end=window_end,
                        min_soc_reserve=min_soc_reserve,
                        window_soc=cutoff_soc,
                        power=max_power,
                        free_energy_start=free_energy_start,
                        free_energy_end=free_energy_end,
                        free_energy_soc=free_energy_soc
                    )
                    if not tou_result.get("success"):
                        logger.warning(f"TOU update failed: {tou_result.get('msg')}")
                    current_state["last_error"] = None
                else:
                    current_state["last_error"] = mode_result.get("msg", "Unknown error")
                    logger.error(f"Failed to set work mode: {mode_result}")

            elif not should_force_discharge and current_state["force_discharge_active"]:
                # Deactivate force discharge: ZERO_EXPORT_TO_CT with reserve SoC everywhere
                reason = "time window ended" if not in_window else f"SoC reached cutoff ({cutoff_soc}%)"
                logger.info(f"Deactivating force discharge ({reason})")

                # Set work mode
                mode_result = client.set_work_mode(MODE_NORMAL)
                if mode_result.get("success"):
                    # Wait for command to complete before sending TOU
                    time.sleep(5)
                    # Set TOU with reserve SoC for all periods
                    tou_result = client.set_tou_settings(
                        window_start=window_start,
                        window_end=window_end,
                        min_soc_reserve=min_soc_reserve,
                        window_soc=min_soc_reserve,
                        power=max_power,
                        free_energy_start=free_energy_start,
                        free_energy_end=free_energy_end,
                        free_energy_soc=free_energy_soc
                    )
                    if not tou_result.get("success"):
                        logger.warning(f"TOU update failed: {tou_result.get('msg')}")
                    current_state["last_error"] = None
                else:
                    current_state["last_error"] = mode_result.get("msg", "Unknown error")
                    logger.error(f"Failed to set work mode: {mode_result}")

        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            current_state["last_error"] = str(e)

        # Check every 30 seconds
        for _ in range(30):
            if not scheduler_running:
                break
            time.sleep(1)

    current_state["scheduler_status"] = "stopped"
    logger.info("Scheduler stopped")


def start_scheduler():
    """Start the scheduler thread"""
    global scheduler_thread, scheduler_running

    if scheduler_running:
        return False

    scheduler_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()
    return True


def stop_scheduler():
    """Stop the scheduler thread"""
    global scheduler_running
    scheduler_running = False
    return True


# --- Flask Routes ---


@app.route('/api/setup/status')
def get_setup_status():
    """Check if initial setup is needed"""
    deye_config = config.get("deye", {})
    
    # Check if Deye credentials are configured
    needs_setup = (
        not deye_config.get("app_id") or 
        deye_config.get("app_id") == "YOUR_APP_ID" or
        not deye_config.get("app_secret") or
        deye_config.get("app_secret") == "YOUR_APP_SECRET" or
        not deye_config.get("email") or
        deye_config.get("email") == "YOUR_EMAIL" or
        not deye_config.get("device_sn") or
        deye_config.get("device_sn") == "YOUR_DEVICE_SN"
    )
    
    return jsonify({
        "needs_setup": needs_setup,
        "deye_configured": not needs_setup
    })


@app.route('/api/setup/test-deye', methods=['POST'])
def test_deye_connection():
    """Test Deye API connection with provided credentials"""
    try:
        body = request.get_json()

        test_client = DeyeCloudClient(
            api_base_url=body.get("api_base_url", "https://eu1-developer.deyecloud.com"),
            app_id=body.get("app_id"),
            app_secret=body.get("app_secret"),
            email=body.get("email"),
            password=body.get("password")
        )

        # Device SN is required
        device_sn = body.get("device_sn")
        if not device_sn:
            return jsonify({
                "success": False,
                "error": "Device serial number is required"
            })

        # Set device_sn on client and test with get_device_latest_data
        test_client.device_sn = device_sn
        result = test_client.get_device_latest_data()

        # Check response
        if result.get("code") in [0, "0", 1000000] or result.get("success") == True:
            device_list = result.get("deviceDataList", [])
            if device_list:
                return jsonify({
                    "success": True,
                    "message": "Connection successful! Device found.",
                    "device_name": device_list[0].get("deviceName") or device_sn
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Device not found or no data available. Check the serial number."
                })
        else:
            return jsonify({
                "success": False,
                "error": f"API error: {result.get('msg', 'Unknown error')}"
            })

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else "unknown"
        if status_code == 401:
            error_msg = "Authentication failed. Check your App ID, App Secret, email and password."
        elif status_code == 404:
            error_msg = "API endpoint not found (404). Check the API base URL is correct for your region."
        else:
            logger.error(f"HTTP error testing Deye connection: {e}")
            error_msg = f"HTTP error {status_code}. Check logs for details."
        return jsonify({"success": False, "error": error_msg})
    except Exception as e:
        logger.error(f"Error testing Deye connection: {e}")
        return jsonify({"success": False, "error": "Connection test failed. Check logs for details."})


@app.route('/api/setup/test-weather', methods=['POST'])
def test_weather_connection():
    """Test weather connection (Open-Meteo - no API key required)"""
    try:
        body = request.get_json()
        latitude = body.get("latitude")
        longitude = body.get("longitude")

        if latitude is None or longitude is None:
            return jsonify({"success": False, "error": "Location coordinates are required"})

        # Test by fetching a forecast for the location
        test_client = WeatherClient(latitude=latitude, longitude=longitude)
        forecast = test_client.get_forecast()

        if forecast.get("success"):
            return jsonify({
                "success": True,
                "message": "Weather service connected successfully!"
            })
        else:
            logger.warning("Weather test failed")
            return jsonify({
                "success": False,
                "error": "Failed to fetch weather data. Check your location settings."
            })

    except Exception as e:
        logger.error(f"Error testing weather connection: {e}")
        return jsonify({"success": False, "error": "Weather test failed. Check logs for details."})


@app.route('/api/setup/search-cities')
def setup_search_cities():
    """Search for cities during setup (no API key required - uses Open-Meteo)"""
    query = request.args.get('q', '')

    if len(query) < 2:
        return jsonify({"success": True, "cities": []})

    cities = WeatherClient.search_cities(query)
    return jsonify({"success": True, "cities": cities})


@app.route('/api/setup/complete', methods=['POST'])
def complete_setup():
    """Save initial setup configuration"""
    global client, weather_client, weather_analyser, solar_client

    try:
        body = request.get_json()

        # Update Deye config
        if "deye" in body:
            deye_data = body["deye"]
            if "deye" not in config:
                config["deye"] = {}

            for key in ["api_base_url", "app_id", "app_secret", "email", "password", "device_sn"]:
                if key in deye_data:
                    config["deye"][key] = deye_data[key]

        # Update Weather config (now uses coordinates instead of API key)
        if "weather" in body:
            weather_data = body["weather"]
            if "weather" not in config:
                config["weather"] = {}

            for key in ["enabled", "city_name", "latitude", "longitude", "timezone"]:
                if key in weather_data:
                    config["weather"][key] = weather_data[key]

            # Enable weather if location provided
            if weather_data.get("latitude") is not None and weather_data.get("longitude") is not None:
                config["weather"]["enabled"] = True

        # Update solar capacity (can come from weather or solar object)
        if "solar" in body:
            solar_data = body["solar"]
            if "weather" not in config:
                config["weather"] = {}
            if solar_data.get("inverter_capacity_kw"):
                config["weather"]["inverter_capacity_kw"] = solar_data["inverter_capacity_kw"]
            if solar_data.get("panel_capacity_kw"):
                config["weather"]["panel_capacity_kw"] = solar_data["panel_capacity_kw"]

        # Set sensible defaults for weather settings
        if "weather" in config:
            if "min_solar_threshold_kwh" not in config["weather"]:
                config["weather"]["min_solar_threshold_kwh"] = 15

        save_config()

        # Clear weather cache to apply new settings
        weather_forecast_cache["forecast"] = None
        weather_forecast_cache["last_update"] = None

        # Reinitialize clients
        init_client()
        init_weather_client()

        return jsonify({"success": True, "message": "Setup completed successfully!"})

    except Exception as e:
        logger.error(f"Error completing setup: {e}")
        return jsonify({"success": False, "error": "Setup failed. Check logs for details."})


@app.route('/')
def index():
    """Serve the main web interface"""
    return render_template('index.html')


@app.route('/api/status')
def get_status():
    """Get current system status including TOU settings from inverter"""
    schedule = config.get("schedule", {})
    weather_config = config.get("weather", {})

    # Fetch TOU settings from inverter
    tou_settings = None
    try:
        tou_data = client.get_tou_settings()
        if tou_data.get("success"):
            tou_settings = {
                "touAction": tou_data.get("touAction"),
                "timeUseSettingItems": tou_data.get("timeUseSettingItems", [])
            }
    except Exception as e:
        logger.warning(f"Could not fetch TOU settings: {e}")

    # Include weather status
    weather_status = {
        "enabled": weather_config.get("enabled", False),
        "skip_active": current_state.get("weather_skip_active", False),
        "skip_reason": current_state.get("weather_skip_reason"),
        "min_solar_threshold_kwh": weather_config.get("min_solar_threshold_kwh", 0)
    }

    # Include free energy status
    free_energy_config = config.get("free_energy", {})
    free_energy_status = {
        "enabled": free_energy_config.get("enabled", False),
        "active": current_state.get("free_energy_active", False),
        "start_time": free_energy_config.get("start_time", "11:00"),
        "end_time": free_energy_config.get("end_time", "14:00"),
        "target_soc": free_energy_config.get("target_soc", 100)
    }

    return jsonify({
        "current_state": current_state,
        "schedule": schedule,
        "in_discharge_window": is_within_discharge_window(),
        "in_free_energy_window": is_within_free_energy_window(),
        "server_time": datetime.now().isoformat(),
        "tou_settings": tou_settings,
        "weather": weather_status,
        "free_energy": free_energy_status
    })


@app.route('/api/device')
def get_device_info():
    """Get device information from Deye"""
    try:
        data = client.get_device_latest_data()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error(f"Error getting device info: {e}")
        return jsonify({"success": False, "error": "Failed to get device info. Check logs for details."}), 500


@app.route('/api/work-mode')
def get_work_mode():
    """Get current work mode from Deye"""
    try:
        data = client.get_work_mode()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error(f"Error getting work mode: {e}")
        return jsonify({"success": False, "error": "Failed to get work mode. Check logs for details."}), 500


@app.route('/api/work-mode', methods=['POST'])
def set_work_mode():
    """Manually set work mode"""
    try:
        body = request.get_json()
        mode = body.get("mode")
        if not mode:
            return jsonify({"success": False, "error": "Mode is required"}), 400

        result = client.set_work_mode(mode)
        if result.get("code") in ["0", 0]:
            current_state["mode"] = mode
            current_state["force_discharge_active"] = (mode == MODE_FORCE_DISCHARGE)
            return jsonify({"success": True, "data": result})
        else:
            return jsonify({"success": False, "error": result.get("msg", "Unknown error")}), 400
    except Exception as e:
        logger.error(f"Error setting work mode: {e}")
        return jsonify({"success": False, "error": "Failed to set work mode. Check logs for details."}), 500


@app.route('/api/tou')
def get_tou():
    """Get TOU settings from Deye"""
    try:
        data = client.get_tou_settings()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error(f"Error getting TOU settings: {e}")
        return jsonify({"success": False, "error": "Failed to get TOU settings. Check logs for details."}), 500


@app.route('/api/config')
def get_config():
    """Get current configuration"""
    # Return config without sensitive data
    safe_config = {
        "schedule": config.get("schedule", {}),
        "device_sn": config.get("deye", {}).get("device_sn")
    }
    return jsonify(safe_config)


@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration and sync TOU to inverter"""
    try:
        body = request.get_json()
        update_tou = body.get("update_tou", False)

        if "schedule" in body:
            config["schedule"] = body["schedule"]

        save_config()

        # If requested, update TOU settings on inverter
        if update_tou:
            schedule = config.get("schedule", {})
            min_soc_reserve = schedule.get("min_soc_reserve", 20)
            cutoff_soc = schedule.get("force_discharge_cutoff_soc", 50)
            max_power = current_state.get("inverter_capacity") or 10000
            window_start = schedule.get("force_discharge_start", "17:30")
            window_end = schedule.get("force_discharge_end", "19:30")

            # Determine window SoC based on current state
            if current_state.get("force_discharge_active"):
                window_soc = cutoff_soc
            else:
                window_soc = min_soc_reserve

            # Get free energy TOU params
            free_energy_start, free_energy_end, free_energy_soc = get_free_energy_tou_params()

            result = client.set_tou_settings(
                window_start=window_start,
                window_end=window_end,
                min_soc_reserve=min_soc_reserve,
                window_soc=window_soc,
                power=max_power,
                free_energy_start=free_energy_start,
                free_energy_end=free_energy_end,
                free_energy_soc=free_energy_soc
            )
            if not result.get("success"):
                return jsonify({"success": False, "error": f"Failed to update TOU: {result.get('msg')}"})

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return jsonify({"success": False, "error": "Failed to update config. Check logs for details."}), 500


@app.route('/api/scheduler/start', methods=['POST'])
def api_start_scheduler():
    """Start the scheduler"""
    if start_scheduler():
        return jsonify({"success": True, "message": "Scheduler started"})
    return jsonify({"success": False, "message": "Scheduler already running"})


@app.route('/api/scheduler/stop', methods=['POST'])
def api_stop_scheduler():
    """Stop the scheduler"""
    stop_scheduler()
    return jsonify({"success": True, "message": "Scheduler stopped"})


@app.route('/api/soc')
def get_soc():
    """Get current battery SoC"""
    try:
        soc = client.get_soc()
        return jsonify({"success": True, "soc": soc})
    except Exception as e:
        logger.error(f"Error getting SoC: {e}")
        return jsonify({"success": False, "error": "Failed to get battery SoC. Check logs for details."}), 500


@app.route('/api/weather')
def get_weather():
    """Get weather forecast"""
    weather_config = config.get("weather", {})

    if not weather_config.get("enabled", False):
        return jsonify({
            "success": True,
            "enabled": False,
            "message": "Weather feature is disabled"
        })

    if not weather_client:
        return jsonify({
            "success": False,
            "enabled": True,
            "error": "Weather client not initialised - check API key and location"
        })

    forecast = get_weather_forecast()
    if not forecast:
        return jsonify({
            "success": False,
            "enabled": True,
            "error": "Failed to fetch weather forecast"
        })

    skip_active, skip_reason = should_skip_discharge_for_weather()

    # Sanitize skip_reason to avoid exposing internal details
    safe_skip_reason = "Weather conditions unfavorable" if skip_active else "Weather OK"

    # Sanitize forecast to only include UI-safe fields
    safe_forecast = {
        "success": True,
        "daily": [],
        "consecutive_bad_days": forecast.get("consecutive_bad_days", 0)
    }
    for day in forecast.get("daily", []):
        safe_day = {
            "date": day.get("date"),
            "day_name": day.get("day_name"),
            "condition": day.get("condition"),
            "icon": day.get("icon"),
            "temp_max": day.get("temp_max"),
            "temp_min": day.get("temp_min"),
            "cloud_cover": day.get("cloud_cover"),
            "precipitation_probability": day.get("precipitation_probability"),
            "is_bad_weather": day.get("is_bad_weather", False),
            "estimated_solar_kwh": day.get("estimated_solar_kwh"),
            "solar_source": day.get("solar_source")
        }
        safe_forecast["daily"].append(safe_day)

    return jsonify({
        "success": True,
        "enabled": True,
        "forecast": safe_forecast,
        "skip_discharge": skip_active,
        "skip_reason": safe_skip_reason,
        "min_solar_threshold_kwh": weather_config.get("min_solar_threshold_kwh", 0),
        "last_update": weather_forecast_cache.get("last_update").isoformat() if weather_forecast_cache.get("last_update") else None
    })


@app.route('/api/weather/config')
def get_weather_config():
    """Get weather configuration"""
    weather_config = config.get("weather", {})
    return jsonify({
        "enabled": weather_config.get("enabled", False),
        "city_name": weather_config.get("city_name", ""),
        "latitude": weather_config.get("latitude"),
        "longitude": weather_config.get("longitude"),
        "timezone": weather_config.get("timezone", "auto"),
        "min_solar_threshold_kwh": weather_config.get("min_solar_threshold_kwh", 0),
        "bad_weather_conditions": weather_config.get("bad_weather_conditions", []),
        "min_cloud_cover_percent": weather_config.get("min_cloud_cover_percent", 70),
        "inverter_capacity_kw": weather_config.get("inverter_capacity_kw", 0),
        "panel_capacity_kw": weather_config.get("panel_capacity_kw", 0),
        "location_configured": weather_config.get("latitude") is not None and weather_config.get("longitude") is not None
    })




@app.route('/api/weather/cities')
def search_cities():
    """Search for cities by name (no API key required - uses Open-Meteo)"""
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({"success": True, "cities": []})

    cities = WeatherClient.search_cities(query)
    return jsonify({"success": True, "cities": cities})


@app.route('/api/weather/config', methods=['POST'])
def update_weather_config():
    """Update weather configuration"""
    global weather_client, weather_analyser, solar_client

    try:
        body = request.get_json()

        if "weather" not in config:
            config["weather"] = {}

        # Update allowed fields
        if "enabled" in body:
            config["weather"]["enabled"] = body["enabled"]
        if "city_name" in body:
            config["weather"]["city_name"] = body["city_name"]
        if "latitude" in body:
            config["weather"]["latitude"] = body["latitude"]
        if "longitude" in body:
            config["weather"]["longitude"] = body["longitude"]
        if "timezone" in body:
            config["weather"]["timezone"] = body["timezone"]
        if "min_solar_threshold_kwh" in body:
            config["weather"]["min_solar_threshold_kwh"] = body["min_solar_threshold_kwh"]
        if "bad_weather_conditions" in body:
            config["weather"]["bad_weather_conditions"] = body["bad_weather_conditions"]
        if "min_cloud_cover_percent" in body:
            config["weather"]["min_cloud_cover_percent"] = body["min_cloud_cover_percent"]
        if "inverter_capacity_kw" in body:
            config["weather"]["inverter_capacity_kw"] = body["inverter_capacity_kw"]
        if "panel_capacity_kw" in body:
            config["weather"]["panel_capacity_kw"] = body["panel_capacity_kw"]

        save_config()

        # Reinitialise weather client with new config
        weather_client = None
        weather_analyser = None
        solar_client = None
        weather_forecast_cache["forecast"] = None
        weather_forecast_cache["last_update"] = None
        init_weather_client()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating weather config: {e}")
        return jsonify({"success": False, "error": "Failed to update weather config. Check logs for details."}), 500


@app.route('/api/free-energy/config')
def get_free_energy_config():
    """Get free energy configuration"""
    free_energy_config = config.get("free_energy", {})
    return jsonify({
        "enabled": free_energy_config.get("enabled", False),
        "start_time": free_energy_config.get("start_time", "11:00"),
        "end_time": free_energy_config.get("end_time", "14:00"),
        "target_soc": free_energy_config.get("target_soc", 100)
    })


@app.route('/api/free-energy/config', methods=['POST'])
def update_free_energy_config():
    """Update free energy configuration"""
    try:
        body = request.get_json()

        if "free_energy" not in config:
            config["free_energy"] = {}

        # Update allowed fields
        if "enabled" in body:
            config["free_energy"]["enabled"] = body["enabled"]
        if "start_time" in body:
            config["free_energy"]["start_time"] = body["start_time"]
        if "end_time" in body:
            config["free_energy"]["end_time"] = body["end_time"]
        if "target_soc" in body:
            config["free_energy"]["target_soc"] = body["target_soc"]

        save_config()

        # If update_tou is requested, sync TOU to inverter with new settings
        if body.get("update_tou", False):
            schedule = config.get("schedule", {})
            min_soc_reserve = schedule.get("min_soc_reserve", 20)
            cutoff_soc = schedule.get("force_discharge_cutoff_soc", 50)
            max_power = current_state.get("inverter_capacity") or 10000
            window_start = schedule.get("force_discharge_start", "17:30")
            window_end = schedule.get("force_discharge_end", "19:30")

            # Determine window SoC based on current state
            if current_state.get("force_discharge_active"):
                window_soc = cutoff_soc
            else:
                window_soc = min_soc_reserve

            # Get free energy TOU params (now with new config)
            free_energy_start, free_energy_end, free_energy_soc = get_free_energy_tou_params()

            result = client.set_tou_settings(
                window_start=window_start,
                window_end=window_end,
                min_soc_reserve=min_soc_reserve,
                window_soc=window_soc,
                power=max_power,
                free_energy_start=free_energy_start,
                free_energy_end=free_energy_end,
                free_energy_soc=free_energy_soc
            )
            if not result.get("success"):
                return jsonify({"success": False, "error": f"Failed to update TOU: {result.get('msg')}"})

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating free energy config: {e}")
        return jsonify({"success": False, "error": "Failed to update free energy config. Check logs for details."}), 500


if __name__ == '__main__':
    load_config()
    init_client()
    init_weather_client()
    start_scheduler()
    app.run(host='0.0.0.0', port=7777, debug=False)
