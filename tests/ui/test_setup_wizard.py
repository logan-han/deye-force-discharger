"""UI tests for the setup wizard flow"""
import re
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
class TestSetupWizardDisplay:
    """Tests for setup wizard visibility and navigation"""

    def test_setup_wizard_shows_when_unconfigured(self, page: Page, ensure_needs_setup_state):
        """Test that setup wizard appears when app is not configured"""
        page.goto(ensure_needs_setup_state)

        # Wait for the page to check setup status and show modal
        page.wait_for_timeout(1000)

        # Setup overlay should be visible
        setup_overlay = page.locator("#setupOverlay")
        expect(setup_overlay).to_be_visible()

    def test_setup_wizard_hidden_when_configured(self, page: Page, ensure_configured_state):
        """Test that setup wizard is hidden when app is configured"""
        page.goto(ensure_configured_state)

        # Wait for the page to load
        page.wait_for_timeout(1000)

        # Setup overlay should be hidden
        setup_overlay = page.locator("#setupOverlay")
        expect(setup_overlay).to_be_hidden()

    def test_setup_wizard_step_1_fields(self, page: Page, ensure_needs_setup_state):
        """Test that step 1 has all required fields"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Check all Deye credential fields are present
        expect(page.locator("#setupApiUrl")).to_be_visible()
        expect(page.locator("#setupAppId")).to_be_visible()
        expect(page.locator("#setupAppSecret")).to_be_visible()
        expect(page.locator("#setupEmail")).to_be_visible()
        expect(page.locator("#setupPassword")).to_be_visible()
        expect(page.locator("#setupDeviceSn")).to_be_visible()

    def test_setup_wizard_progress_dots(self, page: Page, ensure_needs_setup_state):
        """Test that progress dots show correct state"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # First dot should be active
        dot1 = page.locator("#dot1")
        expect(dot1).to_have_class(re.compile(r"active"))

        # Other dots should not be active yet
        dot2 = page.locator("#dot2")
        dot3 = page.locator("#dot3")
        expect(dot2).not_to_have_class(re.compile(r"active"))
        expect(dot3).not_to_have_class(re.compile(r"active"))


@pytest.mark.ui
class TestSetupWizardNavigation:
    """Tests for setup wizard navigation between steps"""

    def test_navigate_to_step_2(self, page: Page, ensure_needs_setup_state):
        """Test navigation from step 1 to step 2"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Click Next button
        page.click("button:has-text('Next')")
        page.wait_for_timeout(500)

        # Step 2 should be visible
        step2 = page.locator("#setupStep2")
        expect(step2).to_have_class(re.compile(r"active"))

        # Weather API key field should be visible
        expect(page.locator("#setupWeatherKey")).to_be_visible()

    def test_navigate_back_to_step_1(self, page: Page, ensure_needs_setup_state):
        """Test navigation back from step 2 to step 1"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Go to step 2
        page.click("button:has-text('Next')")
        page.wait_for_timeout(500)

        # Click Back button
        page.click("button:has-text('Back')")
        page.wait_for_timeout(500)

        # Step 1 should be visible again
        step1 = page.locator("#setupStep1")
        expect(step1).to_have_class(re.compile(r"active"))

    def test_skip_weather_to_step_3(self, page: Page, ensure_needs_setup_state):
        """Test skipping weather config goes to step 3"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Go to step 2
        page.click("button:has-text('Next')")
        page.wait_for_timeout(500)

        # Click Skip (should go to step 3)
        page.click("button:has-text('Skip')")
        page.wait_for_timeout(500)

        # Step 3 should be visible
        step3 = page.locator("#setupStep3")
        expect(step3).to_have_class(re.compile(r"active"))

        # Solar capacity fields should be visible
        expect(page.locator("#setupInverterCapacity")).to_be_visible()


@pytest.mark.ui
class TestSetupWizardFormInteraction:
    """Tests for form interactions in the setup wizard"""

    def test_fill_deye_credentials(self, page: Page, ensure_needs_setup_state):
        """Test filling in Deye credentials"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Fill in credentials
        page.fill("#setupAppId", "test_app_id")
        page.fill("#setupAppSecret", "test_secret")
        page.fill("#setupEmail", "test@example.com")
        page.fill("#setupPassword", "test_password")
        page.fill("#setupDeviceSn", "ABC123456")

        # Verify values are entered
        expect(page.locator("#setupAppId")).to_have_value("test_app_id")
        expect(page.locator("#setupEmail")).to_have_value("test@example.com")
        expect(page.locator("#setupDeviceSn")).to_have_value("ABC123456")

    def test_api_url_dropdown(self, page: Page, ensure_needs_setup_state):
        """Test API URL dropdown selection"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Change API URL to US region
        page.select_option("#setupApiUrl", "https://us1-developer.deyecloud.com")

        # Verify selection
        expect(page.locator("#setupApiUrl")).to_have_value("https://us1-developer.deyecloud.com")

    def test_solar_capacity_input(self, page: Page, ensure_needs_setup_state):
        """Test solar capacity input in step 3"""
        page.goto(ensure_needs_setup_state)
        page.wait_for_timeout(1000)

        # Navigate to step 3
        page.click("button:has-text('Next')")
        page.wait_for_timeout(300)
        page.click("button:has-text('Skip')")
        page.wait_for_timeout(300)

        # Fill in solar capacity
        page.fill("#setupInverterCapacity", "5")
        page.fill("#setupPanelCapacity", "6.6")

        # Verify values
        expect(page.locator("#setupInverterCapacity")).to_have_value("5")
        expect(page.locator("#setupPanelCapacity")).to_have_value("6.6")
