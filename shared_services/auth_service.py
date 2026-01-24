# Simple requests-based script for HH API interaction
import os
import sys
import requests
import json
import logging
from typing import Optional, Dict
from pathlib import Path

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared_services.constants import BASE_URL

logger = logging.getLogger(__name__)


ADMIN_TOKEN  = os.getenv("ADMIN_TOKEN")
BOT_SHARED_SECRET = os.getenv("BOT_SHARED_SECRET")
USER_AGENT = os.getenv("USER_AGENT")

def callback_endpoint_healthcheck() -> bool:
    """
    Check API health endpoint. Returns True if endpoint is available, False otherwise.
    """
    try:
        response = requests.get(f"{BASE_URL}/", timeout=10, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200:
            logger.info(f"Callback endpoint health check passed: {response.text}")
            return True
        else:
            logger.warning(f"Callback endpoint health check failed with status {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Callback endpoint health check error: {e}", exc_info=True)
        return False
    

def get_token_by_state(state: str, bot_shared_secret: str): # returns a dictionary with the token data
    """
    Calls POST {base_url}/token/by-state with:
      headers: Authorization: Bearer <bot_shared_secret>, Content-Type: application/json
      json: {"state": "<state>"}
    Returns the full token payload dict on success, or empty dict on error.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {bot_shared_secret}",
        "Content-Type": "application/json",
    }
    payload = {"state": state}  # server expects a string in StatePayload

    try:
        response = requests.post(f"{BASE_URL}/token/by-state", headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            logger.debug(f"callback endpoint request successful: {response.text}")
            return response.json()
        else:
            logger.error(f"request failed: {response.status_code} {response.text}")
            return None
    except requests.RequestException as e:
        logger.error(f"request failed: {e}", exc_info=True)
        # return None if request fails
        return None
