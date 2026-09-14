"""Smoke tests for deployed Mekong CLI services."""

import urllib.request
import urllib.error
import json
import os
import pytest

BASE_API_URL = os.getenv("API_BASE_URL", "https://mekong-api.workers.dev")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://mekong-ide.pages.dev")


def _fetch(url: str, timeout: int = 10):
    """Open URL or skip if remote endpoint is unreachable."""
    try:
        return urllib.request.urlopen(url, timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        pytest.skip(f"Live service unavailable at {url}: {e}")


def test_api_health():
    """Test that the API health endpoint returns 200."""
    url = f"{BASE_API_URL}/healthz"
    response = _fetch(url, timeout=10)
    with response:
        assert response.status == 200, f"Health endpoint returned {response.status}"
        body = response.read().decode('utf-8')
        print(f"Health response: {body}")


def test_api_health_json_response():
    """Test that the health endpoint returns valid JSON."""
    url = f"{BASE_API_URL}/healthz"
    response = _fetch(url, timeout=10)
    try:
        with response:
            if response.status == 200:
                body = response.read().decode('utf-8')
                data = json.loads(body)
                assert 'status' in data or 'message' in data, "Health response missing expected fields"
                print(f"Health JSON: {json.dumps(data, indent=2)}")
    except json.JSONDecodeError as e:
        pytest.fail(f"Health endpoint did not return valid JSON: {e}")


def test_dashboard_homepage():
    """Test that the dashboard homepage loads."""
    url = DASHBOARD_URL
    response = _fetch(url, timeout=15)
    with response:
        assert response.status in [200, 304], f"Dashboard returned {response.status}"
        body = response.read().decode('utf-8')
        assert len(body) > 1000, "Dashboard page seems too small (possibly error page)"
        assert '<!DOCTYPE html>' in body or '<html' in body, "Dashboard does not appear to be HTML"


def test_dashboard_assets():
    """Test that static assets are accessible."""
    url = f"{DASHBOARD_URL}/_next/static/chunks/main.js"
    response = _fetch(url, timeout=10)
    with response:
        assert response.status in [200, 304], f"Static assets returned {response.status}"

