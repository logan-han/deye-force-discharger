import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import hashlib

from deye_client import DeyeCloudClient


class TestDeyeCloudClient:
    """Tests for DeyeCloudClient class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = DeyeCloudClient(
            api_base_url="https://test-api.deyecloud.com",
            app_id="test_app_id",
            app_secret="test_secret",
            email="test@test.com",
            password="test_password",
            device_sn="TEST123456"
        )

    def test_init(self):
        """Test client initialization"""
        assert self.client.api_base_url == "https://test-api.deyecloud.com"
        assert self.client.app_id == "test_app_id"
        assert self.client.app_secret == "test_secret"
        assert self.client.email == "test@test.com"
        assert self.client.password_hash == hashlib.sha256("test_password".encode()).hexdigest()
        assert self.client.device_sn == "TEST123456"
        assert self.client.access_token is None
        assert self.client.token_expires_at == 0

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is stripped from API URL"""
        client = DeyeCloudClient(
            api_base_url="https://test.com/api/",
            app_id="id",
            app_secret="secret",
            email="email",
            password="pass",
            device_sn="sn"
        )
        assert client.api_base_url == "https://test.com/api"

    @patch('deye_client.requests.post')
    def test_get_token_success(self, mock_post):
        """Test successful token acquisition"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "data": {
                "accessToken": "test_token_12345",
                "expiresIn": 86400
            }
        }
        mock_post.return_value = mock_response

        token = self.client._get_token()

        assert token == "test_token_12345"
        assert self.client.access_token == "test_token_12345"
        mock_post.assert_called_once()

    @patch('deye_client.requests.post')
    def test_get_token_uses_cached(self, mock_post):
        """Test that cached token is used when valid"""
        self.client.access_token = "cached_token"
        self.client.token_expires_at = time.time() + 3600  # Expires in 1 hour

        token = self.client._get_token()

        assert token == "cached_token"
        mock_post.assert_not_called()

    @patch('deye_client.requests.post')
    def test_get_token_refreshes_expired(self, mock_post):
        """Test that expired token is refreshed"""
        self.client.access_token = "old_token"
        self.client.token_expires_at = time.time() - 100  # Already expired

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "data": {
                "accessToken": "new_token",
                "expiresIn": 86400
            }
        }
        mock_post.return_value = mock_response

        token = self.client._get_token()

        assert token == "new_token"
        mock_post.assert_called_once()

    @patch('deye_client.requests.post')
    def test_get_token_failure(self, mock_post):
        """Test token acquisition failure"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "code": "500",
            "msg": "Authentication failed"
        }
        mock_post.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            self.client._get_token()

        assert "Authentication failed" in str(exc_info.value)

    @patch('deye_client.requests.post')
    def test_get_token_no_token_in_response(self, mock_post):
        """Test handling when no token in response"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "data": {}
        }
        mock_post.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            self.client._get_token()

        assert "No access token" in str(exc_info.value)

    @patch('deye_client.requests.post')
    def test_get_token_alternative_response_structure(self, mock_post):
        """Test token extraction from alternative response structure"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "success": True,
            "accessToken": "alt_token",
            "expiresIn": 3600
        }
        mock_post.return_value = mock_response

        token = self.client._get_token()

        assert token == "alt_token"

    @patch.object(DeyeCloudClient, '_get_token')
    @patch('deye_client.requests.get')
    def test_make_request_get(self, mock_get, mock_token):
        """Test GET request"""
        mock_token.return_value = "test_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True}
        mock_get.return_value = mock_response

        result = self.client._make_request("GET", "/test/endpoint", {"param": "value"})

        assert result == {"success": True}
        mock_get.assert_called_once()

    @patch.object(DeyeCloudClient, '_get_token')
    @patch('deye_client.requests.post')
    def test_make_request_post(self, mock_post, mock_token):
        """Test POST request"""
        mock_token.return_value = "test_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True}
        mock_post.return_value = mock_response

        result = self.client._make_request("POST", "/test/endpoint", {"data": "value"})

        assert result == {"success": True}
        mock_post.assert_called_once()

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_device_list(self, mock_request):
        """Test get_device_list method"""
        mock_request.return_value = {"devices": []}

        result = self.client.get_device_list()

        mock_request.assert_called_with("POST", "/v1.0/device/list", {"page": 1, "size": 100})
        assert result == {"devices": []}

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_device_info(self, mock_request):
        """Test get_device_info method"""
        mock_request.return_value = {"device": {}}

        result = self.client.get_device_info()

        mock_request.assert_called_with("POST", "/v1.0/device/info", {"deviceSn": "TEST123456"})

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_device_latest_data(self, mock_request):
        """Test get_device_latest_data method"""
        mock_request.return_value = {"data": []}

        result = self.client.get_device_latest_data()

        mock_request.assert_called_with("POST", "/v1.0/device/latest", {"deviceList": ["TEST123456"]})

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_station_latest(self, mock_request):
        """Test get_station_latest method"""
        mock_request.return_value = {"station": {}}

        result = self.client.get_station_latest()

        mock_request.assert_called_with("POST", "/v1.0/station/latest", {"deviceSn": "TEST123456"})

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_work_mode(self, mock_request):
        """Test get_work_mode method"""
        mock_request.return_value = {"systemWorkMode": "SELLING_FIRST"}

        result = self.client.get_work_mode()

        mock_request.assert_called_with("POST", "/v1.0/config/system", {"deviceSn": "TEST123456"})

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_work_mode(self, mock_request):
        """Test set_work_mode method"""
        mock_request.return_value = {"success": True}

        result = self.client.set_work_mode("SELLING_FIRST")

        mock_request.assert_called_with(
            "POST",
            "/v1.0/order/sys/workMode/update",
            {"deviceSn": "TEST123456", "workMode": "SELLING_FIRST"}
        )

    @patch.object(DeyeCloudClient, '_make_request')
    def test_get_tou_settings(self, mock_request):
        """Test get_tou_settings method"""
        mock_request.return_value = {"settings": []}

        result = self.client.get_tou_settings()

        mock_request.assert_called_with("POST", "/v1.0/config/tou", {"deviceSn": "TEST123456"})

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_settings(self, mock_request):
        """Test set_tou_settings method"""
        mock_request.return_value = {"success": True}

        result = self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000
        )

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/v1.0/order/sys/tou/update"
        payload = call_args[0][2]
        assert payload["deviceSn"] == "TEST123456"
        assert len(payload["timeUseSettingItems"]) == 6

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_status_success(self, mock_latest):
        """Test get_battery_status success"""
        mock_latest.return_value = {"success": True, "data": []}

        result = self.client.get_battery_status()

        assert result == {"success": True, "data": []}

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_status_error(self, mock_latest):
        """Test get_battery_status with error"""
        mock_latest.side_effect = Exception("API Error")

        result = self.client.get_battery_status()

        assert "error" in result

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_success(self, mock_latest):
        """Test get_battery_info extracts SOC and power"""
        mock_latest.return_value = {
            "success": True,
            "deviceDataList": [{
                "dataList": [
                    {"key": "SOC", "value": "75.5"},
                    {"key": "BatteryPower", "value": "1500"}
                ]
            }]
        }

        result = self.client.get_battery_info()

        assert result["soc"] == 75.5
        assert result["power"] == 1500.0

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_code_success(self, mock_latest):
        """Test get_battery_info with code-based success"""
        mock_latest.return_value = {
            "code": 1000000,
            "deviceDataList": [{
                "dataList": [
                    {"key": "soc", "value": "80"},
                    {"key": "batterypower", "value": "2000"}
                ]
            }]
        }

        result = self.client.get_battery_info()

        assert result["soc"] == 80.0
        assert result["power"] == 2000.0

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_no_device_data(self, mock_latest):
        """Test get_battery_info with no device data"""
        mock_latest.return_value = {
            "success": True,
            "deviceDataList": []
        }

        result = self.client.get_battery_info()

        assert result["soc"] is None
        assert result["power"] is None

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_error(self, mock_latest):
        """Test get_battery_info with exception"""
        mock_latest.side_effect = Exception("API Error")

        result = self.client.get_battery_info()

        assert result["soc"] is None
        assert result["power"] is None

    @patch.object(DeyeCloudClient, 'get_battery_info')
    def test_get_soc(self, mock_info):
        """Test get_soc method"""
        mock_info.return_value = {"soc": 65.0, "power": 1000}

        result = self.client.get_soc()

        assert result == 65.0

    @patch.object(DeyeCloudClient, 'get_battery_info')
    def test_get_soc_none(self, mock_info):
        """Test get_soc when no SOC available"""
        mock_info.return_value = {"soc": None, "power": None}

        result = self.client.get_soc()

        assert result is None


class TestDeyeCloudClientEdgeCases:
    """Edge case tests for DeyeCloudClient"""

    def test_password_hashing(self):
        """Test that password is properly hashed"""
        password = "my_secure_password"
        expected_hash = hashlib.sha256(password.encode()).hexdigest()

        client = DeyeCloudClient(
            api_base_url="https://test.com",
            app_id="id",
            app_secret="secret",
            email="email",
            password=password,
            device_sn="sn"
        )

        assert client.password_hash == expected_hash

    @patch('deye_client.requests.post')
    def test_token_with_access_token_key(self, mock_post):
        """Test token extraction with access_token key (underscore)"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "code": "0",
            "data": {
                "access_token": "underscore_token",
                "expires_in": 3600
            }
        }
        mock_post.return_value = mock_response

        client = DeyeCloudClient(
            api_base_url="https://test.com",
            app_id="id",
            app_secret="secret",
            email="email",
            password="pass",
            device_sn="sn"
        )

        token = client._get_token()

        assert token == "underscore_token"

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_missing_keys(self, mock_latest):
        """Test get_battery_info with missing data keys"""
        mock_latest.return_value = {
            "success": True,
            "deviceDataList": [{
                "dataList": [
                    {"key": "OTHER_KEY", "value": "123"}
                ]
            }]
        }

        client = DeyeCloudClient(
            api_base_url="https://test.com",
            app_id="id",
            app_secret="secret",
            email="email",
            password="pass",
            device_sn="sn"
        )

        result = client.get_battery_info()

        assert result["soc"] is None
        assert result["power"] is None

    @patch.object(DeyeCloudClient, 'get_device_latest_data')
    def test_get_battery_info_empty_values(self, mock_latest):
        """Test get_battery_info with empty values"""
        mock_latest.return_value = {
            "success": True,
            "deviceDataList": [{
                "dataList": [
                    {"key": "SOC", "value": ""},
                    {"key": "BatteryPower", "value": None}
                ]
            }]
        }

        client = DeyeCloudClient(
            api_base_url="https://test.com",
            app_id="id",
            app_secret="secret",
            email="email",
            password="pass",
            device_sn="sn"
        )

        result = client.get_battery_info()

        assert result["soc"] is None
        assert result["power"] is None


class TestSetTouSettingsWithFreeEnergy:
    """Tests for set_tou_settings with free energy window parameters"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = DeyeCloudClient(
            api_base_url="https://test-api.deyecloud.com",
            app_id="test_app_id",
            app_secret="test_secret",
            email="test@test.com",
            password="test_password",
            device_sn="TEST123456"
        )

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_without_free_energy(self, mock_request):
        """Test set_tou_settings without free energy params (backward compatible)"""
        mock_request.return_value = {"success": True}

        result = self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000
        )

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Should have 6 time periods
        assert len(payload["timeUseSettingItems"]) == 6

        # All should have enableGridCharge = False
        for item in payload["timeUseSettingItems"]:
            assert item["enableGridCharge"] is False

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_with_free_energy_enabled(self, mock_request):
        """Test set_tou_settings with free energy params"""
        mock_request.return_value = {"success": True}

        result = self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000,
            free_energy_start="11:00",
            free_energy_end="14:00",
            free_energy_soc=100
        )

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Should have 6 time periods with free energy
        assert len(payload["timeUseSettingItems"]) == 6

        # Find the free energy period (11:00)
        free_energy_period = None
        for item in payload["timeUseSettingItems"]:
            if item["time"] == "11:00":
                free_energy_period = item
                break

        assert free_energy_period is not None
        assert free_energy_period["enableGridCharge"] is True
        assert free_energy_period["soc"] == 100

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_free_energy_period_structure(self, mock_request):
        """Test that free energy period has correct structure"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=5000,
            free_energy_start="10:00",
            free_energy_end="13:00",
            free_energy_soc=90
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Find periods by time
        periods_by_time = {item["time"]: item for item in payload["timeUseSettingItems"]}

        # Free energy start period
        assert periods_by_time["10:00"]["enableGridCharge"] is True
        assert periods_by_time["10:00"]["soc"] == 90
        assert periods_by_time["10:00"]["power"] == 5000
        assert periods_by_time["10:00"]["enableGeneration"] is False

        # Free energy end period (grid charge off)
        assert periods_by_time["13:00"]["enableGridCharge"] is False
        assert periods_by_time["13:00"]["soc"] == 20  # min_soc_reserve

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_with_none_free_energy_params(self, mock_request):
        """Test set_tou_settings with explicit None free energy params"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000,
            free_energy_start=None,
            free_energy_end=None,
            free_energy_soc=None
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Should use non-free-energy structure (all grid charge off)
        for item in payload["timeUseSettingItems"]:
            assert item["enableGridCharge"] is False

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_partial_free_energy_params(self, mock_request):
        """Test that partial free energy params result in disabled free energy"""
        mock_request.return_value = {"success": True}

        # Only start time, missing end and soc
        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000,
            free_energy_start="11:00",
            free_energy_end=None,
            free_energy_soc=None
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Should use non-free-energy structure (all grid charge off)
        for item in payload["timeUseSettingItems"]:
            assert item["enableGridCharge"] is False

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_free_energy_custom_target_soc(self, mock_request):
        """Test free energy with custom target SoC (e.g., 90% for battery longevity)"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000,
            free_energy_start="11:00",
            free_energy_end="14:00",
            free_energy_soc=90  # 90% instead of 100%
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        # Find the free energy period
        free_energy_period = next(
            item for item in payload["timeUseSettingItems"]
            if item["time"] == "11:00"
        )

        assert free_energy_period["soc"] == 90
        assert free_energy_period["enableGridCharge"] is True

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_preserves_discharge_window_with_free_energy(self, mock_request):
        """Test that discharge window settings are preserved with free energy"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=8000,
            free_energy_start="11:00",
            free_energy_end="14:00",
            free_energy_soc=100
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]
        periods_by_time = {item["time"]: item for item in payload["timeUseSettingItems"]}

        # Discharge window should still be configured correctly
        assert periods_by_time["17:30"]["soc"] == 50  # window_soc
        assert periods_by_time["17:30"]["enableGridCharge"] is False
        assert periods_by_time["19:30"]["soc"] == 20  # min_soc_reserve
        assert periods_by_time["19:30"]["enableGridCharge"] is False

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_all_periods_have_correct_power(self, mock_request):
        """Test that all periods have the same power setting"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=7500,
            free_energy_start="11:00",
            free_energy_end="14:00",
            free_energy_soc=100
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        for item in payload["timeUseSettingItems"]:
            assert item["power"] == 7500

    @patch.object(DeyeCloudClient, '_make_request')
    def test_set_tou_generation_disabled_everywhere(self, mock_request):
        """Test that enableGeneration is False for all periods"""
        mock_request.return_value = {"success": True}

        self.client.set_tou_settings(
            window_start="17:30",
            window_end="19:30",
            min_soc_reserve=20,
            window_soc=50,
            power=10000,
            free_energy_start="11:00",
            free_energy_end="14:00",
            free_energy_soc=100
        )

        call_args = mock_request.call_args
        payload = call_args[0][2]

        for item in payload["timeUseSettingItems"]:
            assert item["enableGeneration"] is False
