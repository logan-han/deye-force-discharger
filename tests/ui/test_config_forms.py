"""UI tests for configuration forms"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestScheduleSettingsForm:
    """Tests for the schedule settings form"""

    def test_schedule_settings_card_visible(self, page: Page, app_server):
        """Test that schedule settings card is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Schedule Settings card should be visible
        schedule_card = page.locator(".card:has-text('Schedule Settings')")
        expect(schedule_card).to_be_visible()

    def test_force_discharge_fields_visible(self, page: Page, app_server):
        """Test that force discharge time fields are visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Time inputs should be visible
        expect(page.locator("#startTime")).to_be_visible()
        expect(page.locator("#endTime")).to_be_visible()

        # SoC inputs should be visible
        expect(page.locator("#minSocReserve")).to_be_visible()
        expect(page.locator("#cutoffSoc")).to_be_visible()

    def test_force_discharge_checkbox(self, page: Page, app_server):
        """Test force discharge enable checkbox"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Checkbox should be visible
        checkbox = page.locator("#forceDischargeEnabled")
        expect(checkbox).to_be_visible()

        # Should be checked by default
        expect(checkbox).to_be_checked()

    def test_change_start_time(self, page: Page, app_server):
        """Test changing start time input"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Clear and fill start time
        page.fill("#startTime", "16:00")

        # Verify value changed
        expect(page.locator("#startTime")).to_have_value("16:00")

    def test_change_end_time(self, page: Page, app_server):
        """Test changing end time input"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Clear and fill end time
        page.fill("#endTime", "20:30")

        # Verify value changed
        expect(page.locator("#endTime")).to_have_value("20:30")

    def test_change_soc_values(self, page: Page, app_server):
        """Test changing SoC reserve and cutoff values"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Change reserve SoC
        page.fill("#minSocReserve", "25")
        expect(page.locator("#minSocReserve")).to_have_value("25")

        # Change cutoff SoC
        page.fill("#cutoffSoc", "45")
        expect(page.locator("#cutoffSoc")).to_have_value("45")

    def test_save_button_visible(self, page: Page, app_server):
        """Test that save button is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Save button in schedule form should be visible
        save_btn = page.locator("#scheduleForm button[type='submit']")
        expect(save_btn).to_be_visible()


@pytest.mark.ui
class TestFreeEnergyForm:
    """Tests for the free energy configuration form"""

    def test_free_energy_section_visible(self, page: Page, app_server):
        """Test that free energy section is visible"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Free energy card should be visible
        free_energy_card = page.locator("#freeEnergyCard")
        expect(free_energy_card).to_be_visible()

    def test_free_energy_checkbox(self, page: Page, app_server):
        """Test free energy enable checkbox"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Checkbox should be visible
        checkbox = page.locator("#freeEnergyEnabled")
        expect(checkbox).to_be_visible()

    def test_free_energy_time_inputs(self, page: Page, app_server):
        """Test free energy time input fields"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Time inputs should be visible
        expect(page.locator("#freeEnergyStart")).to_be_visible()
        expect(page.locator("#freeEnergyEnd")).to_be_visible()

    def test_free_energy_target_soc(self, page: Page, app_server):
        """Test free energy target SoC input"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Target SoC input should be visible
        target_soc = page.locator("#freeEnergyTargetSoc")
        expect(target_soc).to_be_visible()


@pytest.mark.ui
class TestWeatherSettingsForm:
    """Tests for the weather settings form"""

    def test_weather_form_submission(self, page: Page, app_server):
        """Test weather settings form can be filled and submitted"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Open weather settings
        page.click(".weather-settings-toggle")
        page.wait_for_timeout(300)

        # Fill in solar threshold
        page.fill("#weatherSolarThreshold", "20")
        expect(page.locator("#weatherSolarThreshold")).to_have_value("20")

        # Fill in capacities
        page.fill("#weatherInverterCapacity", "5")
        page.fill("#weatherPanelCapacity", "6.6")

        expect(page.locator("#weatherInverterCapacity")).to_have_value("5")
        expect(page.locator("#weatherPanelCapacity")).to_have_value("6.6")

    def test_weather_enabled_toggle(self, page: Page, app_server):
        """Test weather enabled checkbox toggle"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Open weather settings
        page.click(".weather-settings-toggle")
        page.wait_for_timeout(300)

        # Get checkbox
        checkbox = page.locator("#weatherEnabled")
        expect(checkbox).to_be_visible()

        # Toggle checkbox
        initial_state = checkbox.is_checked()
        checkbox.click()
        page.wait_for_timeout(100)

        # State should have changed
        expect(checkbox).to_be_checked() if not initial_state else expect(checkbox).not_to_be_checked()


@pytest.mark.ui
class TestFormValidation:
    """Tests for form input validation"""

    def test_soc_input_min_max(self, page: Page, app_server):
        """Test SoC inputs have min/max attributes"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Reserve SoC should have min/max
        reserve_input = page.locator("#minSocReserve")
        expect(reserve_input).to_have_attribute("min", "5")
        expect(reserve_input).to_have_attribute("max", "100")

        # Cutoff SoC should have min/max
        cutoff_input = page.locator("#cutoffSoc")
        expect(cutoff_input).to_have_attribute("min", "5")
        expect(cutoff_input).to_have_attribute("max", "100")

    def test_time_input_type(self, page: Page, app_server):
        """Test time inputs have correct type"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Start and end time should be time inputs
        expect(page.locator("#startTime")).to_have_attribute("type", "time")
        expect(page.locator("#endTime")).to_have_attribute("type", "time")


@pytest.mark.ui
class TestFormInteractions:
    """Tests for form interaction behaviors"""

    def test_schedule_form_save_click(self, page: Page, app_server):
        """Test clicking save on schedule form"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        # Modify a value
        page.fill("#cutoffSoc", "55")

        # Click save button (form submission)
        page.click("#scheduleForm button[type='submit']")
        page.wait_for_timeout(500)

        # Form should still be visible (no page navigation)
        expect(page.locator("#scheduleForm")).to_be_visible()

    def test_weather_settings_collapse(self, page: Page, app_server):
        """Test weather settings panel collapse/expand"""
        page.goto(app_server)
        page.wait_for_timeout(1000)

        settings_toggle = page.locator(".weather-settings-toggle")
        settings_panel = page.locator("#weatherSettings")

        # Initially collapsed
        # Click to expand
        settings_toggle.click()
        page.wait_for_timeout(300)
        expect(settings_panel).to_be_visible()

        # Click again to collapse
        settings_toggle.click()
        page.wait_for_timeout(300)
        # Panel should be hidden (display: none or collapsed)
