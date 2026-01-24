# exchange_code.py
import os, requests, json
import sys
import logging
from typing import Optional
from pathlib import Path

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from telegram._passport.passportdata import PassportData

from shared_services.data_service import create_json_file_with_dictionary_content

from shared_services.constants import EMPLOYER_STATE_RESPONSE, EMPLOYER_STATE_CONSIDER

logger = logging.getLogger(__name__)

HH_CLIENT_ID     = os.getenv("HH_CLIENT_ID")
HH_CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
REDIRECT_URI     = os.getenv("OAUTH_REDIRECT_URL")
USER_AGENT       = os.getenv("USER_AGENT")


# ------------------------------ USER related calls ------------------------------

def get_user_info_from_hh(access_token: str) -> Optional[dict]:
    """Get user info from HH.ru API
    Args:
        access_token (str): Access token for HH.ru API
    Returns:
        dict: User info from HH.ru API or None if request failed
    """
    try:
        r = requests.get(
            "https://api.hh.ru/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=10,
        )
        r.raise_for_status()
        if r.status_code == 200:
            return r.json()
        else:
            logger.error(f"Error: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting user info: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting user info: {e}", exc_info=True)
        return None


def clean_user_info_received_from_hh(user_info: dict) -> dict:
    """Clean user info recieved from HH.ru API
    Args:
        user_info (dict): User info from HH.ru API
    Returns:
        dict: Cleaned user info with only the needed fields
    """
    cleaned_user_info = {
        "auth_type": user_info["auth_type"],
        "id": user_info["id"],
        "email": user_info["email"],
        "first_name": user_info["first_name"],
        "middle_name": user_info["middle_name"],
        "last_name": user_info["last_name"],
        "manager": user_info["manager"],
        "employer": user_info["employer"],
        "phone": user_info["phone"],
    }
    return cleaned_user_info

# ------------------------------ VACANCY related calls ------------------------------

def _get_fake_vacancies_data() -> Optional[dict]:
    """Load fake vacancies data from JSON file for testing when HH API is unavailable."""
    try:
        # Get project root (go up from shared_services to project root)
        project_root = Path(__file__).parent.parent
        fake_data_path = project_root / "test_data" / "fake_vacancies.json"
        
        if fake_data_path.exists():
            with open(fake_data_path, "r", encoding="utf-8") as f:
                fake_data = json.load(f)
            logger.info(f"Loaded fake vacancies data from {fake_data_path}")
            return fake_data
        else:
            logger.warning(f"Fake vacancies file not found at {fake_data_path}")
            return None
    except Exception as e:
        logger.error(f"Error loading fake vacancies data: {e}", exc_info=True)
        return None


def get_employer_vacancies_from_hh(access_token: str, employer_id: str) -> Optional[dict]:
    '''
    url = f"https://api.hh.ru/employers/{employer_id}/vacancies/active"
    try:
        r = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=10,
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting employer vacancies: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting employer vacancies: {e}", exc_info=True)
        return None
        '''

    #  !!!!!!! DELETE AFTER TESTING !!!!!!!
    #  !!!!!!! DELETE AFTER TESTING !!!!!!!
    #  !!!!!!! DELETE AFTER TESTING !!!!!!!

    # Fallback to fake data when HH API is unavailable
    return _get_fake_vacancies_data()

    #  !!!!!!! DELETE AFTER TESTING !!!!!!!
    #  !!!!!!! DELETE AFTER TESTING !!!!!!!
    #  !!!!!!! DELETE AFTER TESTING !!!!!!!

def filter_open_employer_vacancies(vacancies_json: dict, status_to_filter: str) -> dict:
    """
    Build a JSON-ready dict of open vacancies from HH.ru response.
    Args:
        vacancies_json (dict): JSON object from HH.ru API containing vacancies
    Returns:
        dict: {"<vacancy_id>": {"id": "<id>", "name": "<name>"}, ...}
    """
    result = {}

    # Get items list from JSON
    items = vacancies_json.get("items", [])

    # Extract id and name from each item with status open
    for item in items:
        # Validate that vacancy has status open ("type":{"id": "open"}
        item_type = item.get("type")
        if not item_type or item_type.get("id") != status_to_filter:
            continue

        vacancy_id = item.get("id")
        vacancy_name = item.get("name")

        if vacancy_id and vacancy_name:
            result[str(vacancy_id)] = {"id": str(vacancy_id), "name": vacancy_name, "status": status_to_filter}

    return result


def get_vacancy_description_from_hh(access_token: str, vacancy_id: str) -> Optional[dict]:
    """Get vacancy description from HH.ru API and return it as a dictionary"""
    try:
        r = requests.get(
            f"https://api.hh.ru/vacancies/{vacancy_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=10,
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting vacancy description: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting vacancy description: {e}", exc_info=True)
        return None

# ------------------------------ NEGOTIATIONS related calls ------------------------------

def get_available_employer_states_and_collections_negotiations(access_token: str, vacancy_id: str) -> Optional[dict]:
    """Returns the list of negotiations for a vacancy"""
    try:
        r = requests.get(
            "https://api.hh.ru/negotiations",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            params={
                "vacancy_id": vacancy_id
            },
            timeout=15,
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting negotiations: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting negotiations: {e}", exc_info=True)
        return None


def get_negotiations_by_collection(access_token: str, vacancy_id: str, collection: str) -> Optional[dict]:
    try:
        url = f"https://api.hh.ru/negotiations/{collection}?vacancy_id={vacancy_id}"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting negotiations by collection: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting negotiations by collection: {e}", exc_info=True)
        return None


def get_negotiations_collection_with_status_response(access_token: str, vacancy_id: str) -> Optional[dict]:
    """
    Get all pages of the negotiations collection with status "response".
    Returns a dictionary with the following keys:
    - items: list of items
    - found: total number of items
    - pages: total number of pages
    - per_page: number of items per page
    More info on the HH API: Список откликов/приглашений коллекции
    https://api.hh.ru/openapi/redoc#tag/Otklikipriglasheniya-rabotodatelya/operation/get-collection-negotiations-list"""
    try:
        page = 0
        per_page = 50
        all_items = []
        collection = EMPLOYER_STATE_RESPONSE

        url = f"https://api.hh.ru/negotiations/{collection}"
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT}
        params = {
                "vacancy_id": vacancy_id,
                "per_page": per_page,
                "page": page,   # не page_number!
            }
        
        # Fetch first page
        r = requests.get(
            url,
            headers=headers,
            timeout=15,
            params=params
        )
        r.raise_for_status()
        
        if r.status_code == 200:
            data = r.json()
            total_pages = data.get("pages", 1)
            found = data.get("found", 0)
            
            # Collect items from first page
            items = data.get("items", [])
            all_items.extend(items)
            logger.debug(f"get_negotiations_collection_with_status_response: page {page} fetched successfully ({len(items)} items)")
            
            # Fetch remaining pages
            while page + 1 < total_pages:
                page += 1
                r = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
                    timeout=15,
                    params={"vacancy_id": vacancy_id, "per_page": 50, "page": page}
                )
                r.raise_for_status()
                
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("items", [])
                    all_items.extend(items)
                    logger.debug(f"get_negotiations_collection_with_status_response: page {page} fetched successfully ({len(items)} items)")
                else:
                    logger.error(f"get_negotiations_collection_with_status_response: request failed for page {page}: {r.status_code} {r.text}")
            # Combine all pages into a single structure
            combined_data = {
                "items": all_items,
                "found": found,
                "pages": total_pages,
                "per_page": per_page
            }            
            logger.debug(f"get_negotiations_collection_with_status_response: Returning combined data")
            return combined_data
        else:
            logger.error(f"get_negotiations_collection_with_status_response: request failed: {r.status_code} {r.text}. Returning None.")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error get_negotiations_collection_with_status_response: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error get_negotiations_collection_with_status_response: {e}", exc_info=True)
        return None


def get_negotiations_by_state(access_token: str, vacancy_id: str, state_id: str) -> Optional[dict]:
    """Get negotiations by state to see what collections are available"""
    try:
        url = f"https://api.hh.ru/negotiations/?vacancy_id={vacancy_id}&state={state_id}"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting negotiations by state: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting negotiations by state: {e}", exc_info=True)
        return None


def get_negotiations_messages(access_token: str, negotiation_id: str) -> Optional[dict]:
    try:
        url = f"https://api.hh.ru/negotiations/{negotiation_id}/messages"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting negotiation messages: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting negotiation messages: {e}", exc_info=True)
        return None


def change_negotiation_collection_status_to_consider(
    access_token: str, 
    negotiation_id: str,
    ):
    try:
        target_collection_name = EMPLOYER_STATE_CONSIDER
        url = f"https://api.hh.ru/negotiations/{target_collection_name}/{negotiation_id}"
        r = requests.put(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15,
        )
        r.raise_for_status()
        if r.status_code in (200, 201, 204):
            logger.debug(f"change_negotiation_collection_status_to_consider: request successful: {r.text}")
            # Some HH endpoints return 204 No Content or empty body on success
            if r.text and r.headers.get("Content-Type", "").startswith("application/json"):
                try:
                    return r.json()
                except Exception:
                    pass
            return {"status": "success", "code": r.status_code}
        else:
            logger.error(f"change_negotiation_collection_status_to_consider: request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error change_negotiation_collection_status_to_consider: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error change_negotiation_collection_status_to_consider: {e}", exc_info=True)
        return None


def send_negotiation_message(access_token: str, negotiation_id: str, user_message: str):
    try:
        user_message_formatted = user_message.strip()
        url = f"https://api.hh.ru/negotiations/{negotiation_id}/messages"
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=15,
            params={"message": f"{user_message_formatted}"}
        )
        r.raise_for_status()
        if r.status_code in (200, 201):
            logger.debug(f"request successful: {r.status_code} - {r.text}")
            # Some HH endpoints return 201 Created with empty body
            if r.text and r.headers.get("Content-Type", "").startswith("application/json"):
                try:
                    return r.json()
                except Exception:
                    pass
            return {"status": "success", "code": r.status_code}
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error sending negotiation message: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error sending negotiation message: {e}", exc_info=True)
        return None


def get_negotiations_history(access_token: str, resume_id: str):
    try:
        url = f"https://api.hh.ru/resumes/{resume_id}/negotiations_history"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15,
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting negotiations history: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting negotiations history: {e}", exc_info=True)
        return None


# ------------------------------ RESUME related calls ------------------------------

def get_resume_info(access_token: str, resume_id: str):
    try:
        url = f"https://api.hh.ru/resumes/{resume_id}"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT},
            timeout=15
        )
        r.raise_for_status()
        if r.status_code == 200:
            logger.debug(f"request successful: {r.text}")
            return r.json()
        else:
            logger.error(f"request failed: {r.status_code} {r.text}")
            return None
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting resume info: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting resume info: {e}", exc_info=True)
        return None


# ------------------------------ SUPPORTING functions ------------------------------

def get_dictionary_from_hh(access_token: str):
    """Get dictionary from HH.ru API and write it to a JSON file"""
    try:
        r = requests.get(
            "https://api.hh.ru/dictionaries",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=10,
        )
        r.raise_for_status()
        if r.status_code == 200:
            hh_dictionaries_file_path = Path("docs") / "hh_dictionaries.json"
            create_json_file_with_dictionary_content(file_path=hh_dictionaries_file_path, content_to_write=r.json())
            logger.debug(f"dictionaries written to {Path('docs') / 'hh_dictionaries.json'}")
        else:
            logger.error(f"Error: {r.status_code} {r.text}")
    except Exception as e:
        if isinstance(e, requests.exceptions.HTTPError):
            logger.error(f"HTTP error getting dictionary: {e.response.status_code} - {e.response.text}")
        else:
            logger.error(f"Error getting dictionary: {e}", exc_info=True)

