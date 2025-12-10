import hashlib
import requests
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DeyeCloudClient:
    """Client for Deye Cloud API"""

    def __init__(self, api_base_url: str, app_id: str, app_secret: str,
                 email: str, password: str, device_sn: str):
        self.api_base_url = api_base_url.rstrip('/')
        self.app_id = app_id
        self.app_secret = app_secret
        self.email = email
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
        self.device_sn = device_sn

        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0

    def _get_token(self) -> str:
        """Get or refresh access token"""
        if self.access_token and time.time() < self.token_expires_at - 300:
            return self.access_token

        url = f"{self.api_base_url}/v1.0/account/token"
        payload = {
            "appSecret": self.app_secret,
            "email": self.email,
            "password": self.password_hash
        }
        params = {"appId": self.app_id}

        logger.info("Requesting new access token")
        response = requests.post(url, json=payload, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        logger.debug(f"Token response: {data}")

        # Handle different success indicators from Deye API
        code = data.get("code")
        success = data.get("success", False)
        if code not in ["0", 0, None] and not success:
            raise Exception(f"Token request failed: {data.get('msg', 'Unknown error')}")

        # Extract token from various possible response structures
        token_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        self.access_token = (
            token_data.get("accessToken") or
            token_data.get("access_token") or
            data.get("accessToken") or
            data.get("access_token")
        )

        if not self.access_token:
            logger.error(f"No access token in response: {data}")
            raise Exception(f"No access token in response: {data}")

        expires_in = token_data.get("expiresIn") or token_data.get("expires_in") or data.get("expiresIn", 86400)
        self.token_expires_at = time.time() + int(expires_in)

        logger.info(f"Token obtained, expires in {expires_in} seconds")
        return self.access_token

    def _make_request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        """Make authenticated API request"""
        token = self._get_token()
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        logger.debug(f"Making {method} request to {url}")

        if method.upper() == "GET":
            response = requests.get(url, headers=headers, params=payload, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=30)

        response.raise_for_status()
        return response.json()

    def get_device_list(self) -> Dict[str, Any]:
        """Get list of devices"""
        return self._make_request("POST", "/v1.0/device/list", {
            "page": 1,
            "size": 100
        })

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information"""
        return self._make_request("POST", "/v1.0/device", {
            "deviceSn": self.device_sn
        })

    def get_device_latest_data(self) -> Dict[str, Any]:
        """Get latest device data including SoC"""
        return self._make_request("POST", "/v1.0/device/latest", {
            "deviceList": [self.device_sn]
        })

    def get_station_latest(self) -> Dict[str, Any]:
        """Get latest station data"""
        return self._make_request("POST", "/v1.0/station/latest", {
            "deviceSn": self.device_sn
        })

    def get_work_mode(self) -> Dict[str, Any]:
        """Get current work mode settings"""
        return self._make_request("POST", "/v1.0/config/system", {
            "deviceSn": self.device_sn
        })

    def set_work_mode(self, mode: str) -> Dict[str, Any]:
        """
        Set system work mode

        Valid modes:
        - SELLING_FIRST: Force discharge to grid
        - ZERO_EXPORT_TO_CT: Zero export mode (discharge based on load)
        - ZERO_EXPORT_TO_LOAD: Zero export to load
        """
        logger.info(f"Setting work mode to: {mode}")
        return self._make_request("POST", "/v1.0/order/sys/workMode/update", {
            "deviceSn": self.device_sn,
            "sysWorkMode": mode
        })

    def get_tou_settings(self) -> Dict[str, Any]:
        """Get Time of Use settings"""
        return self._make_request("POST", "/v1.0/config/tou", {
            "deviceSn": self.device_sn
        })

    def set_tou_settings(
        self,
        window_start: str,
        window_end: str,
        min_soc_reserve: int,
        window_soc: int,
        power: int
    ) -> Dict[str, Any]:
        """
        Update TOU settings on inverter with 3 time periods

        Args:
            window_start: Force discharge window start time (HH:MM)
            window_end: Force discharge window end time (HH:MM)
            min_soc_reserve: SoC for periods outside the window
            window_soc: SoC for the discharge window period
            power: Max discharge power in watts
        """
        logger.info(f"Setting TOU: window={window_start}-{window_end}, reserve_soc={min_soc_reserve}, window_soc={window_soc}, power={power}")
        payload = {
            "deviceSn": self.device_sn,
            "timeUseSettingItems": [
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": min_soc_reserve,
                    "time": "00:00"
                },
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": min_soc_reserve,
                    "time": "06:00"
                },
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": min_soc_reserve,
                    "time": "12:00"
                },
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": window_soc,
                    "time": window_start
                },
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": min_soc_reserve,
                    "time": window_end
                },
                {
                    "enableGeneration": False,
                    "enableGridCharge": False,
                    "power": power,
                    "soc": min_soc_reserve,
                    "time": "23:00"
                }
            ]
        }
        return self._make_request("POST", "/v1.0/order/sys/tou/update", payload)

    def get_battery_status(self) -> Dict[str, Any]:
        """Get battery status and SoC"""
        try:
            data = self.get_device_latest_data()
            return data
        except Exception as e:
            logger.error(f"Failed to get battery status: {e}")
            return {"error": str(e)}

    def get_battery_info(self) -> Dict[str, Any]:
        """Get battery SoC and power"""
        result = {"soc": None, "power": None}
        try:
            data = self.get_device_latest_data()

            if data.get("success") or data.get("code") == 1000000:
                device_data_list = data.get("deviceDataList", [])
                if not device_data_list:
                    logger.warning("No device data in response")
                    return result

                device_data = device_data_list[0]
                data_list = device_data.get("dataList", [])

                for item in data_list:
                    key = (item.get("key") or "").upper()
                    value = item.get("value")
                    if key == "SOC":
                        result["soc"] = float(value) if value else None
                    elif key == "BATTERYPOWER":
                        result["power"] = float(value) if value else None

        except Exception as e:
            logger.error(f"Failed to get battery info: {e}")
        return result

    def get_soc(self) -> Optional[float]:
        """Get current State of Charge percentage"""
        return self.get_battery_info().get("soc")
