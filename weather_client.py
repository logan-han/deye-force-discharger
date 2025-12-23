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
    """Client for OpenWeatherMap API to fetch weather forecasts"""

    def __init__(self, api_key: str, city_name: str):
        self.api_key = api_key
        self.city_name = city_name
        self.latitude = None
        self.longitude = None
        self._coordinates_cached = False
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self._cache = {}
        self._cache_time = None
        self._cache_duration = 300  # 5 minutes cache

    def _geocode_city(self) -> bool:
        """Geocode city_name to get latitude and longitude. Returns True if successful."""
        if self._coordinates_cached:
            return self.latitude is not None and self.longitude is not None

        self._coordinates_cached = True

        if not self.city_name:
            logger.error("No city name configured for weather")
            return False

        cities = self.search_cities(self.api_key, self.city_name, limit=1)
        if not cities:
            logger.error(f"Could not geocode city: {self.city_name}")
            return False

        self.latitude = cities[0]["lat"]
        self.longitude = cities[0]["lon"]
        logger.info(f"Geocoded {self.city_name} to ({self.latitude}, {self.longitude})")
        return True

    @staticmethod
    def search_cities(api_key: str, query: str, limit: int = 5):
        """Search for cities by name using OpenWeatherMap Geocoding API."""
        if not query or len(query) < 3:
            return []
        import requests
        url = "http://api.openweathermap.org/geo/1.0/direct"
        params = {"q": query, "limit": limit, "appid": api_key}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            results = response.json()
            cities = []
            for item in results:
                city = {
                    "name": item.get("name", ""),
                    "country": item.get("country", ""),
                    "state": item.get("state", ""),
                    "lat": item.get("lat"),
                    "lon": item.get("lon")
                }
                display_parts = [city["name"]]
                if city["state"]:
                    display_parts.append(city["state"])
                display_parts.append(city["country"])
                city["display_name"] = ", ".join(display_parts)
                cities.append(city)
            return cities
        except Exception:
            return []

    @staticmethod
    def estimate_solar_output_simple(panel_capacity_kw: float, clouds: int, condition: str, pop: int) -> float:
        """
        Simple estimate of daily solar output (fallback when hourly data unavailable).
        """
        base_daily_kwh = panel_capacity_kw * 5.5 * 0.9
        cloud_factor = 1.0 - (clouds / 100 * 0.5)
        condition_factors = {
            "Clear": 1.0, "Clouds": 0.75, "Rain": 0.35, "Drizzle": 0.45,
            "Thunderstorm": 0.25, "Snow": 0.3, "Mist": 0.65, "Fog": 0.55, "Haze": 0.75
        }
        condition_factor = condition_factors.get(condition, 0.65)
        pop_factor = 1.0 - (pop / 100 * 0.2)
        weather_factor = ((cloud_factor + condition_factor) / 2) * pop_factor
        return round(base_daily_kwh * weather_factor, 1)

    def estimate_solar_output_hourly(self, panel_capacity_kw: float, date_str: str) -> Optional[float]:
        """
        Estimate daily solar output using hourly forecast data.
        Only counts production during daylight hours with hour-specific factors.

        Args:
            panel_capacity_kw: Panel capacity in kW
            date_str: Date string in YYYY-MM-DD format

        Returns:
            Estimated kWh for the day, or None if hourly data unavailable
        """
        if "hourly_data" not in self._cache:
            logger.debug(f"No hourly_data in cache for solar estimate")
            return None

        hourly_data = self._cache["hourly_data"].get(date_str, [])
        if not hourly_data:
            logger.debug(f"No hourly data for date {date_str}, available dates: {list(self._cache['hourly_data'].keys())}")
            return None

        # Base daily production varies by latitude (peak sun hours equivalent)
        # Higher latitudes = less solar potential
        # Typical summer values: equator ~6.0, 20° ~5.5, 35° ~4.5, 45° ~4.0
        lat = abs(self.latitude) if self.latitude else 35  # Default to mid-latitude
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

        # Hour-based solar intensity factors for 3-hour windows
        # Represents the fraction of daily production in each 3-hour window
        # Weighted towards midday when sun is strongest (sum ~1.0)
        hour_weights = {
            6: 0.05,   # 6-9am: sunrise ramp-up
            7: 0.05,
            8: 0.08,
            9: 0.12,   # 9am-12pm: building
            10: 0.12,
            11: 0.14,
            12: 0.14,  # 12-3pm: peak production
            13: 0.14,
            14: 0.12,
            15: 0.12,  # 3-6pm: declining
            16: 0.08,
            17: 0.05,
            18: 0.03   # 6-7pm: sunset
        }

        # Condition factors only for precipitation/obstruction conditions
        # "Clear" and "Clouds" rely on cloud percentage instead
        condition_factors = {
            "Rain": 0.25, "Drizzle": 0.35, "Thunderstorm": 0.1,
            "Snow": 0.15, "Mist": 0.5, "Fog": 0.4, "Haze": 0.7
        }

        # Calculate base daily production for this system
        base_daily_kwh = panel_capacity_kw * base_kwh_per_kw

        total_kwh = 0.0
        hours_with_data = set()

        for entry in hourly_data:
            hour = entry.get("hour", 12)
            clouds = entry.get("clouds", 0)
            condition = entry.get("condition", "Clear")
            pop = entry.get("pop", 0)

            # Skip nighttime hours
            if hour < 6 or hour > 18:
                continue

            # Get weight for this hour
            hour_weight = hour_weights.get(hour, 0)
            if hour_weight == 0:
                continue

            hours_with_data.add(hour)

            # Cloud impact: 0-100% clouds reduces output
            # At 100% overcast, output is about 25-30% of clear sky
            cloud_factor = 1.0 - (clouds / 100 * 0.75)

            # Precipitation/obstruction conditions apply additional penalty
            # For Clear/Clouds, only cloud_factor matters
            if condition in condition_factors:
                cond_factor = condition_factors[condition]
                weather_factor = min(cloud_factor, cond_factor)
            else:
                weather_factor = cloud_factor

            # Precipitation probability slightly reduces expected output
            pop_factor = 1.0 - (pop / 100 * 0.3)
            weather_factor *= pop_factor

            # Calculate kWh contribution from this period
            # Each 3-hour period covers ~3 hours worth of production
            # Scale the hour_weight by 3 since we have 3-hour data points
            period_kwh = base_daily_kwh * hour_weight * 3 * weather_factor

            total_kwh += period_kwh
            logger.debug(f"Hour {hour}: clouds={clouds}, cond={condition}, weather_factor={weather_factor:.2f}, kwh={period_kwh:.1f}")

        # Need at least 1 data point to make any estimate
        if len(hours_with_data) < 1:
            return None

        return round(total_kwh, 1) if total_kwh > 0 else None

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self._cache_time:
            return False
        return (datetime.now() - self._cache_time).total_seconds() < self._cache_duration

    def _make_request_with_retry(self, url: str, params: dict, max_retries: int = 2) -> requests.Response:
        """
        Make an HTTP request with retry logic for transient errors.

        Args:
            url: The URL to request
            params: Query parameters
            max_retries: Maximum number of retry attempts for transient errors

        Returns:
            Response object

        Raises:
            WeatherAPIError: On permanent failures or after retries exhausted
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=30)

                # Handle rate limiting with retry
                if response.status_code == 429:
                    if attempt < max_retries:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        wait_time = min(retry_after, 60)  # Cap at 60 seconds
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        "OpenWeatherMap API rate limit exceeded",
                        is_temporary=True,
                        status_code=429
                    )

                # Server errors - retry
                if response.status_code >= 500:
                    if attempt < max_retries:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s
                        logger.warning(f"Server error {response.status_code}, retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        f"OpenWeatherMap API server error (HTTP {response.status_code})",
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
                    "OpenWeatherMap API request timed out",
                    is_temporary=True
                )

            except requests.exceptions.ConnectionError as e:
                last_error = e
                error_str = str(e).lower()

                # DNS resolution failure
                if "name or service not known" in error_str or "getaddrinfo" in error_str or "nodename nor servname" in error_str:
                    if attempt < max_retries:
                        wait_time = 2 ** attempt
                        logger.warning(f"DNS resolution failed, retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    raise WeatherAPIError(
                        "Unable to resolve OpenWeatherMap API hostname (DNS failure)",
                        is_temporary=True
                    )

                # Connection refused
                if "connection refused" in error_str:
                    raise WeatherAPIError(
                        "Connection to OpenWeatherMap API refused",
                        is_temporary=True
                    )

                # Generic connection error - retry
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Connection error, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                raise WeatherAPIError(
                    f"Unable to connect to OpenWeatherMap API: {e}",
                    is_temporary=True
                )

            except requests.exceptions.RequestException as e:
                raise WeatherAPIError(
                    f"OpenWeatherMap API request failed: {e}",
                    is_temporary=False
                )

        # Should not reach here, but just in case
        raise WeatherAPIError(
            f"OpenWeatherMap API request failed after {max_retries + 1} attempts",
            is_temporary=True
        )

    def get_forecast(self) -> Dict[str, Any]:
        """
        Get 5-day weather forecast with 3-hourly data for solar predictions.
        Uses the free tier 5-day/3-hour forecast API which provides
        the hourly data needed for accurate solar output estimates.
        """
        if self._is_cache_valid() and "forecast" in self._cache:
            logger.debug("Using cached forecast data")
            return self._cache["forecast"]

        # Geocode city name to coordinates if not already done
        if not self._geocode_city():
            return {
                "success": False,
                "error": f"Could not geocode city: {self.city_name}"
            }

        # Use legacy 5-day/3-hour API - free tier and provides hourly data for solar calc
        return self._get_forecast_legacy()

    def _get_forecast_legacy(self) -> Dict[str, Any]:
        """
        Fallback to 5-day/3-hour forecast API (free tier)
        Aggregates into daily forecasts
        """
        try:
            url = f"{self.base_url}/forecast"
            params = {
                "lat": self.latitude,
                "lon": self.longitude,
                "appid": self.api_key,
                "units": "metric"
            }

            logger.info("Fetching weather forecast using legacy 5-day API")
            response = self._make_request_with_retry(url, params)

            # Handle authentication errors
            if response.status_code == 401:
                error_msg = "Invalid OpenWeatherMap API key"
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "daily": [], "is_temporary": False}

            if response.status_code == 403:
                error_msg = "OpenWeatherMap API access forbidden - check API key permissions"
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "daily": [], "is_temporary": False}

            response.raise_for_status()
            data = response.json()

            forecast = self._parse_legacy_forecast(data)
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
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching weather: {e}")
            return {
                "success": False,
                "error": f"OpenWeatherMap API returned an error: {e}",
                "daily": [],
                "is_temporary": False
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching weather forecast: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
                "daily": [],
                "is_temporary": False
            }

    def _parse_onecall_forecast(self, data: Dict) -> Dict[str, Any]:
        """Parse One Call API response into daily forecast"""
        daily_forecasts = []

        current = data.get("current", {})
        daily_list = data.get("daily", [])

        for i, day in enumerate(daily_list[:5]):  # Up to 5 days
            dt = datetime.fromtimestamp(day.get("dt", 0))
            weather_list = day.get("weather", [])
            weather = weather_list[0] if weather_list else {}

            daily_forecasts.append({
                "date": dt.strftime("%Y-%m-%d"),
                "day_name": dt.strftime("%A"),
                "is_today": i == 0,
                "temp_min": day.get("temp", {}).get("min"),
                "temp_max": day.get("temp", {}).get("max"),
                "condition": weather.get("main", "Unknown"),
                "description": weather.get("description", ""),
                "icon": weather.get("icon", "01d"),
                "clouds": day.get("clouds", 0),
                "pop": int(day.get("pop", 0) * 100),  # Probability of precipitation
                "rain": day.get("rain", 0),
                "uvi": day.get("uvi", 0),
                "is_bad_weather": False  # Will be calculated by analyzer
            })

        current_weather_list = current.get("weather", [])
        current_weather = current_weather_list[0] if current_weather_list else {}
        location = self.city_name if self.city_name else data.get("timezone", "Unknown")
        return {
            "success": True,
            "location": location,
            "current": {
                "temp": current.get("temp"),
                "condition": current_weather.get("main", "Unknown"),
                "clouds": current.get("clouds", 0)
            },
            "daily": daily_forecasts
        }

    def _parse_legacy_forecast(self, data: Dict) -> Dict[str, Any]:
        """Parse 5-day/3-hour forecast into daily aggregates and store hourly data"""
        daily_data = {}
        hourly_data = {}  # Store hourly data for solar calculations

        # Get timezone offset from API response (seconds from UTC)
        tz_offset_seconds = data.get("city", {}).get("timezone", 0)
        local_tz = timezone(timedelta(seconds=tz_offset_seconds))

        for item in data.get("list", []):
            # Convert UTC timestamp to location's local time
            utc_dt = datetime.fromtimestamp(item.get("dt", 0), tz=timezone.utc)
            local_dt = utc_dt.astimezone(local_tz)
            date_key = local_dt.strftime("%Y-%m-%d")
            hour = local_dt.hour

            if date_key not in daily_data:
                daily_data[date_key] = {
                    "temps": [],
                    "conditions": [],
                    "clouds": [],
                    "pop": [],
                    "rain": 0
                }
                hourly_data[date_key] = []

            main = item.get("main", {})
            weather = item.get("weather", [{}])[0]
            clouds = item.get("clouds", {}).get("all", 0)
            pop = item.get("pop", 0) * 100
            condition = weather.get("main", "Unknown")

            daily_data[date_key]["temps"].append(main.get("temp", 0))
            daily_data[date_key]["conditions"].append(condition)
            daily_data[date_key]["clouds"].append(clouds)
            daily_data[date_key]["pop"].append(pop)
            daily_data[date_key]["rain"] += item.get("rain", {}).get("3h", 0)

            # Store hourly data for solar calculation
            hourly_data[date_key].append({
                "hour": hour,
                "clouds": clouds,
                "condition": condition,
                "pop": pop,
                "hours": 3  # 3-hour forecast period
            })

        # Cache hourly data for solar calculations
        self._cache["hourly_data"] = hourly_data
        logger.debug(f"Cached hourly weather data for {len(hourly_data)} days")

        daily_forecasts = []
        # Use location's timezone for "today" comparison
        today = datetime.now(local_tz).strftime("%Y-%m-%d")

        for i, (date_key, day_data) in enumerate(sorted(daily_data.items())[:5]):
            dt = datetime.strptime(date_key, "%Y-%m-%d")

            # Get most common condition for the day
            condition_counts = {}
            for cond in day_data["conditions"]:
                condition_counts[cond] = condition_counts.get(cond, 0) + 1
            main_condition = max(condition_counts, key=condition_counts.get)

            # Get weather icon based on condition
            icon_map = {
                "Clear": "01d", "Clouds": "03d", "Rain": "10d",
                "Drizzle": "09d", "Thunderstorm": "11d", "Snow": "13d",
                "Mist": "50d", "Fog": "50d"
            }

            daily_forecasts.append({
                "date": date_key,
                "day_name": dt.strftime("%A"),
                "is_today": date_key == today,
                "temp_min": min(day_data["temps"]) if day_data["temps"] else None,
                "temp_max": max(day_data["temps"]) if day_data["temps"] else None,
                "condition": main_condition,
                "description": main_condition.lower(),
                "icon": icon_map.get(main_condition, "01d"),
                "clouds": int(sum(day_data["clouds"]) / len(day_data["clouds"])) if day_data["clouds"] else 0,
                "pop": int(max(day_data["pop"])) if day_data["pop"] else 0,
                "rain": round(day_data["rain"], 1),
                "uvi": 0,  # Not available in legacy API
                "is_bad_weather": False
            })

        city = data.get("city", {})
        location = self.city_name if self.city_name else city.get("name", "Unknown")
        return {
            "success": True,
            "location": location,
            "current": daily_forecasts[0] if daily_forecasts else {},
            "daily": daily_forecasts
        }


class WeatherAnalyser:
    """Analyses weather forecast to determine bad weather days"""

    def __init__(
        self,
        bad_conditions: List[str] = None,
        min_cloud_cover: int = 70
    ):
        self.bad_conditions = bad_conditions if bad_conditions is not None else ["Rain", "Thunderstorm", "Drizzle", "Snow"]
        self.min_cloud_cover = min_cloud_cover

    def analyse_forecast(self, forecast: Dict[str, Any], panel_capacity_kw: float = None, weather_client: 'WeatherClient' = None, min_solar_threshold: float = None) -> Dict[str, Any]:
        """
        Analyse forecast and mark bad weather days

        Args:
            forecast: Forecast data from weather client
            panel_capacity_kw: Panel capacity for solar estimation
            weather_client: WeatherClient instance for hourly solar calculations
            min_solar_threshold: Minimum solar kWh to consider a "good" day

        Returns forecast with is_bad_weather flag set for each day
        """
        if not forecast.get("success") or not forecast.get("daily"):
            return forecast

        daily = forecast["daily"]
        bad_weather_days = []

        for day in daily:
            # Add solar output estimate if panel capacity provided
            # Only use hourly data - don't fall back to simple (less accurate)
            if panel_capacity_kw and panel_capacity_kw > 0 and weather_client:
                hourly_estimate = weather_client.estimate_solar_output_hourly(
                    panel_capacity_kw,
                    day.get("date", "")
                )

                if hourly_estimate is not None:
                    day["estimated_solar_kwh"] = hourly_estimate
                    day["has_solar_prediction"] = True
                else:
                    # No hourly data available for this day
                    day["estimated_solar_kwh"] = None
                    day["has_solar_prediction"] = False
            else:
                day["estimated_solar_kwh"] = None
                day["has_solar_prediction"] = False

            # Determine if bad weather based on solar prediction (if available)
            # Otherwise fall back to condition-based check
            if day.get("has_solar_prediction") and min_solar_threshold:
                # Bad weather = solar prediction below threshold
                is_bad = day["estimated_solar_kwh"] < min_solar_threshold
            else:
                # Fallback to condition-based check for days without solar prediction
                is_bad = self._is_bad_weather_day(day)

            day["is_bad_weather"] = is_bad
            if is_bad:
                bad_weather_days.append(day["date"])

        forecast["bad_weather_days"] = bad_weather_days
        forecast["consecutive_bad_days"] = self._count_consecutive_bad_days(daily)

        return forecast

    def _is_bad_weather_day(self, day: Dict) -> bool:
        """Determine if a single day has bad weather for solar"""
        condition = day.get("condition", "")
        clouds = day.get("clouds", 0)
        pop = day.get("pop", 0)

        # Bad if condition is in bad list
        if condition in self.bad_conditions:
            return True

        # Bad if high cloud cover
        if clouds >= self.min_cloud_cover:
            return True

        # Bad if high probability of precipitation
        if pop >= 70:
            return True

        return False

    def _count_consecutive_bad_days(self, daily: List[Dict]) -> int:
        """Count consecutive bad weather days starting from today"""
        count = 0
        for day in daily:
            if day.get("is_bad_weather"):
                count += 1
            else:
                break
        return count

    def should_skip_discharge(
        self,
        forecast: Dict[str, Any],
        min_solar_kwh: float = None
    ) -> tuple[bool, str]:
        """
        Determine if discharge should be skipped based on forecast

        Args:
            forecast: Analysed forecast data
            min_solar_kwh: Minimum expected solar kWh to allow discharge.
                          If tomorrow's solar is below this, skip discharge.

        Returns:
            Tuple of (should_skip, reason)
        """
        if not forecast.get("success"):
            return False, "Weather data unavailable"

        # If solar threshold is configured, use it
        if min_solar_kwh is not None and min_solar_kwh > 0:
            daily = forecast.get("daily", [])

            # Check tomorrow's solar prediction (index 1 if available, else today)
            tomorrow_idx = 1 if len(daily) > 1 else 0
            if daily:
                tomorrow = daily[tomorrow_idx]
                estimated_solar = tomorrow.get("estimated_solar_kwh")

                if estimated_solar is not None:
                    if estimated_solar < min_solar_kwh:
                        day_name = tomorrow.get("day_name", "Tomorrow")
                        return True, f"Low solar forecast ({estimated_solar:.1f} kWh < {min_solar_kwh:.1f} kWh on {day_name})"
                    else:
                        return False, f"Good solar forecast ({estimated_solar:.1f} kWh on {tomorrow.get('day_name', 'Tomorrow')})"
                else:
                    return False, "Solar prediction not available (no hourly forecast data)"

        return False, "Solar threshold not configured"
