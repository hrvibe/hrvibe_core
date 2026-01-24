# TAGS: [status_validation], [get_data], [create_data], [update_data], [directory_path], [file_path], [persistent_keyboard], [format_data]

import os
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Type

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

from shared_services.constants import (
    USERS_RECORDS_FILENAME, 
    RESUME_RECORDS_FILENAME,
    BOT_FOR_APPLICANTS_USERNAME,
    )
from shared_services.db_service import (
    is_value_in_db,
    is_boolean_field_true_in_db,
    get_column_value_in_db,
)

from database import Base, Managers


def create_json_file_with_dictionary_content(file_path: Path, content_to_write: dict) -> None:
    # TAGS: [create_data],[file_path]
    """Create a JSON file from a dictionary.
    If file already exists, it will be overwritten."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(content_to_write, f, ensure_ascii=False, indent=2)
    logger.debug(f"Content written to {file_path}")


def get_employer_id_from_json_value_from_db(db_model: Type[Base], record_id: str) -> Optional[str]:
    """Get employer id from JSON value from database. TAGS: [get_data]"""
    hh_data = get_column_value_in_db(db_model, record_id, "hh_data")
    if not isinstance(hh_data, dict):
        logger.debug(f"'record_id': {record_id} not found in DB or hh_data is empty")
        return None

    employer_id = hh_data.get("employer", {}).get("id")
    if employer_id:
        logger.debug(f"'employer_id': {employer_id} found for 'bot_user_id': {record_id} in DB")
        return employer_id

    logger.debug(f"'employer_id' not found in hh_data for 'bot_user_id': {record_id}")
    return None



# ****** METHODS with TAGS: [create_data] ******

def _resolve_users_data_dir() -> Path:
    """Resolve USERS_DATA_DIR relative to the project root if it is not absolute."""
    # shared_services is one level below project root
    project_root = Path(__file__).parent.parent
    users_data_env = os.getenv("USERS_DATA_DIR", "./users_data")
    users_data_path = Path(users_data_env)

    if users_data_path.is_absolute():
        # If absolute path provided, use it as-is
        return users_data_path

    # If relative path, resolve it relative to the project root
    # Strip leading './' to avoid double separators
    return project_root / users_data_env.lstrip("./")


def create_data_directories() -> Path:
    # TAGS: [create_data],[directory_path]
    """Create a directory for all data (users_data) and its subdirectories.

    For local development, USERS_DATA_DIR is typically ./users_data, which will be
    resolved relative to the project root, not the current working directory.
    """
    data_dir = _resolve_users_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    list_of_sub_directories = ["videos", "audio", "negotiations", "resumes"]
    for sub_directory in list_of_sub_directories:
        sub_directory_path = data_dir / sub_directory
        sub_directory_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"{sub_directory_path} created or exists.")
    logger.debug(f"{data_dir} created or exists.")
    return data_dir


def get_tg_user_data_attribute_from_update_object(update: Update, tg_user_attribute: str) -> str | int | None | bool | list | dict:
    """Collects Telegram user data from context and returns it as a dictionary. TAGS: [get_data]"""
    tg_user = update.effective_user
    if tg_user:
        tg_user_attribute_value = tg_user.__getattribute__(tg_user_attribute)
        logger.debug(f"'{tg_user_attribute}': {tg_user_attribute_value} found in update.")
        return tg_user_attribute_value 
    else:
        logger.warning(f"'{tg_user_attribute}' not found in update. CHECK CORRECTNESS OF THE ATTRIBUTE NAME")
        return None


def create_oauth_link(state: str) -> str:
    # TAGS: [create_data]
    """
    Get the OAuth link for HH.ru authentication.
    """
    hh_client_id = os.getenv("HH_CLIENT_ID")
    if not hh_client_id:
        raise ValueError("HH_CLIENT_ID is not set in environment variables")
    oauth_redirect_url = os.getenv("OAUTH_REDIRECT_URL")
    if not oauth_redirect_url:
        raise ValueError("OAUTH_REDIRECT_URL is not set in environment variables")
    auth_link = f"https://hh.ru/oauth/authorize?response_type=code&client_id={hh_client_id}&state={state}&redirect_uri={oauth_redirect_url}"
    return auth_link


def create_tg_bot_link_for_applicant(bot_user_id: str, vacancy_id: str, resume_id: str) -> str:
    """Create Telegram bot link for applicant to start the bot. TAGS: [create_data]
    When the user taps it, Telegram sends your bot /start <payload>
    The payload is read from message.from.id (Telegram user_id) and the <payload> in the same update and persist the mapping.
    Example: https://t.me/{BOT_FOR_APPLICANTS_USERNAME}?start={bot_user_id}_{vacancy_id}_{resume_id}"""
    payload = f"{bot_user_id}_{vacancy_id}_{resume_id}"
    return f"https://t.me/{BOT_FOR_APPLICANTS_USERNAME}?start={payload}"

# ****** METHODS with TAGS: [get_data] ******

def get_data_directory() -> Path:
    # TAGS: [get_data],[directory_path]
    """Get the directory path for user data."""
    data_dir = _resolve_users_data_dir()
    # return it if data_dir exists
    if data_dir.exists():
        return data_dir
    # create it and return the path if it doesn't exist
    else:
        data_dir = create_data_directories()
        return data_dir


def get_data_subdirectory_path(subdirectory_name: str) -> Path:
    # TAGS: [get_data],[directory_path]
    """Get the directory path for a subdirectory of user data."""
    allowed_subdirectories = ["videos", "audio", "negotiations", "resumes"]
    if subdirectory_name not in allowed_subdirectories:
        logger.error(f"Invalid subdirectory name: {subdirectory_name}")
        return None
    data_dir = get_data_directory()
    subdirectory_path = data_dir / subdirectory_name
    if subdirectory_path.exists():
        return subdirectory_path
    else:
        logger.debug(f"{subdirectory_path} does not exist.")
        return None


def get_decision_status_from_selected_callback_code(selected_callback_code: str) -> str:
    #TAGS: [get_data]
    """Extract the meaningful part of a callback code.
    Args:
        selected_callback_code (str): Selected callback code, e.g. 'action_code:value'
    Returns:
        str: The part after the last colon, or the original string if no colon is present.
    """
    if ":" in selected_callback_code:
        return selected_callback_code.split(":")[-1].strip()
    else:
        return selected_callback_code


def get_access_token_from_callback_endpoint_resp(endpoint_response: dict) -> Optional[str]:
    # TAGS: [get_data]
    """Get access token from endpoint response. TAGS: [get_data]"""
    if isinstance(endpoint_response, dict):
        # return access_token if it exists in endpoint_response, otherwise return None
        return endpoint_response.get("access_token", None)
    else:
        logger.debug(f"'endpoint_response' is not a dictionary: {endpoint_response}")
        return None


def get_expires_at_from_callback_endpoint_resp(endpoint_response: dict) -> Optional[int]:
    """Get expires_at from endpoint response. TAGS: [get_data]"""
    if isinstance(endpoint_response, dict):
        return endpoint_response.get("expires_at", None)
    else:
        logger.debug(f"'endpoint_response' is not a dictionary: {endpoint_response}")
        return None

def get_reply_from_update_object(update: Update):
    """ Get user reply to from the update object if user did one of below. TAGS: [get_data].
    1. sent message (text, photo, video, etc.) - update.message OR
    2. clicked button - update.callback_query.message
    If none of the above, return None
    """
    if update.message:
        return update.message.reply_text
    elif update.callback_query and update.callback_query.message:
        return update.callback_query.message.reply_text
    else:
        return None

# ****** METHODS with TAGS: [format_data] ******

def format_oauth_link_text(oauth_link: str) -> str:
    # TAGS: [format_data]
    """Format oauth link text. TAGS: [format_data]"""
    return f"<a href=\"{oauth_link}\">Ссылка для авторизации</a>"


def is_vacany_data_enough_for_resume_analysis(user_id: str) -> bool:
    # TAGS: [status_validation]
    """
    Check if everything is ready for resume analysis.
    Validates that user is authorized, vacancy is selected, vacancy description is received, and sourcing criterias are received.
    """
    return (
        is_value_in_db(db_model=Managers, field_name="id", value=user_id) and
        is_boolean_field_true_in_db(db_model=Managers, record_id=user_id, field_name="vacancy_selected") and
        is_boolean_field_true_in_db(db_model=Managers, record_id=user_id, field_name="vacancy_description_recieved") and
        is_boolean_field_true_in_db(db_model=Managers, record_id=user_id, field_name="vacancy_sourcing_criterias_recieved")
    )



# ****** METHODS with TAGS: [persistent_keyboard] ******

'''
def get_persistent_keyboard_messages(bot_user_id: str) -> list[tuple[int, int]]:
    # TAGS: [persistent_keyboard]
    """Get persistent keyboard message IDs for a user. Returns list of (chat_id, message_id) tuples."""
    users_records_file_path = get_users_records_file_path()
    try:
        with open(users_records_file_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        if bot_user_id in records:
            keyboard_messages = records[bot_user_id].get("messages_with_keyboards", [])
            # Convert list of lists to list of tuples
            return [tuple(msg) for msg in keyboard_messages if isinstance(msg, (list, tuple)) and len(msg) == 2]
        return []
    except Exception as e:
        logger.error(f"Error reading keyboard messages for {bot_user_id}: {e}")
        return []
'''

def get_persistent_keyboard_messages_from_db(bot_user_id: str) -> list[tuple[int, int]]:
    # TAGS: [persistent_keyboard]
    """Get persistent keyboard message IDs for a user. Returns list of (chat_id, message_id) tuples."""
    try:
        if is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            keyboard_messages = get_column_value_in_db(
                db_model=Managers,
                record_id=bot_user_id,
                field_name="messages_with_keyboards",
            )
            # Convert list of lists to list of tuples
            return [tuple(msg) for msg in keyboard_messages if isinstance(msg, (list, tuple)) and len(msg) == 2]
        return []
    except Exception as e:
        logger.error(f"Error reading keyboard messages for {bot_user_id}: {e}")
        return []

'''
def add_persistent_keyboard_message(bot_user_id: str, chat_id: int, message_id: int) -> None:
    # TAGS: [persistent_keyboard]
    """Add a keyboard message ID to persistent storage."""
    users_records_file_path = get_users_records_file_path()
    try:
        with open(users_records_file_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        
        bot_user_id_str = str(bot_user_id)
        if bot_user_id_str not in records:
            logger.debug(f"User {bot_user_id_str} not found in records, cannot track keyboard")
            return
        
        if "messages_with_keyboards" not in records[bot_user_id_str]:
            records[bot_user_id_str]["messages_with_keyboards"] = []
        
        # Add if not already present
        keyboard_messages = records[bot_user_id_str]["messages_with_keyboards"]
        if [chat_id, message_id] not in keyboard_messages:
            keyboard_messages.append([chat_id, message_id])
            records[bot_user_id_str]["messages_with_keyboards"] = keyboard_messages
            users_records_file_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"Added keyboard message {message_id} to persistent storage for user {bot_user_id_str}")
    except Exception as e:
        logger.error(f"Error adding keyboard message to persistent storage: {e}")
'''

def add_persistent_keyboard_message_in_db(bot_user_id: str, chat_id: int, message_id: int) -> None:
    # TAGS: [persistent_keyboard]
    """Add a keyboard message ID to persistent storage in DB."""
    method_name = "add_persistent_keyboard_message_in_db"
    try:
        keyboard_messages = get_column_value_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            field_name="messages_with_keyboards",
        )

        if keyboard_messages is None:
            keyboard_messages = []
        elif not isinstance(keyboard_messages, list):
            logger.warning(f"{method_name}: invalid type for messages_with_keyboards, resetting")
            keyboard_messages = []

        if [chat_id, message_id] not in keyboard_messages:
            keyboard_messages.append([chat_id, message_id])
            update_record_in_db(
                record_id=bot_user_id,
                db_model=Managers,
                updates={"messages_with_keyboards": keyboard_messages},
            )
            logger.debug(
                f"{method_name}: added message {message_id} for user {bot_user_id}"
            )
    except Exception as e:
        logger.error(f"{method_name}: error adding keyboard message: {e}")

'''
def remove_persistent_keyboard_message(bot_user_id: str, chat_id: int, message_id: int) -> None:
    # TAGS: [persistent_keyboard]
    """Remove a keyboard message ID from persistent storage."""
    users_records_file_path = get_users_records_file_path()
    try:
        with open(users_records_file_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        
        bot_user_id_str = str(bot_user_id)
        if bot_user_id_str not in records:
            return
        
        if "messages_with_keyboards" in records[bot_user_id_str]:
            keyboard_messages = records[bot_user_id_str]["messages_with_keyboards"]
            records[bot_user_id_str]["messages_with_keyboards"] = [
                msg for msg in keyboard_messages if not (msg[0] == chat_id and msg[1] == message_id)
            ]
            users_records_file_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"Removed keyboard message {message_id} from persistent storage for user {bot_user_id_str}")
    except Exception as e:
        logger.error(f"Error removing keyboard message from persistent storage: {e}")
'''

def remove_persistent_keyboard_message_from_db(bot_user_id: str, chat_id: int, message_id: int) -> None:
    # TAGS: [persistent_keyboard]
    """Remove a keyboard message ID from persistent storage in DB."""
    try:
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            return

        keyboard_messages = get_column_value_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            field_name="messages_with_keyboards",
        )
        if not isinstance(keyboard_messages, list):
            keyboard_messages = []

        keyboard_messages = [
            msg for msg in keyboard_messages if not (msg[0] == chat_id and msg[1] == message_id)
        ]
        update_record_in_db(
            record_id=bot_user_id,
            db_model=Managers,
            updates={"messages_with_keyboards": keyboard_messages},
        )
        logger.debug(f"Removed keyboard message {message_id} from persistent storage for user {bot_user_id}")
    except Exception as e:
        logger.error(f"Error removing keyboard message from persistent storage: {e}")

'''
def clear_all_persistent_keyboard_messages(bot_user_id: str) -> None:
    # TAGS: [persistent_keyboard]
    """Clear all persistent keyboard messages for a user."""
    users_records_file_path = get_users_records_file_path()
    try:
        with open(users_records_file_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        
        bot_user_id_str = str(bot_user_id)
        if bot_user_id_str in records:
            records[bot_user_id_str]["messages_with_keyboards"] = []
            users_records_file_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"Cleared all persistent keyboard messages for user {bot_user_id_str}")
    except Exception as e:
        logger.error(f"Error clearing persistent keyboard messages: {e}")    
'''

def clear_all_persistent_keyboard_messages_from_db(bot_user_id: str) -> None:
    # TAGS: [persistent_keyboard]
    """Clear all persistent keyboard messages for a user."""
    try:
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            return
        clear_column_value_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            field_name="messages_with_keyboards",
        )
        logger.debug(f"Cleared all persistent keyboard messages for user {bot_user_id}")
    except Exception as e:
        logger.error(f"Error clearing persistent keyboard messages: {e}")    


# ****** METHODS with TAGS: [format_data] ******


def create_resume_records_file(bot_user_id: str, vacancy_id: str) -> None:
    # TAGS: [create_data],[file_path]
    """Create a file with resume data records if it doesn't exist."""
    resume_data_dir = ""
    if resume_data_dir is None:
        raise ValueError(f"Resume directory not found for user {bot_user_id} and vacancy {vacancy_id}. Vacancy directory may not exist or resumes directory may not be created.")
    resume_records_file_path = resume_data_dir / f"{RESUME_RECORDS_FILENAME}.json"
    if not resume_records_file_path.exists():
        resume_records_file_path.write_text(json.dumps({}), encoding="utf-8")
        logger.debug(f"{resume_records_file_path} created.")
    else:
        logger.debug(f"{resume_records_file_path} already exists.")


def get_resume_records_file_path(bot_user_id: str, vacancy_id: str) -> Path:
    # TAGS: [get_data],[file_path]
    """Get the path for a resume records file."""
    resume_data_dir = ""
    if resume_data_dir is None:
        raise ValueError(f"Resume directory not found for user {bot_user_id} and vacancy {vacancy_id}. Vacancy directory may not exist or resumes directory may not be created.")
    resume_records_file_path = resume_data_dir / f"{RESUME_RECORDS_FILENAME}.json"
    if resume_records_file_path.exists():
        logger.debug(f"'{RESUME_RECORDS_FILENAME}' found in {resume_data_dir}")
        return resume_records_file_path
    else:
        # Create the file if it doesn't exist
        create_resume_records_file(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
        logger.debug(f"'{RESUME_RECORDS_FILENAME}' created in {resume_data_dir}")
        return resume_records_file_path

def get_list_of_resume_ids_for_recommendation(bot_user_id: str, vacancy_id: str) -> list[str]:
    # TAGS: [get_data]
    """Get list of resume IDs for recommendation.
    Criterias:
    1. Resume is passed
    2. Resume has video
    3. Resume is not recommended yet
    """
    resume_records_file_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
    with open(resume_records_file_path, "r", encoding="utf-8") as f:
        resume_records = json.load(f)
    logger.debug(f"get_list_of_resume_ids_for_recommendation: Resume records path: {resume_records}")

    recommendation_list = []
    for resume_id, resume_record_data in resume_records.items():
        # Check if resume is passed and not recommended yet without video
        if resume_record_data["resume_sorting_status"] == "passed":
            logger.debug(f"get_list_of_resume_ids_for_recommendation: Resume {resume_id} is passed")
            if resume_record_data.get("resume_recommended", "no") == "no" or resume_record_data.get("resume_recommended", "") == "":
                logger.debug(f"get_list_of_resume_ids_for_recommendation: Resume {resume_id} is not recommended yet")
                recommendation_list.append(resume_id)
            """
            # Collect resume id for passed resumes WITH video
            if resume_record_data["resume_video_received"] == "yes":
                if resume_record_data.get("resume_recommended", "no") == "no":
                    recommendation_list.append(resume_id)
            """
        else:
            logger.debug(f"get_list_of_resume_ids_for_recommendation: Resume {resume_id} is not passed")
    logger.debug(f"get_list_of_resume_ids_for_recommendation: List of resume IDs for recommendation: {recommendation_list}")
    return recommendation_list


def get_negotiation_id_from_resume_record(bot_user_id: str, vacancy_id: str, resume_record_id: str) -> Optional[str]:
    # TAGS: [get_data]
    """Get negotiation id from resume record."""
    resume_records_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
    with open(resume_records_path, "r", encoding="utf-8") as f:
        resume_records = json.load(f)
    return resume_records[resume_record_id]["negotiation_id"]


def get_resume_recommendation_text_from_resume_records(bot_user_id: str, vacancy_id: str, resume_record_id: str) -> str:
    # TAGS: [get_data]
    """Get resume recommendation text from resume records."""
    resume_records_file_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
    # Read existing data
    with open(resume_records_file_path, "r", encoding="utf-8") as f:
        resume_records = json.load(f)
    
    resume_record_id_data = resume_records[resume_record_id]

    # ----- GET VALUES for TEXT -----

    first_name = resume_record_id_data["first_name"]
    last_name = resume_record_id_data["last_name"]
    final_score = resume_record_id_data["ai_analysis"]["final_score"]
    recommendation = resume_record_id_data["ai_analysis"]["recommendation"]
    attention = resume_record_id_data["ai_analysis"]["requirements_compliance"]["attention"]

    if not first_name or not last_name or not final_score or not recommendation or not attention:
        raise ValueError(f"Missing required values for recommendation text for 'resume_record_id': {resume_record_id}")
    
    # ----- FORMAT ATTENTION list to present each item on a new line -----

    if isinstance(attention, list):
        attention_text = "\n".join(f"- {item}" for item in attention)
    else:
        attention_text = str(attention)

    # ----- FORMAT RECOMMENDATION TEXT and send message -----

    recommendation_text = (
        f"<b>Имя</b>: {first_name} {last_name}\n"
        f"<b>Общий балл</b>: <b>{final_score}</b> из 10\n"
        f"--------------------\n"
        f"<b>Рекомендация:</b>\n{recommendation}\n"
        f"--------------------\n"
        f"<b>Обратить внимание:</b>\n{attention_text}"
    )
    return recommendation_text



def get_path_to_video_from_applicant_from_resume_records(bot_user_id: str, vacancy_id: str, resume_record_id: str) -> Path:
    """Get path to video from applicant from resume records. TAGS: [get_data]"""
    resume_records_file_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
    # Read existing data
    with open(resume_records_file_path, "r", encoding="utf-8") as f:
        resume_records = json.load(f)
    video_path_value = resume_records[resume_record_id].get("resume_video_path")
    if video_path_value is None:
        raise ValueError(f"'resume_video_path' not found for 'resume_record_id': {resume_record_id}")
    return Path(video_path_value)

'''
def get_employer_id_from_records(record_id: str) -> Optional[str]:
    """Get employer id from users records. TAGS: [get_data]"""
    users_records_file_path = get_users_records_file_path()
    with open(users_records_file_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    if record_id in records:
        employer_id = records[record_id]["data_from_hh"]["employer"]["id"]
        logger.debug(f"'employer_id': {employer_id} found for 'bot_user_id': {record_id} in {users_records_file_path}")
        return employer_id
    else:
        logger.debug(f"'record_id': {record_id} not found in {users_records_file_path}")
        return None


def get_list_of_users_from_records() -> list[str]:
    # TAGS: [get_data]
    """Get list of users from users records."""
    users_records_file_path = get_users_records_file_path()
    with open(users_records_file_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    return list(records.keys())


# ****** METHODS with TAGS: [update_data] ******
'''

def update_user_records_with_top_level_key(record_id: int | str, key: str, value: str | int | bool | dict | list) -> None:
    # TAGS: [update_data]
    """Only updates if the user_id exists in the JSON."""
    try:
        users_records_path = ""
        # Read existing data
        with open(users_records_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        
        # Convert user_id to string since JSON keys are always strings
        record_id_str = str(record_id)
        
        if record_id_str in records:
            records[record_id_str][key] = value
            users_records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"{record_id_str} has been successfully updated with {key}={value}")
        else:
            raise ValueError(f"User record {record_id_str} does not exist in the file {users_records_path}")
    except Exception as e:
        raise ValueError(f"Error updating user records with top level key: {e}")

'''
def update_resume_record_with_top_level_key(bot_user_id: str, vacancy_id: str, resume_record_id: str, key: str, value: str | int | bool | dict | list) -> None:
    """Update resume record with new resume data. TAGS: [update_data]"""
    try:
        resume_records_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
        with open(resume_records_path, "r", encoding="utf-8") as f:
            resume_records = json.load(f)
        if resume_record_id in resume_records:
            resume_records[resume_record_id][key] = value
            resume_records_path.write_text(json.dumps(resume_records, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"{resume_records_path} has been successfully updated with {key}={value}")
        else:
            raise ValueError(f"Resume record {resume_record_id} does not exist in the file {resume_records_path}")
    except Exception as e:
        raise ValueError(f"Error updating resume record with top level key: {e}")
'''

