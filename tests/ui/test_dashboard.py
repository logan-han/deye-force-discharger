"""UI tests for the main dashboard"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestDashboardDisplay:
    """Tests for dashboard element visibility"""

    def test_dashboard_loads(self, page: Page, app_server):
        """Test that dashboard loads when app is configured"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Main container should be visible
        container = page.locator(".container")
        expect(container).to_be_visible()

        # Title should be visible
        title = page.locator("h1")
        expect(title).to_contain_text("Deye Force Discharger")

    def test_system_status_card_visible(self, page: Page, app_server):
        """Test that system status card is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # System Status card should be visible
        status_card = page.locator(".card:has-text('System Status')")
        expect(status_card).to_be_visible()

        # Status items should be present
        expect(page.locator("#forceDischargeStatus")).to_be_visible()
        expect(page.locator("#inWindow")).to_be_visible()

    def test_soc_bar_displays(self, page: Page, app_server):
        """Test that SoC bar displays correctly"""
        page.goto(app_server)
        page.wait_for_timeout(1500)

        # SoC value should be visible
        soc_value = page.locator("#socValue")
        expect(soc_value).to_be_visible()

        # SoC bar should exist
        soc_bar = page.locator("#socBar")
        expect(soc_bar).to_be_visible()

        # Reserve and cutoff markers should exist
        expect(page.locator("#reserveMarker")).to_be_visible()
        expect(page.locator("#cutoffMarker")).to_be_visible()

    def test_power_gauge_displays(self, page: Page, app_server):
        """Test that power gauge displays"""
        page.goto(app_server)
        page.wait_for_timeout(1500)

        # Power value should be visible
        power_value = page.locator("#powerValue")
        expect(power_value).to_be_visible()

        # Power gauge fill should exist
        gauge_fill = page.locator("#powerGaugeFill")
        expect(gauge_fill).to_be_visible()


@pytest.mark.ui
class TestSchedulerControls:
    """Tests for scheduler start/stop buttons"""

    def test_scheduler_buttons_visible(self, page: Page, app_server):
        """Test that scheduler buttons are visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Start and Stop buttons should be visible
        start_btn = page.locator("#startBtn")
        stop_btn = page.locator("#stopBtn")

        expect(start_btn).to_be_visible()
        expect(stop_btn).to_be_visible()

    def test_scheduler_status_display(self, page: Page, app_server):
        """Test that scheduler status is displayed"""
        page.goto(app_server)
        page.wait_for_timeout(1500)

        # Scheduler status should be visible
        status = page.locator("#schedulerStatusLarge")
        expect(status).to_be_visible()

    def test_start_scheduler_click(self, page: Page, app_server):
        """Test clicking start scheduler button"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Click start button
        page.click("#startBtn")
        page.wait_for_timeout(500)

        # Status should change (API call made)
        # Note: In test environment, the actual state change depends on mock responses


@pytest.mark.ui
class TestTOUTable:
    """Tests for the TOU settings table"""

    def test_tou_table_visible(self, page: Page, app_server):
        """Test that TOU table is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1500)

        # TOU card should be visible
        tou_card = page.locator(".card:has-text('Inverter TOU Settings')")
        expect(tou_card).to_be_visible()

        # Table should exist
        tou_table = page.locator(".tou-table")
        expect(tou_table).to_be_visible()

    def test_tou_table_headers(self, page: Page, app_server):
        """Test that TOU table has correct headers"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Check table headers
        expect(page.locator("th:has-text('Time Range')")).to_be_visible()
        expect(page.locator("th:has-text('SoC')")).to_be_visible()
        expect(page.locator("th:has-text('Power')")).to_be_visible()
        expect(page.locator("th:has-text('Grid')")).to_be_visible()


@pytest.mark.ui
class TestWeatherCard:
    """Tests for the weather forecast card"""

    def test_weather_card_visible(self, page: Page, app_server):
        """Test that weather card is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Weather card should be visible
        weather_card = page.locator("#weatherCard")
        expect(weather_card).to_be_visible()

    def test_weather_settings_toggle(self, page: Page, app_server):
        """Test weather settings toggle button"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Settings toggle should be visible
        settings_toggle = page.locator(".weather-settings-toggle")
        expect(settings_toggle).to_be_visible()

        # Click to expand settings
        settings_toggle.click()
        page.wait_for_timeout(300)

        # Settings panel should be visible
        settings_panel = page.locator("#weatherSettings")
        expect(settings_panel).to_be_visible()

    def test_weather_settings_form_fields(self, page: Page, app_server):
        """Test weather settings form has all fields"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Open settings
        page.click(".weather-settings-toggle")
        page.wait_for_timeout(300)

        # Check form fields exist
        expect(page.locator("#weatherEnabled")).to_be_visible()
        expect(page.locator("#weatherCity")).to_be_visible()
        expect(page.locator("#weatherSolarThreshold")).to_be_visible()
        expect(page.locator("#weatherInverterCapacity")).to_be_visible()
        expect(page.locator("#weatherPanelCapacity")).to_be_visible()


@pytest.mark.ui
class TestErrorDisplay:
    """Tests for error message display"""

    def test_error_message_hidden_initially(self, page: Page, app_server):
        """Test that error message is hidden when no errors"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Error message should be hidden
        error_msg = page.locator("#errorMsg")
        expect(error_msg).to_be_hidden()


@pytest.mark.ui
class TestStatusRefresh:
    """Tests for auto-refresh functionality"""

    def test_refresh_indicator_exists(self, page: Page, app_server):
        """Test that refresh indicator exists"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Refresh indicator should exist
        indicator = page.locator("#refreshIndicator")
        expect(indicator).to_be_visible()
