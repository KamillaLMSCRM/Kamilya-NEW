"""Offline controls for the pinned HTTP dependency; never make network calls."""

import pytest
import requests
from urllib3.exceptions import LocationParseError
from urllib3.util import parse_url


@pytest.mark.parametrize("host", ["example.com bad", "example.com%0d%0aInjected"])
def test_http_url_parser_rejects_invalid_host_representations(host: str) -> None:
    with pytest.raises(LocationParseError):
        parse_url(f"https://{host}/api")


def test_requests_prepares_ordinary_https_request_without_network() -> None:
    with requests.Session() as session:
        prepared = session.prepare_request(
            requests.Request("GET", "https://example.com/api", params={"language": "ru"})
        )
        assert prepared.method == "GET"
        assert prepared.url == "https://example.com/api?language=ru"
        assert session.verify is True
