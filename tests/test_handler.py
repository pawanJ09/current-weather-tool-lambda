import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src import handler

SAMPLE_OPEN_METEO_RESPONSE = {
    "latitude": 40.71,
    "longitude": -74.01,
    "timezone": "America/New_York",
    "current": {
        "time": "2026-10-02T09:00",
        "temperature_2m": 68.5,
        "relative_humidity_2m": 54,
        "apparent_temperature": 67.0,
        "precipitation": 0.0,
        "weather_code": 1,
        "wind_speed_10m": 6.2,
        "wind_direction_10m": 210,
    },
}


def _mock_urlopen_returning(payload_bytes: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload_bytes
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


class TestFetchCurrentWeather:
    @patch("src.handler.urllib.request.urlopen")
    def test_success_maps_open_meteo_fields(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen_returning(
            json.dumps(SAMPLE_OPEN_METEO_RESPONSE).encode("utf-8")
        )

        result = handler.fetch_current_weather(40.71, -74.01)

        assert result["temperature_f"] == 68.5
        assert result["feels_like_f"] == 67.0
        assert result["humidity_pct"] == 54
        assert result["timezone"] == "America/New_York"
        assert result["weather_code"] == 1

    @patch("src.handler.urllib.request.urlopen")
    def test_network_error_raises_weather_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        with pytest.raises(handler.WeatherError):
            handler.fetch_current_weather(40.71, -74.01)

    @patch("src.handler.urllib.request.urlopen")
    def test_timeout_raises_weather_error(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("timed out")

        with pytest.raises(handler.WeatherError):
            handler.fetch_current_weather(40.71, -74.01)

    @patch("src.handler.urllib.request.urlopen")
    def test_bad_json_raises_weather_error(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen_returning(b"not valid json")

        with pytest.raises(handler.WeatherError):
            handler.fetch_current_weather(40.71, -74.01)

    @patch("src.handler.urllib.request.urlopen")
    def test_missing_current_block_raises_weather_error(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen_returning(
            json.dumps({"latitude": 1, "longitude": 2}).encode("utf-8")
        )

        with pytest.raises(handler.WeatherError):
            handler.fetch_current_weather(1, 2)


class TestParseCoordinates:
    def test_valid_numbers(self):
        lat, lon = handler._parse_coordinates({"latitude": 40.71, "longitude": -74.01})
        assert lat == 40.71
        assert lon == -74.01

    def test_valid_numeric_strings(self):
        lat, lon = handler._parse_coordinates({"latitude": "40.71", "longitude": "-74.01"})
        assert lat == 40.71
        assert lon == -74.01

    def test_missing_latitude_raises(self):
        with pytest.raises(handler.InputError):
            handler._parse_coordinates({"longitude": -74.01})

    def test_missing_longitude_raises(self):
        with pytest.raises(handler.InputError):
            handler._parse_coordinates({"latitude": 40.71})

    def test_non_numeric_value_raises(self):
        with pytest.raises(handler.InputError):
            handler._parse_coordinates({"latitude": "abc", "longitude": -74.01})

    def test_non_dict_event_raises(self):
        with pytest.raises(handler.InputError):
            handler._parse_coordinates(["not", "a", "dict"])


class TestToolNameFromContext:
    def test_no_client_context_returns_none(self):
        assert handler._tool_name_from_context(SimpleNamespace()) is None

    def test_client_context_with_custom_returns_tool_name(self):
        context = SimpleNamespace(
            client_context=SimpleNamespace(
                custom={"bedrockAgentCoreToolName": "weather-tools___get_current_weather"}
            )
        )
        assert handler._tool_name_from_context(context) == "weather-tools___get_current_weather"

    def test_client_context_without_custom_returns_none(self):
        context = SimpleNamespace(client_context=SimpleNamespace(custom=None))
        assert handler._tool_name_from_context(context) is None


class TestLambdaHandler:
    @patch("src.handler.fetch_current_weather")
    def test_success_returns_raw_weather_dict(self, mock_fetch):
        mock_fetch.return_value = {"temperature_f": 68.5}

        result = handler.lambda_handler({"latitude": 40.71, "longitude": -74.01}, SimpleNamespace())

        assert result == {"temperature_f": 68.5}

    def test_missing_coordinates_returns_error_dict(self):
        result = handler.lambda_handler({}, SimpleNamespace())
        assert "error" in result

    @patch("src.handler.fetch_current_weather")
    def test_upstream_failure_returns_error_dict(self, mock_fetch):
        mock_fetch.side_effect = handler.WeatherError("Open-Meteo request failed: boom")

        result = handler.lambda_handler({"latitude": 40.71, "longitude": -74.01}, SimpleNamespace())

        assert "error" in result

    @patch("src.handler.fetch_current_weather")
    def test_gateway_invocation_logs_tool_name(self, mock_fetch, caplog):
        mock_fetch.return_value = {"temperature_f": 68.5}
        context = SimpleNamespace(
            client_context=SimpleNamespace(
                custom={"bedrockAgentCoreToolName": "weather-tools___get_current_weather"}
            )
        )

        with caplog.at_level("INFO"):
            result = handler.lambda_handler({"latitude": 40.71, "longitude": -74.01}, context)

        assert result == {"temperature_f": 68.5}
        assert "get_current_weather" in caplog.text
