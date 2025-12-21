import requests
import logging
import time
from datetime import datetime, timedelta
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

    def __init__(self, api_key: str, latitude: float, longitude: float):
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self._cache = {}
        self._cache_time = None
        self._cache_duration = 1800  # 30 minutes cache

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
        Get 8-day weather forecast (today + 7 days)
        Uses OpenWeatherMap One Call API 3.0 for daily forecasts
        """
        if self._is_cache_valid() and "forecast" in self._cache:
            logger.debug("Using cached forecast data")
            return self._cache["forecast"]

        try:
            # Use One Call API 3.0 for daily forecast
            url = "https://api.openweathermap.org/data/3.0/onecall"
            params = {
                "lat": self.latitude,
                "lon": self.longitude,
                "appid": self.api_key,
                "units": "metric",
                "exclude": "minutely,hourly,alerts"
            }

            logger.info(f"Fetching weather forecast for ({self.latitude}, {self.longitude})")
            response = self._make_request_with_retry(url, params)

            # If One Call 3.0 fails (requires subscription), fallback to 2.5
            if response.status_code == 401 or response.status_code == 403:
                logger.warning("One Call API 3.0 not available, trying 2.5")
                return self._get_forecast_legacy()

            response.raise_for_status()
            data = response.json()

            forecast = self._parse_onecall_forecast(data)
            self._cache["forecast"] = forecast
            self._cache_time = datetime.now()

            return forecast

        except WeatherAPIError as e:
            logger.warning(f"One Call API failed: {e}, trying legacy API")
            return self._get_forecast_legacy()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"One Call API HTTP error: {e}, trying legacy API")
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

        for i, day in enumerate(daily_list[:8]):  # Up to 8 days
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
        return {
            "success": True,
            "location": data.get("timezone", "Unknown"),
            "current": {
                "temp": current.get("temp"),
                "condition": current_weather.get("main", "Unknown"),
                "clouds": current.get("clouds", 0)
            },
            "daily": daily_forecasts
        }

    def _parse_legacy_forecast(self, data: Dict) -> Dict[str, Any]:
        """Parse 5-day/3-hour forecast into daily aggregates"""
        daily_data = {}

        for item in data.get("list", []):
            dt = datetime.fromtimestamp(item.get("dt", 0))
            date_key = dt.strftime("%Y-%m-%d")

            if date_key not in daily_data:
                daily_data[date_key] = {
                    "temps": [],
                    "conditions": [],
                    "clouds": [],
                    "pop": [],
                    "rain": 0
                }

            main = item.get("main", {})
            weather = item.get("weather", [{}])[0]

            daily_data[date_key]["temps"].append(main.get("temp", 0))
            daily_data[date_key]["conditions"].append(weather.get("main", "Unknown"))
            daily_data[date_key]["clouds"].append(item.get("clouds", {}).get("all", 0))
            daily_data[date_key]["pop"].append(item.get("pop", 0) * 100)
            daily_data[date_key]["rain"] += item.get("rain", {}).get("3h", 0)

        daily_forecasts = []
        today = datetime.now().strftime("%Y-%m-%d")

        for i, (date_key, day_data) in enumerate(sorted(daily_data.items())[:8]):
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
        return {
            "success": True,
            "location": city.get("name", "Unknown"),
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

    def analyse_forecast(self, forecast: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse forecast and mark bad weather days

        Returns forecast with is_bad_weather flag set for each day
        """
        if not forecast.get("success") or not forecast.get("daily"):
            return forecast

        daily = forecast["daily"]
        bad_weather_days = []

        for day in daily:
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
        threshold_days: int = 2
    ) -> tuple[bool, str]:
        """
        Determine if discharge should be skipped based on forecast

        Args:
            forecast: Analysed forecast data
            threshold_days: Number of consecutive bad days to trigger skip

        Returns:
            Tuple of (should_skip, reason)
        """
        if not forecast.get("success"):
            return False, "Weather data unavailable"

        consecutive = forecast.get("consecutive_bad_days", 0)
        bad_days = forecast.get("bad_weather_days", [])

        if consecutive >= threshold_days:
            return True, f"Bad weather expected for next {consecutive} days ({', '.join(bad_days[:threshold_days])})"

        # Also check if there are enough bad days in the next threshold_days period
        upcoming_bad = sum(1 for day in forecast.get("daily", [])[:threshold_days] if day.get("is_bad_weather"))
        if upcoming_bad >= threshold_days:
            return True, f"{upcoming_bad} bad weather days in next {threshold_days} days"

        return False, f"Good weather forecast ({consecutive} consecutive bad days)"
