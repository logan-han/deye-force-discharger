import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from deye_client import DeyeCloudClient

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
scheduler_thread: threading.Thread = None
scheduler_running = False
current_state = {
    "mode": "unknown",
    "soc": None,
    "battery_power": None,
    "force_discharge_active": False,
    "force_charge_active": False,
    "last_check": None,
    "last_error": None,
    "scheduler_status": "stopped"
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
    """Initialize Deye client"""
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
    logger.info("Deye client initialized")

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


def is_within_charge_window() -> bool:
    """Check if current time is within force charge window"""
    schedule = config.get("schedule", {})
    start_time_str = schedule.get("force_charge_start")
    end_time_str = schedule.get("force_charge_end")

    # If not configured, return False
    if not start_time_str or not end_time_str:
        return False

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


def update_tou_settings():
    """Update TOU settings on inverter based on current state"""
    schedule = config.get("schedule", {})

    min_soc_reserve = schedule.get("min_soc_reserve", 20)
    cutoff_soc = schedule.get("force_discharge_cutoff_soc", 50)
    max_power = schedule.get("max_discharge_power", 10000)
    window_start = schedule.get("force_discharge_start", "17:30")
    window_end = schedule.get("force_discharge_end", "19:30")

    # Force charge settings
    charge_start = schedule.get("force_charge_start")
    charge_end = schedule.get("force_charge_end")
    charge_target_soc = schedule.get("force_charge_target_soc")

    # Determine discharge window SoC based on current state
    if current_state.get("force_discharge_active"):
        discharge_window_soc = cutoff_soc
    else:
        discharge_window_soc = min_soc_reserve

    # Determine charge settings based on current state
    if current_state.get("force_charge_active") and charge_start and charge_end and charge_target_soc:
        active_charge_start = charge_start
        active_charge_end = charge_end
        active_charge_soc = charge_target_soc
    else:
        active_charge_start = None
        active_charge_end = None
        active_charge_soc = None

    return client.set_tou_settings(
        window_start=window_start,
        window_end=window_end,
        min_soc_reserve=min_soc_reserve,
        window_soc=discharge_window_soc,
        power=max_power,
        charge_window_start=active_charge_start,
        charge_window_end=active_charge_end,
        charge_target_soc=active_charge_soc
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
            max_power = schedule.get("max_discharge_power", 10000)

            # Force charge settings
            charge_target_soc = schedule.get("force_charge_target_soc")

            # Get current battery info
            battery_info = client.get_battery_info()
            soc = battery_info.get("soc")
            current_state["soc"] = soc
            current_state["battery_power"] = battery_info.get("power")
            current_state["last_check"] = datetime.now().isoformat()

            # Check if features are enabled
            discharge_enabled = schedule.get("force_discharge_enabled", True)
            charge_enabled = schedule.get("force_charge_enabled", True)

            in_discharge_window = is_within_discharge_window()
            in_charge_window = is_within_charge_window()

            logger.info(f"Check: discharge_enabled={discharge_enabled}, charge_enabled={charge_enabled}, "
                       f"discharge_window={in_discharge_window}, charge_window={in_charge_window}, "
                       f"soc={soc}, cutoff={cutoff_soc}, charge_target={charge_target_soc}, reserve={min_soc_reserve}")

            # Determine if we should be in force discharge mode
            # Force discharge when: enabled AND in window AND SoC above cutoff
            should_force_discharge = (
                discharge_enabled and
                in_discharge_window and
                (soc is None or soc > cutoff_soc)
            )

            # Determine if we should be in force charge mode
            # Force charge when: enabled AND in window AND SoC below target (if target configured)
            should_force_charge = (
                charge_enabled and
                in_charge_window and
                charge_target_soc is not None and
                (soc is None or soc < charge_target_soc)
            )

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

            # Track if TOU needs update
            tou_needs_update = False

            # Handle force discharge state changes
            if should_force_discharge and not current_state["force_discharge_active"]:
                # Activate force discharge: SELLING_FIRST with cutoff SoC in window
                logger.info(f"Activating force discharge (SoC: {soc}% -> {cutoff_soc}%)")

                # Set work mode
                mode_result = client.set_work_mode(MODE_FORCE_DISCHARGE)
                if mode_result.get("success"):
                    current_state["force_discharge_active"] = True
                    tou_needs_update = True
                    current_state["last_error"] = None
                else:
                    current_state["last_error"] = mode_result.get("msg", "Unknown error")
                    logger.error(f"Failed to set work mode: {mode_result}")

            elif not should_force_discharge and current_state["force_discharge_active"]:
                # Deactivate force discharge: ZERO_EXPORT_TO_CT with reserve SoC everywhere
                reason = "time window ended" if not in_discharge_window else f"SoC reached cutoff ({cutoff_soc}%)"
                logger.info(f"Deactivating force discharge ({reason})")

                # Set work mode
                mode_result = client.set_work_mode(MODE_NORMAL)
                if mode_result.get("success"):
                    current_state["force_discharge_active"] = False
                    tou_needs_update = True
                    current_state["last_error"] = None
                else:
                    current_state["last_error"] = mode_result.get("msg", "Unknown error")
                    logger.error(f"Failed to set work mode: {mode_result}")

            # Handle force charge state changes (no mode change needed, just TOU update)
            if should_force_charge and not current_state["force_charge_active"]:
                logger.info(f"Activating force charge (SoC: {soc}% -> {charge_target_soc}%)")
                current_state["force_charge_active"] = True
                tou_needs_update = True
                current_state["last_error"] = None

            elif not should_force_charge and current_state["force_charge_active"]:
                reason = "time window ended" if not in_charge_window else f"SoC reached target ({charge_target_soc}%)"
                logger.info(f"Deactivating force charge ({reason})")
                current_state["force_charge_active"] = False
                tou_needs_update = True
                current_state["last_error"] = None

            # Update TOU if state changed
            if tou_needs_update:
                time.sleep(5)  # Wait for mode change to complete
                tou_result = update_tou_settings()
                if not tou_result.get("success"):
                    logger.warning(f"TOU update failed: {tou_result.get('msg')}")

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

@app.route('/')
def index():
    """Serve the main web interface"""
    return render_template('index.html')


@app.route('/api/status')
def get_status():
    """Get current system status including TOU settings from inverter"""
    schedule = config.get("schedule", {})

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

    return jsonify({
        "current_state": current_state,
        "schedule": schedule,
        "in_discharge_window": is_within_discharge_window(),
        "in_charge_window": is_within_charge_window(),
        "server_time": datetime.now().isoformat(),
        "tou_settings": tou_settings
    })


@app.route('/api/device')
def get_device_info():
    """Get device information from Deye"""
    try:
        data = client.get_device_latest_data()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/work-mode')
def get_work_mode():
    """Get current work mode from Deye"""
    try:
        data = client.get_work_mode()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tou')
def get_tou():
    """Get TOU settings from Deye"""
    try:
        data = client.get_tou_settings()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
def update_config_route():
    """Update configuration and sync TOU to inverter"""
    try:
        body = request.get_json()
        should_update_tou = body.get("update_tou", False)

        if "schedule" in body:
            config["schedule"] = body["schedule"]

        save_config()

        # If requested, update TOU settings on inverter
        if should_update_tou:
            result = update_tou_settings()
            if not result.get("success"):
                return jsonify({"success": False, "error": f"Failed to update TOU: {result.get('msg')}"})

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    load_config()
    init_client()
    start_scheduler()
    app.run(host='0.0.0.0', port=7777, debug=False)
