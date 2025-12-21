import requests
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


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
            url = f"https://api.openweathermap.org/data/3.0/onecall"
            params = {
                "lat": self.latitude,
                "lon": self.longitude,
                "appid": self.api_key,
                "units": "metric",
                "exclude": "minutely,hourly,alerts"
            }

            logger.info(f"Fetching weather forecast for ({self.latitude}, {self.longitude})")
            response = requests.get(url, params=params, timeout=30)

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

        except requests.exceptions.RequestException as e:
            logger.warning(f"One Call API failed: {e}, trying legacy API")
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
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            forecast = self._parse_legacy_forecast(data)
            self._cache["forecast"] = forecast
            self._cache_time = datetime.now()

            return forecast

        except Exception as e:
            logger.error(f"Failed to fetch weather forecast: {e}")
            return {"success": False, "error": str(e), "daily": []}

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
