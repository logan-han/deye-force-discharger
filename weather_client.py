import requests
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class WeatherAPIError(Exception):
    """Custom exception for weather API errors"""

    def __init__(self, message: str, is_temporary: bool = False, status_code: int = None):
        super().__init__(message)
        self.message = message
        self.is_temporary = is_temporary  # True for errors that may resolve on retry
        self.status_code = status_code

    def __str__(self):
        return self.message


class WeatherClient:
    """Client for Open-Meteo API to fetch weather forecasts (no API key required)"""

    def __init__(self, latitude: float, longitude: float, timezone_str: str = "auto"):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_str = timezone_str
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        self._cache = {}
        self._cache_time = None
        self._cache_duration = 300  # 5 minutes cache

    @staticmethod
    def search_cities(query: str, limit: int = 5) -> List[Dict]:
        """Search for cities by name using Open-Meteo Geocoding API (no API key needed)."""
        if not query or len(query) < 2:
            return []

        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": query,
            "count": limit,
            "language": "en",
            "format": "json"
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            cities = []
            for item in results:
                city = {
                    "name": item.get("name", ""),
                    "country": item.get("country", ""),
                    "state": item.get("admin1", ""),  # admin1 is state/province
                    "lat": item.get("latitude"),
                    "lon": item.get("longitude"),
                    "timezone": item.get("timezone", "auto")
                }
                display_parts = [city["name"]]
                if city["state"]:
                    display_parts.append(city["state"])
                if city["country"]:
                    display_parts.append(city["country"])
                city["display_name"] = ", ".join(display_parts)
                cities.append(city)
            return cities
        except Exception as e:
            logger.error(f"City search error: {e}")
            return []

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self._cache_time:
            return False
        return (datetime.now() - self._cache_time).total_seconds() < self._cache_duration

    def _make_request_with_retry(self, url: str, params: dict, max_retries: int = 2) -> requests.Response:
        """
        Make an HTTP request with retry logic for transient errors.
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=30)

                # Handle rate limiting with retry
                if response.status_code == 429:
                    if attempt < max_retries:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        wait_time = min(retry_after, 60)
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        "Open-Meteo API rate limit exceeded",
                        is_temporary=True,
                        status_code=429
                    )

                # Server errors - retry
                if response.status_code >= 500:
                    if attempt < max_retries:
                        wait_time = 2 ** attempt
                        logger.warning(f"Server error {response.status_code}, retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        f"Open-Meteo API server error (HTTP {response.status_code})",
                        is_temporary=True,
                        status_code=response.status_code
                    )

                return response

            except requests.exceptions.Timeout as e:
                last_error = e
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Request timeout, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                raise WeatherAPIError(
                    "Open-Meteo API request timed out",
                    is_temporary=True
                )

            except requests.exceptions.ConnectionError as e:
                last_error = e
                error_str = str(e).lower()

                if "name or service not known" in error_str or "getaddrinfo" in error_str or "nodename nor servname" in error_str:
                    if attempt < max_retries:
                        wait_time = 2 ** attempt
                        logger.warning(f"DNS resolution failed, retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        "Unable to resolve Open-Meteo API hostname (DNS failure)",
                        is_temporary=True
                    )

                if "connection refused" in error_str:
                    raise WeatherAPIError(
                        "Connection to Open-Meteo API refused",
                        is_temporary=True
                    )

                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Connection error, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                raise WeatherAPIError(
                    f"Unable to connect to Open-Meteo API: {e}",
                    is_temporary=True
                )

            except requests.exceptions.RequestException as e:
                raise WeatherAPIError(
                    f"Open-Meteo API request failed: {e}",
                    is_temporary=False
                )

        raise WeatherAPIError(
            f"Open-Meteo API request failed after {max_retries + 1} attempts",
            is_temporary=True
        )

    def get_forecast(self) -> Dict[str, Any]:
        """
        Get 4-day weather forecast with hourly data for solar predictions.
        Uses Open-Meteo free API (no API key required).
        """
        if self._is_cache_valid() and "forecast" in self._cache:
            logger.debug("Using cached forecast data")
            return self._cache["forecast"]

        try:
            params = {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "hourly": "temperature_2m,cloud_cover,precipitation_probability,precipitation,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum,precipitation_probability_max",
                "timezone": self.timezone_str,
                "forecast_days": 4
            }

            logger.info("Fetching weather forecast from Open-Meteo")
            response = self._make_request_with_retry(self.base_url, params)

            if response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("reason", "Invalid request")
                logger.error(f"Open-Meteo API error: {error_msg}")
                return {"success": False, "error": error_msg, "daily": [], "is_temporary": False}

            response.raise_for_status()
            data = response.json()

            forecast = self._parse_forecast(data)
            self._cache["forecast"] = forecast
            self._cache_time = datetime.now()

            return forecast

        except WeatherAPIError as e:
            logger.error(f"Weather API error: {e}")
            return {
                "success": False,
                "error": str(e),
                "daily": [],
                "is_temporary": e.is_temporary
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching weather forecast: {e}")
            return {
                "success": False,
                "error": "Unexpected error fetching forecast. Check logs for details.",
                "daily": [],
                "is_temporary": False
            }

    def _parse_forecast(self, data: Dict) -> Dict[str, Any]:
        """Parse Open-Meteo API response into daily forecast format"""
        daily_data = data.get("daily", {})
        hourly_data = data.get("hourly", {})

        # Store hourly data for solar calculations
        hourly_by_date = {}
        hourly_times = hourly_data.get("time", [])
        hourly_clouds = hourly_data.get("cloud_cover", [])
        hourly_precip_prob = hourly_data.get("precipitation_probability", [])
        hourly_weather_codes = hourly_data.get("weather_code", [])

        for i, time_str in enumerate(hourly_times):
            dt = datetime.fromisoformat(time_str)
            date_key = dt.strftime("%Y-%m-%d")
            hour = dt.hour

            if date_key not in hourly_by_date:
                hourly_by_date[date_key] = []

            hourly_by_date[date_key].append({
                "hour": hour,
                "clouds": hourly_clouds[i] if i < len(hourly_clouds) else 0,
                "condition": self._weather_code_to_condition(hourly_weather_codes[i] if i < len(hourly_weather_codes) else 0),
                "pop": hourly_precip_prob[i] if i < len(hourly_precip_prob) else 0,
                "hours": 1
            })

        self._cache["hourly_data"] = hourly_by_date
        logger.debug(f"Cached hourly weather data for {len(hourly_by_date)} days")

        # Build daily forecasts
        daily_forecasts = []
        dates = daily_data.get("time", [])
        temp_maxs = daily_data.get("temperature_2m_max", [])
        temp_mins = daily_data.get("temperature_2m_min", [])
        weather_codes = daily_data.get("weather_code", [])
        precip_sums = daily_data.get("precipitation_sum", [])
        precip_probs = daily_data.get("precipitation_probability_max", [])

        today = datetime.now().strftime("%Y-%m-%d")

        for i, date_str in enumerate(dates[:4]):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weather_code = weather_codes[i] if i < len(weather_codes) else 0
            condition = self._weather_code_to_condition(weather_code)

            # Calculate average cloud cover for the day from hourly data
            day_hourly = hourly_by_date.get(date_str, [])
            avg_clouds = 0
            if day_hourly:
                cloud_values = [h["clouds"] for h in day_hourly if 6 <= h["hour"] <= 18]
                if cloud_values:
                    avg_clouds = int(sum(cloud_values) / len(cloud_values))

            daily_forecasts.append({
                "date": date_str,
                "day_name": dt.strftime("%A"),
                "is_today": date_str == today,
                "temp_min": temp_mins[i] if i < len(temp_mins) else None,
                "temp_max": temp_maxs[i] if i < len(temp_maxs) else None,
                "condition": condition,
                "description": condition.lower(),
                "icon": self._condition_to_icon(condition),
                "clouds": avg_clouds,
                "pop": int(precip_probs[i]) if i < len(precip_probs) else 0,
                "rain": precip_sums[i] if i < len(precip_sums) else 0,
                "uvi": 0,
                "is_bad_weather": False
            })

        return {
            "success": True,
            "location": f"{self.latitude}, {self.longitude}",
            "current": daily_forecasts[0] if daily_forecasts else {},
            "daily": daily_forecasts
        }

    def _weather_code_to_condition(self, code: int) -> str:
        """Convert WMO weather code to condition string"""
        # WMO Weather interpretation codes (WW)
        # https://open-meteo.com/en/docs
        if code == 0:
            return "Clear"
        elif code in [1, 2, 3]:
            return "Clouds"
        elif code in [45, 48]:
            return "Fog"
        elif code in [51, 53, 55]:
            return "Drizzle"
        elif code in [56, 57]:
            return "Drizzle"  # Freezing drizzle
        elif code in [61, 63, 65]:
            return "Rain"
        elif code in [66, 67]:
            return "Rain"  # Freezing rain
        elif code in [71, 73, 75, 77]:
            return "Snow"
        elif code in [80, 81, 82]:
            return "Rain"  # Showers
        elif code in [85, 86]:
            return "Snow"  # Snow showers
        elif code in [95, 96, 99]:
            return "Thunderstorm"
        else:
            return "Clouds"

    def _condition_to_icon(self, condition: str) -> str:
        """Get icon code for condition"""
        icon_map = {
            "Clear": "01d",
            "Clouds": "03d",
            "Rain": "10d",
            "Drizzle": "09d",
            "Thunderstorm": "11d",
            "Snow": "13d",
            "Fog": "50d"
        }
        return icon_map.get(condition, "01d")

    def estimate_solar_output_hourly(self, panel_capacity_kw: float, date_str: str) -> Optional[float]:
        """
        Estimate daily solar output using hourly forecast data.
        Only counts production during daylight hours with hour-specific factors.
        """
        if "hourly_data" not in self._cache:
            logger.debug("No hourly_data in cache for solar estimate")
            return None

        hourly_data = self._cache["hourly_data"].get(date_str, [])
        if not hourly_data:
            logger.debug("No hourly data available for the requested date")
            return None

        # Base daily production varies by latitude
        lat = abs(self.latitude) if self.latitude else 35
        if lat < 15:
            base_kwh_per_kw = 5.8
        elif lat < 25:
            base_kwh_per_kw = 5.3
        elif lat < 35:
            base_kwh_per_kw = 4.8
        elif lat < 45:
            base_kwh_per_kw = 4.3
        else:
            base_kwh_per_kw = 3.8

        # Hour-based solar intensity factors
        hour_weights = {
            6: 0.02, 7: 0.05, 8: 0.08, 9: 0.11,
            10: 0.13, 11: 0.14, 12: 0.14, 13: 0.14,
            14: 0.13, 15: 0.11, 16: 0.08, 17: 0.05, 18: 0.02
        }

        condition_factors = {
            "Rain": 0.25, "Drizzle": 0.35, "Thunderstorm": 0.1,
            "Snow": 0.15, "Fog": 0.4
        }

        base_daily_kwh = panel_capacity_kw * base_kwh_per_kw
        total_kwh = 0.0
        hours_with_data = set()

        for entry in hourly_data:
            hour = entry.get("hour", 12)
            clouds = entry.get("clouds", 0)
            condition = entry.get("condition", "Clear")
            pop = entry.get("pop", 0)

            if hour < 6 or hour > 18:
                continue

            hour_weight = hour_weights.get(hour, 0)
            if hour_weight == 0:
                continue

            hours_with_data.add(hour)

            # Cloud impact
            cloud_factor = 1.0 - (clouds / 100 * 0.75)

            if condition in condition_factors:
                cond_factor = condition_factors[condition]
                weather_factor = min(cloud_factor, cond_factor)
            else:
                weather_factor = cloud_factor

            pop_factor = 1.0 - (pop / 100 * 0.3)
            weather_factor *= pop_factor

            period_kwh = base_daily_kwh * hour_weight * weather_factor
            total_kwh += period_kwh

        if len(hours_with_data) < 1:
            return None

        return round(total_kwh, 1) if total_kwh > 0 else None


class SolarForecastClient:
    """Client for forecast.solar API to get solar production predictions"""

    def __init__(self, latitude: float, longitude: float, declination: int = None,
                 azimuth: int = None, kwp: float = 5.0):
        """
        Initialize solar forecast client.

        Args:
            latitude: Location latitude
            longitude: Location longitude
            declination: Panel tilt angle in degrees (0=horizontal, 90=vertical).
                         If None, calculated optimally from latitude.
            azimuth: Panel direction (-180 to 180, 0=south, -90=east, 90=west).
                     If None, defaults to equator-facing (0 for both hemispheres in API convention).
            kwp: System capacity in kilowatts peak
        """
        self.latitude = latitude
        self.longitude = longitude
        # Calculate optimal tilt if not provided (roughly equal to latitude for fixed panels)
        if declination is None:
            self.declination = self._calculate_optimal_tilt(latitude)
        else:
            self.declination = declination
        # Default to equator-facing if not provided
        if azimuth is None:
            self.azimuth = self._calculate_optimal_azimuth(latitude)
        else:
            self.azimuth = azimuth
        self.kwp = kwp
        self.base_url = "https://api.forecast.solar"
        self._cache = {}
        self._cache_time = None
        self._cache_duration = 900  # 15 minutes (API updates every 15 min)

    @staticmethod
    def _calculate_optimal_tilt(latitude: float) -> int:
        """
        Default panel tilt angle.
        Most residential installs follow roof pitch (typically 15-25 degrees).
        """
        return 25

    @staticmethod
    def _calculate_optimal_azimuth(latitude: float) -> int:
        """
        Calculate optimal panel azimuth (direction) based on hemisphere.
        Panels should face the equator for maximum sun exposure.
        Southern hemisphere: 0 degrees (north-facing)
        Northern hemisphere: 180 degrees (south-facing)
        """
        if latitude < 0:
            return 0  # Face north in southern hemisphere
        else:
            return 180  # Face south in northern hemisphere

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self._cache_time:
            return False
        return (datetime.now() - self._cache_time).total_seconds() < self._cache_duration

    def get_forecast(self) -> Dict[str, Any]:
        """
        Get solar production forecast from forecast.solar API.
        Free tier: 12 requests/hour, updates every 15 minutes.
        """
        if self._is_cache_valid() and "forecast" in self._cache:
            logger.debug("Using cached solar forecast data")
            return self._cache["forecast"]

        try:
            # Public (free) API endpoint
            url = f"{self.base_url}/estimate/{self.latitude}/{self.longitude}/{self.declination}/{self.azimuth}/{self.kwp}"

            logger.info(f"Fetching solar forecast from forecast.solar for {self.kwp}kWp system")
            response = requests.get(url, timeout=30)

            if response.status_code == 429:
                logger.warning("forecast.solar rate limit exceeded")
                return {
                    "success": False,
                    "error": "Rate limit exceeded. Free tier allows 12 requests/hour.",
                    "is_temporary": True
                }

            if response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("message", {}).get("text", "Invalid request")
                logger.error("forecast.solar API returned an error")
                return {"success": False, "error": "Solar forecast service error", "is_temporary": False}

            if response.status_code == 422:
                logger.error("forecast.solar: Invalid location or plane parameters")
                return {
                    "success": False,
                    "error": "Invalid location or solar panel configuration",
                    "is_temporary": False
                }

            response.raise_for_status()
            data = response.json()

            forecast = self._parse_forecast(data)
            self._cache["forecast"] = forecast
            self._cache_time = datetime.now()

            return forecast

        except requests.exceptions.Timeout:
            logger.error("forecast.solar request timed out")
            return {"success": False, "error": "Request timed out", "is_temporary": True}
        except requests.exceptions.RequestException as e:
            logger.error(f"forecast.solar request failed: {e}")
            return {"success": False, "error": str(e), "is_temporary": True}
        except Exception as e:
            logger.error(f"Unexpected error fetching solar forecast: {e}")
            return {"success": False, "error": str(e), "is_temporary": False}

    def _parse_forecast(self, data: Dict) -> Dict[str, Any]:
        """Parse forecast.solar API response"""
        result = data.get("result", {})
        message = data.get("message", {})

        # watt_hours_day contains daily totals: {"YYYY-MM-DD": wh}
        daily_wh = result.get("watt_hours_day", {})

        # Convert to daily forecasts
        daily_forecasts = []
        today = datetime.now().strftime("%Y-%m-%d")

        for date_str, wh in sorted(daily_wh.items())[:4]:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            kwh = wh / 1000.0

            daily_forecasts.append({
                "date": date_str,
                "day_name": dt.strftime("%A"),
                "is_today": date_str == today,
                "estimated_kwh": round(kwh, 2),
                "estimated_wh": wh
            })

        # Also store hourly data for more detailed analysis
        hourly_wh = result.get("watt_hours", {})  # Cumulative Wh per timestamp
        watts = result.get("watts", {})  # Instant power per timestamp

        return {
            "success": True,
            "daily": daily_forecasts,
            "hourly_watts": watts,
            "hourly_wh": hourly_wh,
            "api_calls_remaining": message.get("ratelimit", {}).get("remaining"),
            "place": message.get("info", {}).get("place")
        }

    def get_daily_estimate(self, date_str: str = None) -> Optional[float]:
        """
        Get estimated kWh for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format. Defaults to tomorrow.

        Returns:
            Estimated kWh production or None if not available.
        """
        forecast = self.get_forecast()
        if not forecast.get("success"):
            return None

        if date_str is None:
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        for day in forecast.get("daily", []):
            if day["date"] == date_str:
                return day["estimated_kwh"]

        return None


class WeatherAnalyser:
    """Analyses weather forecast to determine bad weather days"""

    def __init__(
        self,
        bad_conditions: List[str] = None,
        min_cloud_cover: int = 70
    ):
        self.bad_conditions = bad_conditions if bad_conditions is not None else ["Rain", "Thunderstorm", "Drizzle", "Snow"]
        self.min_cloud_cover = min_cloud_cover

    def analyse_forecast(
        self,
        forecast: Dict[str, Any],
        panel_capacity_kw: float = None,
        weather_client: 'WeatherClient' = None,
        solar_client: 'SolarForecastClient' = None,
        min_solar_threshold: float = None
    ) -> Dict[str, Any]:
        """
        Analyse forecast and mark bad weather days.

        Args:
            forecast: Forecast data from weather client
            panel_capacity_kw: Panel capacity (unused, kept for compatibility)
            weather_client: WeatherClient instance (unused, kept for compatibility)
            solar_client: SolarForecastClient for accurate solar predictions
            min_solar_threshold: Minimum solar kWh to consider a "good" day
        """
        if not forecast.get("success") or not forecast.get("daily"):
            return forecast

        daily = forecast["daily"]
        bad_weather_days = []

        # Try to get solar forecast from forecast.solar
        solar_forecast = None
        if solar_client:
            solar_forecast = solar_client.get_forecast()
            if solar_forecast.get("success"):
                logger.info("Using forecast.solar for solar predictions")
            elif solar_forecast.get("is_temporary"):
                logger.warning("forecast.solar temporarily unavailable (rate limited or timeout)")

        for day in daily:
            date_str = day.get("date", "")

            # Use forecast.solar if available
            if solar_forecast and solar_forecast.get("success"):
                for solar_day in solar_forecast.get("daily", []):
                    if solar_day["date"] == date_str:
                        day["estimated_solar_kwh"] = solar_day["estimated_kwh"]
                        day["has_solar_prediction"] = True
                        day["solar_source"] = "forecast.solar"
                        break
                else:
                    day["estimated_solar_kwh"] = None
                    day["has_solar_prediction"] = False
                    day["solar_source"] = None
            else:
                # No API prediction available - don't fall back to weather estimate
                day["estimated_solar_kwh"] = None
                day["has_solar_prediction"] = False
                day["solar_source"] = None

            # Determine if bad weather based on solar prediction or weather conditions
            if day.get("has_solar_prediction") and min_solar_threshold:
                is_bad = day["estimated_solar_kwh"] < min_solar_threshold
            else:
                is_bad = self._is_bad_weather_day(day)

            day["is_bad_weather"] = is_bad
            if is_bad:
                bad_weather_days.append(day["date"])

        forecast["bad_weather_days"] = bad_weather_days

        return forecast

    def _is_bad_weather_day(self, day: Dict) -> bool:
        """Determine if a single day has bad weather for solar"""
        condition = day.get("condition", "")
        clouds = day.get("clouds", 0)
        pop = day.get("pop", 0)

        if condition in self.bad_conditions:
            return True

        if clouds >= self.min_cloud_cover:
            return True

        if pop >= 70:
            return True

        return False

    def should_skip_discharge(
        self,
        forecast: Dict[str, Any],
        min_solar_kwh: float = None
    ) -> tuple[bool, str]:
        """
        Determine if discharge should be skipped based on forecast.

        Args:
            forecast: Analysed forecast data
            min_solar_kwh: Minimum expected solar kWh to allow discharge.

        Returns:
            Tuple of (should_skip, reason)
        """
        if not forecast.get("success"):
            return False, "Weather data unavailable"

        if min_solar_kwh is not None and min_solar_kwh > 0:
            daily = forecast.get("daily", [])

            # Check tomorrow's solar prediction
            tomorrow_idx = 1 if len(daily) > 1 else 0
            if daily:
                tomorrow = daily[tomorrow_idx]
                estimated_solar = tomorrow.get("estimated_solar_kwh")

                if estimated_solar is not None:
                    source = tomorrow.get("solar_source", "unknown")
                    if estimated_solar < min_solar_kwh:
                        day_name = tomorrow.get("day_name", "Tomorrow")
                        return True, f"Low solar forecast ({estimated_solar:.1f} kWh < {min_solar_kwh:.1f} kWh on {day_name})"
                    else:
                        return False, f"Good solar forecast ({estimated_solar:.1f} kWh on {tomorrow.get('day_name', 'Tomorrow')})"
                else:
                    return False, "Solar prediction not available"

        return False, "Solar threshold not configured"
