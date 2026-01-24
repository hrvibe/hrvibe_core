# TAGS: [status_validation], [applicant_bot_usage]


import json
import logging
from pathlib import Path
from services.data_service import get_applicant_bot_records_file_path, get_vacancy_directory

logger = logging.getLogger(__name__)



# ****** METHODS with TAGS: [status_validation] ******

def is_applicant_in_applicant_bot_records(applicant_record_id: str) -> bool:
    # TAGS: [status_validation],[applicant_bot_usage]
    """Check if user is in records."""
    applicant_bot_records_file_path = get_applicant_bot_records_file_path()
    if applicant_bot_records_file_path is None:
        logger.debug(f"Applicant bot records file path does not exist, cannot check if applicant_record_id: {applicant_record_id} is in records")
        return False
    
    if not applicant_bot_records_file_path.exists():
        logger.debug(f"Applicant bot records file does not exist, applicant_record_id: {applicant_record_id} not found in records")
        return False
    
    try:
        with open(applicant_bot_records_file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.debug(f"Applicant bot records file is empty, applicant_record_id: {applicant_record_id} not found in records")
                return False
            applicant_bot_records = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from applicant bot records file: {e}")
        return False
    
    if applicant_record_id in applicant_bot_records:
        logger.debug(f"'applicant_record_id': {applicant_record_id} found in records")
        return True
    else:
        logger.debug(f"'applicant_record_id': {applicant_record_id} not found in records")
        return False


def is_applicant_privacy_policy_confirmed(applicant_record_id: str) -> bool:
    # TAGS: [status_validation],[applicant_bot_usage]
    """Check if privacy policy is confirmed."""
    applicant_bot_records_file_path = get_applicant_bot_records_file_path()
    if applicant_bot_records_file_path is None:
        logger.debug(f"Applicant bot records file path does not exist, cannot check privacy policy confirmation for applicant_record_id: {applicant_record_id}")
        return False
    
    if not applicant_bot_records_file_path.exists():
        logger.debug(f"Applicant bot records file does not exist, privacy policy not confirmed for applicant_record_id: {applicant_record_id}")
        return False
    
    try:
        with open(applicant_bot_records_file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.debug(f"Applicant bot records file is empty, privacy policy not confirmed for applicant_record_id: {applicant_record_id}")
                return False
            applicant_bot_records = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from applicant bot records file: {e}")
        return False
    
    if applicant_record_id in applicant_bot_records:
        if applicant_bot_records[applicant_record_id]["privacy_policy_confirmed"] == "yes":
            logger.debug(f"privacy_policy is confirmed for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return True
        else:
            logger.debug(f"privacy_policy is NOT confirmed for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return False
    else:
        logger.debug(f"'applicant_record_id': {applicant_record_id} is not found in {applicant_bot_records_file_path}")
        return False


def is_welcome_video_shown_to_applicant(applicant_record_id: str) -> bool:
    # TAGS: [status_validation],[applicant_bot_usage]
    """Check if welcome video is shown."""
    applicant_bot_records_file_path = get_applicant_bot_records_file_path()
    if applicant_bot_records_file_path is None:
        logger.debug(f"Applicant bot records file path does not exist, cannot check welcome video status for applicant_record_id: {applicant_record_id}")
        return False
    
    if not applicant_bot_records_file_path.exists():
        logger.debug(f"Applicant bot records file does not exist, welcome video not shown for applicant_record_id: {applicant_record_id}")
        return False
    
    try:
        with open(applicant_bot_records_file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.debug(f"Applicant bot records file is empty, welcome video not shown for applicant_record_id: {applicant_record_id}")
                return False
            applicant_bot_records = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from applicant bot records file: {e}")
        return False
    
    if applicant_record_id in applicant_bot_records:
        if applicant_bot_records[applicant_record_id]["welcome_video_shown"] == "yes":
            logger.debug(f"welcome video is shown for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return True
        else:
            logger.debug(f"welcome video is NOT shown for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return False
    else:
        logger.debug(f"'applicant_record_id': {applicant_record_id} is not found in {applicant_bot_records_file_path}")
        return False


def is_resume_video_received(applicant_record_id: str) -> bool:
    # TAGS: [status_validation],[applicant_bot_usage]
    """Check if resume video is received."""
    applicant_bot_records_file_path = get_applicant_bot_records_file_path()
    if applicant_bot_records_file_path is None:
        logger.debug(f"Applicant bot records file path does not exist, cannot check resume video status for applicant_record_id: {applicant_record_id}")
        return False
    
    if not applicant_bot_records_file_path.exists():
        logger.debug(f"Applicant bot records file does not exist, resume video not received for applicant_record_id: {applicant_record_id}")
        return False
    
    try:
        with open(applicant_bot_records_file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.debug(f"Applicant bot records file is empty, resume video not received for applicant_record_id: {applicant_record_id}")
                return False
            applicant_bot_records = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from applicant bot records file: {e}")
        return False
    
    if applicant_record_id in applicant_bot_records:
        if applicant_bot_records[applicant_record_id]["resume_video_received"] == "yes":
            logger.debug(f"resume video is received for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return True
        else:
            logger.debug(f"resume video is NOT received for 'applicant_record_id': {applicant_record_id} in {applicant_bot_records_file_path}")
            return False
    else:
        logger.debug(f"'applicant_record_id': {applicant_record_id} is not found in {applicant_bot_records_file_path}")
        return False


def is_vacancy_exist(user_record_id: str, vacancy_id: str) -> bool:
    # TAGS: [status_validation],[applicant_bot_usage]
    """Check if vacancy exists."""
    vacancy_records_file_path = get_vacancy_directory(user_record_id=user_record_id, vacancy_id=vacancy_id)
    if vacancy_records_file_path is None:
        logger.debug(f"Vacancy {vacancy_id} not found for manager {user_record_id}")
        return False
    return True