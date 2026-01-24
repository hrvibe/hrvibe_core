# TAGS: [admin], [user_related], [vacancy_related], [resume_related], [recommendation_related]

from ast import Pass
import asyncio
import logging
import sys
from datetime import datetime, timezone
from multiprocessing import process
from pathlib import Path
from typing import Optional, List, Tuple
import os
import json
import shutil
import re

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

# Module-level storage for sourcing criterias confirmation answer options
# Used as fallback when application.user_data is read-only (mappingproxy)
_sourcing_criterias_confirmation_options_storage: dict[int, list] = {}

from pydantic.type_adapter import P
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.constants import ParseMode
from telegram.ext import (  
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram.error import TelegramError

from shared_services.video_service import (
    process_incoming_video,
    download_incoming_video_locally,
    get_data_subdirectory_path
)
from shared_services.audio_service import (
    process_incoming_audio,
)


from shared_services.auth_service import (
    get_token_by_state,
    callback_endpoint_healthcheck,
    BOT_SHARED_SECRET,
)

from shared_services.hh_service import (
    get_user_info_from_hh, 
    clean_user_info_received_from_hh,
    get_employer_vacancies_from_hh,
    filter_open_employer_vacancies,
    get_vacancy_description_from_hh,
    get_negotiations_collection_with_status_response,
    change_negotiation_collection_status_to_consider,
    send_negotiation_message,
    get_resume_info,
    get_available_employer_states_and_collections_negotiations,
    get_negotiations_messages,
    get_negotiations_history,
)


from shared_services.ai_service import (
    analyze_vacancy_with_ai, 
    format_sourcing_criterias_analysis_result_for_markdown,
    analyze_resume_with_ai
)

from shared_services.questionnaire_service import (
    ask_question_with_options, 
    handle_answer,
    send_message_to_user,
    clear_all_unprocessed_keyboards
)

from shared_services.task_queue_service import TaskQueue

from shared_services.constants import *

from shared_services.db_service import (
    is_boolean_field_true_in_db,
    update_record_in_db,
    create_new_record_in_db,
    is_value_in_db,
    get_column_value_in_db,
    get_column_value_by_field,
    update_column_value_by_field
)

from shared_services.data_service import (
    get_employer_id_from_json_value_from_db,
    get_expires_at_from_callback_endpoint_resp,
    get_access_token_from_callback_endpoint_resp,
    get_decision_status_from_selected_callback_code,
    create_tg_bot_link_for_applicant,
    create_oauth_link,
    get_tg_user_data_attribute_from_update_object,
    create_json_file_with_dictionary_content,
    format_oauth_link_text,
    create_resume_records_file,
    get_resume_records_file_path,
    get_path_to_video_from_applicant_from_resume_records,
    update_user_records_with_top_level_key, 
    #get_vacancy_directory,
    #create_record_for_new_resume_id_in_resume_records,
    get_resume_recommendation_text_from_resume_records,
    #update_resume_record_with_top_level_key,
    #get_resume_directory,
    #get_access_token_from_records,
    #get_target_vacancy_id_from_records,
    #get_target_vacancy_name_from_records,
    get_list_of_resume_ids_for_recommendation,
    get_negotiation_id_from_resume_record,
)

from database import (
    Managers,
    Vacancies,
    Negotiations,
)

HH_CLIENT_ID = os.getenv("HH_CLIENT_ID")
HH_CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
OAUTH_REDIRECT_URL = os.getenv("OAUTH_REDIRECT_URL")
USER_AGENT = os.getenv("USER_AGENT")

# Global task queue for AI analysis tasks
ai_task_queue = TaskQueue(maxsize=500)


########################################################################################
# -------------------------- ADMIN COMMANDS --------------------------------------------
########################################################################################

async def send_message_to_admin(application: Application, text: str, parse_mode: Optional[ParseMode] = None) -> None:
    #TAGS: [admin]

    # ----- GET ADMIN ID from environment variables -----
    
    admin_id = os.getenv("ADMIN_ID", "")
    if not admin_id:
        logger.error("send_message_to_admin:ADMIN_ID environment variable is not set. Cannot send admin notification.")
        return
    
    # ----- SEND NOTIFICATION to admin -----
    
    try:
        if application and application.bot:
            await application.bot.send_message(
                chat_id=int(admin_id),
                text=text,
                parse_mode=parse_mode
            )
            logger.debug(f"send_message_to_admin: Admin notification sent successfully to admin_id: {admin_id}")
        else:
            logger.warning("send_message_to_admin: Cannot send admin notification: application or bot instance not available")
    except Exception as e:
        logger.error(f"send_message_to_admin: Failed to send admin notification: {e}", exc_info=True)

########################################################################################
# ------------ AUTOMATIC FLOW ON START - can be triggered by from MAIN MENU ------------
########################################################################################
# - setup user
# - ask privacy policy confirmation
# - handle answer privacy policy confirmation
# - HH authorization
# - pull user data from HH
# - select vacancy
# - handle answer select vacancy
# - ask to record video
# - handle answer video record request
# - send instructions to shoot video
# - ask confirm sending video
# - handle answer confirm sending video
# - read vacancy description
# - define sourcing criterias
# - get sourcing criterias from AI and save to file


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler. 
    Called from: 'start' button in main menu.
    Triggers: 1) setup new user 2) ask privacy policy confirmation
    """


    # ----- SETUP NEW USER and send welcome message -----

    # if existing user, setup_new_user_command will be skipped
    await setup_new_user_command(update=update, context=context)

    # ----- ASK PRIVACY POLICY CONFIRMATION -----

    # if already confirmed, second confirmation will be skipped
    await ask_privacy_policy_confirmation_command(update=update, context=context)

    # IMPORTANT: ALL OTHER COMMANDS will be triggered from functions if PRIVACY POLICY is confirmed


async def setup_new_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Setup new user in system.
    Called from: 'start_command'.
    Triggers: nothing."""

    try:
        # ------ COLLECT NEW USER ID and CREATE record and user directory if needed ------

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"setup_new_user_command started. user_id: {bot_user_id}")

        if bot_user_id is None:
            raise ValueError(f"setup_new_user_command: bot_user_id is None")

        # ----- CHECK IF USER is in records and CREATE record and user directory if needed -----
        
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            create_new_record_in_db(db_model=Managers, record_id=bot_user_id)

        # ------ ENRICH RECORDS with NEW USER DATA ------

        tg_user_attributes = ["username", "first_name", "last_name"]
        for item in tg_user_attributes:
            tg_user_attribute_value = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute=item)
            update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={item: tg_user_attribute_value})
            # If cannot update user records, ValueError is raised from method: update_user_records_with_top_level_key()
        logger.debug(f"setup_new_user_command: {bot_user_id} in user records is updated with telegram user attributes.")
        
        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"✅ New user {bot_user_id} has been successfully setup."
            )
        
    except Exception as e:
        logger.error(f"Failed to setup new user: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error setup_new_user_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def ask_privacy_policy_confirmation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask privacy policy confirmation command handler. 
    Called from: 'start_command'.
    Triggers: nothing."""

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"ask_privacy_policy_confirmation_command started. user_id: {bot_user_id}")

        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            await send_message_to_user(update, context, text=FAIL_TO_FIND_USER_IN_RECORDS_TEXT)
            raise ValueError(f"ask_privacy_policy_confirmation_command: user {bot_user_id} not found in database")

        # ----- CHECK IF PRIVACY POLICY is already confirmed and STOP if it is -----

        if is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
            await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)
            return

        # Build options (which will be tuples of (button_text, callback_data))
        answer_options = [
            ("Ознакомлен, даю согласие на обработку.", "privacy_policy_confirmation:yes"),
            ("Не даю согласие на обрабоку.", "privacy_policy_confirmation:no"),
        ]
        # Store button_text and callback_data options in context to use it later for button _text identification as this is not stored in "update.callback_query" object
        context.user_data["privacy_policy_confirmation_answer_options"] = answer_options
        await ask_question_with_options(update, context, question_text=PRIVACY_POLICY_CONFIRMATION_TEXT, answer_options=answer_options)
        logger.info(f"ask_privacy_policy_confirmation_command: privacy policy confirmation question with options asked")

    except Exception as e:
        logger.error(f"Failed to ask privacy policy confirmation: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error ask_privacy_policy_confirmation_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def handle_answer_policy_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click, updates confirmation status in user records.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to process personal data, triggers 'hh_authorization_command'.
    - If user does not agree to process personal data, informs user how to give consent."""

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_policy_confirmation started. user_id: {bot_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)

    # ----- UNDERSTAND TEXT on clicked buttton from option taken from context -----

    # Get options from context or return empty list [] if not found
    privacy_policy_confirmation_answer_options = context.user_data.get("privacy_policy_confirmation_answer_options", [])
    # find selected button text from callback_data
    for button_text, callback_code in privacy_policy_confirmation_answer_options:
        if selected_callback_code == callback_code:
            selected_button_text = button_text
            # Clear privacy policy confirmation answer options from "context" object, because now use "selected_button_text" variable instead
            context.user_data.pop("privacy_policy_confirmation_answer_options", None)
            break

    # ----- INFORM USER about selected option -----

    # If "options" is NOT an empty list execute the following code
    if privacy_policy_confirmation_answer_options:
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No options available, inform user and return
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UPDATE USER RECORDS with selected vacancy data -----

    # Now you can use callback_data or selected_option for your logic
    if update.callback_query and update.callback_query.message:
        if selected_callback_code is None:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
            return
        privacy_policy_confirmation_user_decision = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
        
        # Update user records with selected vacancy data
  
        privacy_policy_confirmation_user_value = True if privacy_policy_confirmation_user_decision == "yes" else False
        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"privacy_policy_confirmed": privacy_policy_confirmation_user_value})
        
        current_time = datetime.now(timezone.utc).isoformat()
        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"privacy_policy_confirmation_time": current_time})
        
        logger.debug(f"Privacy policy confirmation user decision: {privacy_policy_confirmation_user_decision} at {current_time}")

        # ----- IF USER CHOSE "YES" download video to local storage -----

        if privacy_policy_confirmation_user_decision == "yes":
            await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)
            
        # ----- SEND AUTHENTICATION REQUEST and wait for user to authorize -----
    
            # if already authorized, second authorization will be skipped
            await hh_authorization_command(update=update, context=context)
        
        # ----- IF USER CHOSE "NO" inform user about need to give consent to process personal data -----
        
        else:
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)


async def hh_authorization_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """ HH authorization command. 
    Called from: 'handle_answer_policy_confirmation'.
    Triggers: 'pull_user_data_from_hh_command'.
    - Sends intro text and link to authorize via HH.ru.
    - Waits for user to authorize
        - If user authorized, sends success text.
        - If user didn't authorize, sends error text.
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"hh_authorization_command started. user_id: {bot_user_id}")
        
        # ----- CHECK IF NO Privacy policy consent or AUTHORIZAED already and STOP if it is -----
        if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
            return

        if is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token_recieved"):
            await send_message_to_user(update, context, text=SUCCESS_TO_HH_AUTHORIZATION_TEXT)
            return

        # ------ HH.ru AUTHENTICATION PROCESS ------
        
        # Check if the authentication endpoint is healthy
        if not callback_endpoint_healthcheck():
            raise ValueError(f"hh_authorization_command: Server authorization is not available. User {bot_user_id} cannot authorize.")

        # ------ SEND USER AUTH link in HTML format ------

        # Build OAuth link and send it to the user
        auth_link = create_oauth_link(state=bot_user_id)
        # If cannot create oauth link, ValueError is raised from method: create_oauth_link()

        # Format oauth link text to keep https links in html format
        formatted_oauth_link_text = format_oauth_link_text(oauth_link=auth_link)
        authorization_request_text = AUTH_REQ_TEXT + formatted_oauth_link_text
        await send_message_to_user(update, context, text=authorization_request_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await asyncio.sleep(1) 

        # ------ WAIT FOR USER AUTHORIZATION ------

        await send_message_to_user(update, context, text="⏳ Ожидаю авторизацию...")
        # Wait for user to authorize - retry 5 times over ~60 seconds
        max_attempts = 30
        retry_delay = 6  # seconds between retries
        endpoint_response = None
        # Retry to get access token by state 5 times over ~60 seconds
        for attempt in range(1, max_attempts + 1):
            await asyncio.sleep(retry_delay)
            endpoint_response = get_token_by_state(state=bot_user_id, bot_shared_secret=BOT_SHARED_SECRET)
            
            if endpoint_response is not None:
                if endpoint_response is not CALLBACK_ENDPOINT_RESPONSE_WHEN_RECORDS_NOT_READY:
                    logger.debug(f"Endpoint response: {endpoint_response}")
                    access_token = get_access_token_from_callback_endpoint_resp(endpoint_response=endpoint_response)
                    expires_at = get_expires_at_from_callback_endpoint_resp(endpoint_response=endpoint_response)
                    if access_token is not None and expires_at is not None:
                        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"access_token_recieved": True})
                        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"access_token": access_token})
                        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"access_token_expires_at": expires_at})
                        # If cannot update user records, ValueError is raised from method: update_user_records_with_top_level_key()

                    logger.info(f"Authorization successful on attempt {attempt}. Access token '{access_token}' and expires_at '{expires_at}' updated in records.")
                    await send_message_to_user(update, context, text=AUTH_SUCCESS_TEXT)

        # ----- PULL USER DATA from HH and enrich records with it -----

                    await pull_user_data_from_hh_command(update=update, context=context)
                    
                    #Stop the loop after successful authorization
                    break
            else:
                logger.debug(f"Attempt {attempt}/{max_attempts}: User hasn't authorized yet. Retrying...")
        # If still None after all attempts, user didn't authorize
        if endpoint_response is None:
            await send_message_to_user(update, context, text=AUTH_FAILED_TEXT)
            return
    
    except Exception as e:
        logger.error(f"hh_authorization_command: Failed to execute: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error hh_authorization_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def pull_user_data_from_hh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Pull user data from HH and enrich records with it. 
    Called from: 'hh_authorization_command'.
    Triggers: 'select_vacancy_command'.
    Sends notification to admin if fails"""
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"pull_user_data_from_hh_command started. user_id: {bot_user_id}")
        access_token = get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token")

        # ----- CHECK IF USER DATA is already in records and STOP if it is -----

        # Check if user is already authorized, if not, pull user data from HH
        if get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="hh_data") is not None:
            logger.debug(f"'bot_user_id': {bot_user_id} already has HH data in user record.")
            return 
            
        # ----- PULL USER DATA from HH and enrich records with it -----

        # Get user info from HH.ru API
        hh_user_info = get_user_info_from_hh(access_token=access_token)
        # Clean user info received from HH.ru API
        cleaned_hh_user_info = clean_user_info_received_from_hh(user_info=hh_user_info)
        # Update user info from HH.ru API in records
        # Exception raised if fails
        update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={"hh_data": cleaned_hh_user_info})

        # ----- SELECT VACANCY -----

        await select_vacancy_command(update=update, context=context)
    
    except Exception as e:
        logger.error(f"Failed to pull user data from HH: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error pull_user_data_from_hh_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def ask_to_record_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask to record video command. 
    Called from: 'handle_vacancy_selection'.
    Triggers: nothing."""

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"ask_to_record_video_command triggered by user_id: {bot_user_id}")

    # ----- CHECK MUST CONDITIONS are met and STOP if not -----

    if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
        logger.debug(f"'bot_user_id': {bot_user_id} doesn't have privacy policy confirmed.")
        await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
        return

    if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_selected"):
        logger.debug(f"'bot_user_id': {bot_user_id} doesn't have target vacancy selected.")
        await send_message_to_user(update, context, text=MISSING_VACANCY_SELECTION_TEXT)
        return

    # Get status of video received from Vacancies table by manager_id
    is_vacancy_video_received = get_column_value_by_field(
        db_model=Vacancies,
        search_field_name="manager_id",
        search_value=bot_user_id,
        target_field_name="video_received"
    )

    if is_vacancy_video_received:
        logger.debug(f"'bot_user_id': {bot_user_id} already has welcome video recorded.")
        await send_message_to_user(update, context, text=SUCCESS_TO_RECORD_VIDEO_TEXT)
        return


    # ----- ASK USER IF WANTS TO RECORD or drop welcome video for the selected vacancy -----

    # Build options (which will be tuples of (button_text, callback_data))
    answer_options = [
        ("Хочу записать или загрузить видео", "record_video_request:yes"), 
        ("Продолжить без видео", "record_video_request:no")
        ]
    # Store button_text and callback_data options in context to use it later for button _text identification as this is not stored in "update.callback_query" object
    context.user_data["video_record_request_options"] = answer_options
    await ask_question_with_options(update, context, question_text=WELCOME_VIDEO_RECORD_REQUEST_TEXT, answer_options=answer_options)
    logger.debug(f"Record video request question with options asked")


async def handle_answer_video_record_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click. 
    Called from: nowhere.
    Triggers commands:
    - If user agrees to record, sends instructions to shootv ideo command'.
    - If user does not agree to record, triggers 'read_vacancy_description_command'.

    This is called AUTOMATICALLY by Telegram when a button is clicked (via CallbackQueryHandler).

    Note: Bot knows which user clicked because:
    - update.effective_user.id contains the user ID (works for both messages and callbacks)
    - context.user_data is automatically isolated per user by python-telegram-bot framework
    """

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_video_record_request triggered by user_id: {bot_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)
    
    logger.debug(f"Callback code found: {selected_callback_code}")

    # ----- UNDERSTAND TEXT on clicked buttton from option taken from context -----

    if not selected_callback_code:
        if update.callback_query and update.callback_query.message:
            logger.debug(f"No callback code found in update.callback_query.message")
            await send_message_to_user(update, context, text="Не удалось определить ваш выбор. Попробуйте еще раз командой /ask_to_record_video.")
        return

    logger.debug(f"Callback code found: {selected_callback_code}")

    # Get options from context or use fallback defaults if not found
    video_record_request_options = context.user_data.get("video_record_request_options", [])
    logger.debug(f"Video record request options: {video_record_request_options}")
    if not video_record_request_options:
        video_record_request_options = [
            ("Хочу записать или загрузить видео", "record_video_request:yes"),
            ("Продолжить без видео", "record_video_request:no"),
        ]
    logger.debug(f"Video record request options set: {video_record_request_options}")
    selected_button_text = None
    # find selected button text from callback_data
    for button_text, callback_code in video_record_request_options:
        if selected_callback_code == callback_code:
            selected_button_text = button_text
            # Clear video record request options from "context" object, because now use "selected_button_text" variable instead
            context.user_data.pop("video_record_request_options", None)
            break
    logger.debug(f"Selected button text: {selected_button_text}")
    logger.debug(f"Context user data: {context.user_data}")

    # ----- INFORM USER about selected option -----

    if selected_button_text:
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No option identified, inform user and return
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UPDATE USER RECORDS with selected vacancy data and infrom user -----

    # Now you can use callback_data or selected_option for your logic
    if update.callback_query and update.callback_query.message:
        logger.debug(f"Selected callback code: {selected_callback_code}")
        if selected_callback_code is None:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
            return
        video_record_request_user_decision = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
        logger.debug(f"Video record request user decision: {video_record_request_user_decision}")
        if video_record_request_user_decision == "yes":
            new_value = True
        else:
            new_value = False
        # Update user records with selected vacancy data
        update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="video_record_agreed", new_value=new_value)
        logger.debug(f"Vacancies Database record updated")
    
    # ----- PROGRESS THROUGH THE VIDEO FLOW BASED ON THE USER'S RESPONSE -----

    # ----- IF USER CHOSE "YES" send instructions to shoot video -----

    if video_record_request_user_decision == "yes":
        logger.debug(f"Video record request user decision is yes")
        await send_message_to_user(update, context, text=INSTRUCTIONS_TO_SHOOT_VIDEO_TEXT)
        await asyncio.sleep(1)
        await send_message_to_user(update, context, text=INFO_DROP_VIDEO_HERE_TEXT)
        
        # ----- NOW HANDLER LISTENING FOR VIDEO from user -----

        # this line just for info that handler will work from "create_manager_application" method in file "manager_bot.py"
        # once handler will be triggered, it will trigget "handle_video" method from file "services.video_service.py"

    # ----- IF USER CHOSE "NO" inform user about need to continue without video -----

    else:
        await send_message_to_user(update, context, text=CONTINUE_WITHIOUT_WELCOME_VIDEO_TEXT)

        # ----- READ VACANCY DESCRIPTION -----

        await read_vacancy_description_command(update=update, context=context)


async def ask_confirm_sending_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask confirm sending video command handler. 
    Called from: 'process_incoming_video' from file "services.video_service.py".
    Triggers: nothing. """

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"ask_confirm_sending_video_command started. user_id: {bot_user_id}")

    # Build options (which will be tuples of (button_text, callback_data))
    answer_options = [
        ("Да. Отправить это.", "sending_video_confirmation:yes"),
        ("Нет. Попробую еще раз.", "sending_video_confirmation:no"),
    ]
    # Store button_text and callback_data options in context to use it later for button _text identification as this is not stored in "update.callback_query" object
    context.user_data["sending_video_confirmation_answer_options"] = answer_options
    await ask_question_with_options(update, context, question_text=VIDEO_SENDING_CONFIRMATION_TEXT, answer_options=answer_options)


async def handle_answer_confrim_sending_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to send video, triggers 'download_incoming_video_locally' method.
    - If user does not agree to send video, inform that waiting for another video to be sent by user.
    """
    
    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_confrim_sending_video triggered by user_id: {bot_user_id}")

    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)

    # ----- UNDERSTAND TEXT on clicked buttton from option taken from context -----

    # Get options from context or return empty list [] if not found
    sending_video_confirmation_answer_options = context.user_data.get("sending_video_confirmation_answer_options", [])
    # find selected button text from callback_data
    for button_text, callback_code in sending_video_confirmation_answer_options:
        if selected_callback_code == callback_code:
            selected_button_text = button_text
            # Clear sending video confirmation answer options from "context" object, because now use "selected_button_text" variable instead
            context.user_data.pop("sending_video_confirmation_answer_options", None)
            break

    # ----- INFORM USER about selected option -----

    # If "options" is NOT an empty list execute the following code
    if sending_video_confirmation_answer_options:
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No options available, inform user and return
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UPDATE USER RECORDS with selected vacancy data -----

    # Now you can use callback_data or selected_option for your logic
    if update.callback_query and update.callback_query.message:
        if selected_callback_code is None:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
            return
        sending_video_confirmation_user_decision = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
        # Update user records with selected vacancy data
        if sending_video_confirmation_user_decision == "yes":
            new_value = True
        else:
            new_value = False
        update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="video_sending_confirmed", new_value=new_value)
        logger.debug(f"Vacancies Database record updated")

    # ----- IF USER CHOSE "YES" start video download  -----

    if sending_video_confirmation_user_decision == "yes":
        
        # ----- GET VIDEO DETAILS from message -----

        # Get file_id and video_kind from user_data
        file_id = context.user_data.get("pending_file_id")
        video_kind = context.user_data.get("pending_kind")

        # ----- DOWNLOAD VIDEO to local storage -----
        logger.debug(f"Downloading video to local storage...")
        await download_incoming_video_locally(
            update=update,
            context=context,
            tg_file_id=file_id,
            user_id=bot_user_id,
            file_type=video_kind
        )

        # ----- UPDATE USER RECORDS with video status and path -----
        # skipping as updated in "download_incoming_video_locally" method

        # ----- IF VIDEO NOT FOUND, ask for another video -----

        if not file_id:
            logger.warning("No file_id found in user_data")
            await send_message_to_user(update, context, text=MISSING_VIDEO_RECORD_TEXT)
            return

    else:

    # ----- IF USER CHOSE "NO" ask for another video -----

        await send_message_to_user(update, context, text=WAITING_FOR_ANOTHER_VIDEO_TEXT)


async def select_vacancy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Asks users to select a vacancy to work with. 
    Called from: 'pull_user_data_from_hh_command'.
    Triggers: nothing.
    Sends notification to admin if fails"""

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"select_vacancy_command started. user_id: {bot_user_id}")
        access_token = get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token")

        # ----- CHECK IF Privacy confirmed and VACANCY is selected and STOP if it is -----

        if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
            return

        if is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_selected"):
            await send_message_to_user(update, context, text=SUCCESS_TO_SELECT_VACANCY_TEXT)
            return

        # ----- PULL ALL OPEN VACANCIES from HH and enrich records with it -----

        employer_id = get_employer_id_from_json_value_from_db(db_model=Managers, record_id=bot_user_id)
        if not employer_id:
            await send_message_to_user(update, context, text=FAILED_TO_GET_OPEN_VACANCIES_TEXT)
            # Raise exception to be caught by outer try-except block (which will notify admin)
            raise ValueError(f"No employer id found for user {bot_user_id}")

        # Get open vacancies from HH.ru API
        all_employer_vacancies = get_employer_vacancies_from_hh(access_token=access_token, employer_id=employer_id)
        if all_employer_vacancies is None:
            await send_message_to_user(update, context, text=FAILED_TO_GET_OPEN_VACANCIES_TEXT)
            # Raise exception to be caught by outer try-except block (which will notify admin)
            raise ValueError(f"No open vacancies found for user {bot_user_id}")
        # Filter only open vacancies (id, name tuples)
        vacancy_status = VACANCY_STATUS_TO_FILTER
        # get nested dict with open vacancies {id: {id, name, status=open}}
        open_employer_vacancies_dict = filter_open_employer_vacancies(vacancies_json=all_employer_vacancies, status_to_filter=vacancy_status)

        # If dict is empty => no open vacancies, inform user and raise exception
        if not open_employer_vacancies_dict:
            await send_message_to_user(update, context, text=FAILED_TO_GET_OPEN_VACANCIES_TEXT)
            # Raise exception to be caught by outer try-except block (which will notify admin)
            raise ValueError(f"No open vacancies found for user {bot_user_id}")

        # ----- ASK USER what vacancy to work on -----

        # Initialize options for user to select a vacancy (from JSON/dict)
        # Build options (which will be tuples of (vacancy_name, vacancy_id)) from dict: key is vacancy_id, value is {id, name, ...}
        answer_options = []


        for vacancy_id, vacancy_data in open_employer_vacancies_dict.items():
            if not vacancy_data:
                continue
            vacancy_name = vacancy_data.get("name")
            if vacancy_name:
                answer_options.append((vacancy_name, vacancy_id))
        # Store options in context so handler can access them
        context.user_data["vacancy_options"] = answer_options
        await ask_question_with_options(update, context, question_text="Выберите c какой из вакансий вы хотите работать.", answer_options=answer_options)
    
    except Exception as e:
        logger.error(f"Failed to select vacancy: {e}", exc_info=True)        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error select_vacancy_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def handle_answer_select_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Handle button click.
    Called from: nowhere.
    Triggers 'ask_to_record_video_command'.

    Saves selected vacancy data to records, vacancy description and available employer_states_and_collections to vacancy directory.
    This is called AUTOMATICALLY by Telegram when a button is clicked (via CallbackQueryHandler).
    The options list should be stored in context.user_data["vacancy_options"] when asking the question.
    
    Note: Bot knows which user clicked because:
    - update.effective_user.id contains the user ID (works for both messages and callbacks)
    - context.user_data is automatically isolated per user by python-telegram-bot framework
    Sends notification to admin if fails
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----
        
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"handle_answer_select_vacancy started. user_id: {bot_user_id}")
        
        # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

        # Get the callback_data from the button click
        callback_data = await handle_answer(update, context)

        # ------- CREATE VACANCY RECORD for selected vacancy  -------

        target_vacancy_id = str(callback_data)
        logger.debug(f"Target vacancy id: {target_vacancy_id}")
        if not target_vacancy_id:
            raise ValueError(f"No target_vacancy_id {target_vacancy_id} found in callback_data")

        # ----- PULL OPTIONS from context (stored when question asked) -----

        # Get options from context (stored when question was asked)
        answer_options = context.user_data.get("vacancy_options", [])
        if not answer_options:
            raise ValueError(f"No answer_options available in context")
        
        # ----- FIND SELECTED OPTION from options list and store it in variable -----

        # Find the selected option
        selected_option = None
        for button_text, callback_code in answer_options:
            # Compare as strings to avoid type mismatches (e.g., int vs str)
            if str(callback_data) == str(callback_code):
                selected_option = (button_text, callback_code)
                # Clear vacancy options from "context" object, because now use "selected_option" variable instead
                context.user_data.pop("vacancy_options", None)
                break

        if not selected_option:
            raise ValueError(f"Selected vacancy option not found for callback_data {callback_data}")

        vacancy_name_value = selected_option[0]

        # Create Vacancies record with required NOT NULL fields set immediately
        update_record_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            updates={"vacancy_selected": True},
        )
        create_new_record_in_db(
            db_model=Vacancies,
            record_id=target_vacancy_id,
            initial_values={
                "manager_id": bot_user_id,
                "name": vacancy_name_value,
            },
        )

        # ----- UPDATE USER RECORDS with selected vacancy data and inform user -----

        # Now you can use callback_data or selected_option for your logic
        if update.callback_query and update.callback_query.message:
            # Inform user that selected vacancy is being processed
            vacancy_name, vacancy_id = selected_option
            await send_message_to_user(
                update,
                context,
                text=f"Вы выбрали вакансию:\n'{vacancy_name}'",
            )
            await asyncio.sleep(2)

        # ----- ASK USER to record welcome video -----

        await ask_to_record_video_command(update=update, context=context)
    
    except Exception as e:
        logger.error(f"Failed to handle answer select vacancy: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error handling answer select vacancy: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def read_vacancy_description_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Read vacancy description and save it. 
    Called from: 'download_incoming_video_locally' from file "services.video_service.py".
    Triggers: nothing.
    Sends notification to admin if fails"""
    
    # ----- IDENTIFY USER and pull required data from records -----
    
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"read_vacancy_description_command started. user_id: {bot_user_id}")

    await send_message_to_user(update, context, text="!!! Поздравляю !!! ты дошел до этапа получения описания вакансии.")

    access_token = get_column_value_in_db(
        db_model=Managers,
        record_id=bot_user_id,
        field_name="access_token",
    )
    # Find vacancy id for this manager (manager_id == bot_user_id)
    target_vacancy_id = get_column_value_by_field(
        db_model=Vacancies,
        search_field_name="manager_id",
        search_value=bot_user_id,
        target_field_name="id",
    )
    target_vacancy_name = get_column_value_in_db(
        db_model=Vacancies,
        record_id=target_vacancy_id,
        field_name="name",
    )
    
    # ----- VALIDATE description received -----

    if is_boolean_field_true_in_db(db_model=Vacancies, record_id=target_vacancy_id, field_name="description_recieved"):
        await send_message_to_user(update, context, text=SUCCESS_TO_SELECT_VACANCY_TEXT)
        return

    try:

        # ----- PULL VACANCY DESCRIPTION from HH and save it to file -----
        """
        vacancy_description = get_vacancy_description_from_hh(access_token=access_token, vacancy_id=target_vacancy_id)
        """

        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!

        with open("/Users/gridavyv/HRVibe/hrvibe_2.1/test_data/fake_vacancy_description.json", "r", encoding="utf-8") as f:
            vacancy_description = json.load(f)
        logger.debug(f"Vacancy description fetched from fake file: {vacancy_description}")

        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!

        if vacancy_description is None:
            logger.error(f"Failed to get vacancy description from HH: {target_vacancy_name}")
            return
        
        await send_message_to_user(update, context, text=INFO_ABOUT_ANALYZING_VACANCY_TEXT)
        
        # ----- SAVE VACANCY DESCRIPTION to file and update records -----

        """
        create_json_file_with_dictionary_content(file_path=vacancy_description_file_path, content_to_write=vacancy_description)
        update_user_records_with_top_level_key(record_id=bot_user_id, key="vacancy_description_recieved", value="yes")
        """
        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=target_vacancy_id, target_field_name="description_recieved", new_value=True)
        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=target_vacancy_id, target_field_name="description_json", new_value=vacancy_description)

    
    except Exception as e:
        logger.error(f"Failed to read vacancy description: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error read_vacancy_description_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )
    

########################################################################################
# ------------ DEFINING SOURCING CRITERIAS on ADMIN request ------------
########################################################################################


async def define_sourcing_criterias_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """User-facing command to define sourcing criterias.
    Called from: 'handle_chat_menu_action'.
    Triggers: 'define_sourcing_criterias_triggered_by_admin_command'.
    """
    try:
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"define_sourcing_criterias_command: started. user_id: {bot_user_id}")
        target_vacancy_id = get_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="id")
        await define_sourcing_criterias_triggered_by_admin_command(vacancy_id=target_vacancy_id)
    except Exception as e:
        logger.error(f"define_sourcing_criterias_command: Failed to execute: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error define_sourcing_criterias_command: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def define_sourcing_criterias_triggered_by_admin_command(vacancy_id: str) -> None:
    # TAGS: [vacancy_related]
    """Prepare everything for vacancy description analysis and 
    create TaksQueue job to get sourcing criteria from AI and save it to file.
    Called from: 'read_vacancy_description_command' or 'define_sourcing_criterias_command'.
    Triggers: nothing.
    """

    try:

        logger.info(f"define_sourcing_criterias_triggered_by_admin_command: started. vacancy_id: {vacancy_id}")

        # ----- VALIDATE VACANCY IS SELECTED and has description and sourcing criterias exist -----

        if not is_value_in_db(db_model=Vacancies, field_name="id", value=vacancy_id):
            raise ValueError(f"Vacancy {vacancy_id} not found in database.")

        if not is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="description_recieved"):
            raise ValueError(f"Vacancy description is not received for vacancy {vacancy_id}.")

        # ----- CHECK IF SOURCING CRITERIA is already derived and STOP if it is -----

        if is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="sourcing_criterias_recieved"):
            raise ValueError(f"Sourcing criterias is received already for vacancy {vacancy_id}.")

        # ----- DO AI ANALYSIS of the vacancy description  -----

        
        # Get files paths for AI analysis
        vacancy_description=get_column_value_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="description_json")
        prompt_file_path = Path(PROMPT_DIR) / "for_vacancy.txt"

        # Load inputs for AI analysis
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        # Add AI analysis task to queue
        await ai_task_queue.put(
            get_sourcing_criterias_from_ai_and_save_to_db,
            vacancy_id,
            vacancy_description,
            prompt_text,
            task_id=f"vacancy_analysis_{vacancy_id}"
        )  

    except Exception as e:
        logger.error(f"Error in define_sourcing_criterias_command: {e}", exc_info=True)
        raise 


async def get_sourcing_criterias_from_ai_and_save_to_db(
    vacancy_id: str,
    vacancy_description: dict,
    prompt_text: str,
    ) -> None:
    # TAGS: [vacancy_related]
    """
    Wrapper function to process vacancy analysis result.
    This function is executed through TaskQueue.
    """

    # ----- IDENTIFY USER and pull required data from records -----

    logger.info(f"get_sourcing_criterias_from_ai_and_save_to_file: started. vacancy_id: {vacancy_id}")

    try:
        '''
        # ----- CALL AI ANALYZER -----

        vacancy_analysis_result = analyze_vacancy_with_ai(
            vacancy_data=vacancy_description,
            prompt_vacancy_analysis_text=prompt_text
        )
        '''

        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!

        with open("/Users/gridavyv/HRVibe/hrvibe_2.1/test_data/fake_sourcing_criterias.json", "r", encoding="utf-8") as f:
            vacancy_analysis_result = json.load(f)
        logger.debug(f"Sourcing criterias fetched from fake file: {vacancy_analysis_result}")

        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!
        # !!! FOR TESTING ONLY !!!  

        # ----- SAVE SOURCING CRITERIAS to DB -----

        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="sourcing_criterias_recieved", new_value=True)
        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="sourcing_criterias_json", new_value=vacancy_analysis_result)
        
    except Exception as e:
        logger.error(f"Failed to get sourcing criterias and save to DB for vacancy {vacancy_id}: {e}", exc_info=True)        # Send notification to admin about the error
        raise


async def send_to_user_sourcing_criterias_triggered_by_admin_command(vacancy_id: str, application: Application) -> None:

    """
    Sends sourcing criterias analysis result to user and then asks for confirmation.
    This function is triggered by admin command and therefore works with `Application`
    instance instead of `update` / `context`.
    """

    try:

        bot_user_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
        if not bot_user_id:
            raise ValueError(f"Manager ID not found for vacancy {vacancy_id}")

        # Format and send result to user
        formatted_result = format_sourcing_criterias_analysis_result_for_markdown(vacancy_id=vacancy_id)
        
        if application and application.bot:
            await application.bot.send_message(
                chat_id=int(bot_user_id),
                text=f"{INFO_ABOUT_SOURCING_CRITERIAS_TEXT}\n\n{formatted_result}",
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(1)

            # Ask for sourcing criterias confirmation using Application-based helper
            await ask_sourcing_criterias_confirmation_via_application(
                bot_user_id=str(bot_user_id),
                application=application,
            )

        else:
            raise ValueError(f"Missing required application or bot instance for sending message to user {bot_user_id}")
    except Exception as e:
        logger.error(f"Failed to send sourcing criterias result to user: {e}", exc_info=True)
        raise


async def ask_sourcing_criterias_confirmation_via_application(bot_user_id: str, application: Application) -> None:
    """
    Variant of `ask_sourcing_criterias_confirmation_command` that works with `Application`
    and `bot_user_id` only (no `update` / `context`). Used when flow is triggered by admin
    command and not directly by the user.
    """

    try:
        logger.info(f"ask_sourcing_criterias_confirmation_via_application started. user_id: {bot_user_id}")

        # ----- CHECK IF USER EXISTS IN DATABASE -----
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            if application and application.bot:
                await application.bot.send_message(
                    chat_id=int(bot_user_id),
                    text=FAIL_TO_FIND_USER_IN_RECORDS_TEXT,
                )
            raise ValueError(
                f"ask_sourcing_criterias_confirmation_via_application: user {bot_user_id} not found in database"
            )

        # Build options (which will be tuples of (button_text, callback_data))
        answer_options = [
            ("Согласен с критериями отбора.", "sourcing_criterias_confirmation:yes"),
            ("Не согласен, хочу изменить критерии отбора.", "sourcing_criterias_confirmation:no"),
        ]

        # Store options in per-user data via Application so that
        # `handle_answer_sourcing_criterias_confirmation` can resolve button text later.
        user_id_int = int(bot_user_id)
        
        # Try to store in application.user_data first (if it's writable)
        stored_in_application = False
        try:
            if hasattr(application, "user_data") and application.user_data is not None:
                # Check if user_data is writable (not a mappingproxy)
                # Try to access it and see if we can modify it
                if user_id_int in application.user_data:
                    # Key exists, we can modify the inner dict
                    application.user_data[user_id_int]["sourcing_criterias_confirmation_answer_options"] = answer_options
                    stored_in_application = True
                else:
                    # Key doesn't exist, try to create it (will fail if user_data is read-only)
                    try:
                        application.user_data[user_id_int] = {"sourcing_criterias_confirmation_answer_options": answer_options}
                        stored_in_application = True
                    except (TypeError, AttributeError):
                        # user_data is read-only (mappingproxy), can't create new keys
                        pass
        except (TypeError, AttributeError) as e:
            logger.debug(f"application.user_data is not writable: {e}")
        
        # Fallback to module-level storage if application.user_data is read-only
        if not stored_in_application:
            _sourcing_criterias_confirmation_options_storage[user_id_int] = answer_options
            logger.debug(f"Stored sourcing_criterias_confirmation_answer_options in module-level storage for user {bot_user_id}")

        # Build inline keyboard and send question
        keyboard = [
            [InlineKeyboardButton(text=button_text, callback_data=callback_code)]
            for button_text, callback_code in answer_options
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if application and application.bot:
            await application.bot.send_message(
                chat_id=int(bot_user_id),
                text=SOURCING_CRITERIAS_CONFIRMATION_TEXT,
                reply_markup=reply_markup,
            )
            logger.info(
                "ask_sourcing_criterias_confirmation_via_application: sourcing criterias "
                "confirmation question with options asked"
            )

    except Exception as e:
        logger.error(
            f"Failed to ask sourcing criterias confirmation via Application: {e}",
            exc_info=True,
        )
        # Notify admin about the error if possible
        try:
            if application:
                await send_message_to_admin(
                    application=application,
                    text=(
                        f"⚠️ Error ask_sourcing_criterias_confirmation_via_application: {e}\n"
                        f"User ID: {bot_user_id if bot_user_id else 'unknown'}"
                    ),
                )
        except Exception:
            logger.error(
                "Failed to send admin notification from ask_sourcing_criterias_confirmation_via_application",
                exc_info=True,
            )


async def handle_answer_sourcing_criterias_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click, updates confirmation status in user records.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to sourcing criterias, triggers 'start_sourcing_command'.
    - If user does not agree to sourcing criterias, asks user for feedback"""

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_sourcing_criterias_confirmation: started. user_id: {bot_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)
    logger.debug(f"handle_answer_sourcing_criterias_confirmation: Selected callback code: {selected_callback_code}")

    # Now you can use callback_data or selected_option for your logic
    if selected_callback_code is None:
        logger.warning(f"handle_answer_sourcing_criterias_confirmation: selected_callback_code is None")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UNDERSTAND TEXT on clicked buttton from options stored in application.user_data or module-level storage -----

    # For admin-triggered flow we store answer options in application.user_data (if writable) or module-level storage (fallback)
    sourcing_criterias_confirmation_answer_options = []
    user_id_int = int(bot_user_id)
    
    # Try to get from application.user_data first
    if context.application:
        try:
            if hasattr(context.application, "user_data") and user_id_int in context.application.user_data:
                sourcing_criterias_confirmation_answer_options = context.application.user_data[user_id_int].get(
                    "sourcing_criterias_confirmation_answer_options", []
                )
                if sourcing_criterias_confirmation_answer_options:
                    logger.debug(
                        f"handle_answer_sourcing_criterias_confirmation: Retrieved sourcing_criterias_confirmation_answer_options from application.user_data for user {bot_user_id}"
                    )
        except (ValueError, KeyError, AttributeError) as e:
            logger.debug(f"handle_answer_sourcing_criterias_confirmation: Failed to retrieve options from application.user_data: {e}")
    
    # Fallback to module-level storage if not found in application.user_data
    if not sourcing_criterias_confirmation_answer_options and user_id_int in _sourcing_criterias_confirmation_options_storage:
        sourcing_criterias_confirmation_answer_options = _sourcing_criterias_confirmation_options_storage[user_id_int]
        logger.debug(
            f"handle_answer_sourcing_criterias_confirmation: Retrieved sourcing_criterias_confirmation_answer_options from module-level storage for user {bot_user_id}"
        )
    
    # find selected button text from callback_data
    selected_button_text = None
    for button_text, callback_code in sourcing_criterias_confirmation_answer_options:
        if selected_callback_code == callback_code:
            selected_button_text = button_text
            # Clear sourcing criterias confirmation answer options from application.user_data
            if context.application and hasattr(context.application, "user_data"):
                try:
                    if user_id_int in context.application.user_data:
                        context.application.user_data[user_id_int].pop("sourcing_criterias_confirmation_answer_options", None)
                except (ValueError, KeyError, AttributeError):
                    pass
            # Also clear from module-level storage if it was used
            _sourcing_criterias_confirmation_options_storage.pop(user_id_int, None)
            break

    # ----- INFORM USER about selected option -----

    # If "options" is NOT an empty list and we found a matching button text, execute the following code
    if sourcing_criterias_confirmation_answer_options and selected_button_text:
        logger.debug(f"handle_answer_sourcing_criterias_confirmation: sourcing_criterias_confirmation_answer_options exists and selected_button_text: {selected_button_text}")
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No options available or button text not found, inform user and return
        logger.warning(
            f"handle_answer_sourcing_criterias_confirmation: "
            f"sourcing_criterias_confirmation_answer_options "
            f"options_empty={not sourcing_criterias_confirmation_answer_options}, "
            f"selected_button_text={selected_button_text}, "
            f"selected_callback_code={selected_callback_code}, "
            f"user_id={bot_user_id}"
        )
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UPDATE USER RECORDS with selected vacancy data -----

    
    logger.debug(f"handle_answer_sourcing_criterias_confirmation: selected_callback_code: {selected_callback_code}")
    sourcing_criterias_confirmation_user_decision = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
    
    # Update user records with selected vacancy data

    sourcing_criterias_confirmation_user_value = True if sourcing_criterias_confirmation_user_decision == "yes" else False
    update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="sourcing_criterias_confirmed", new_value=sourcing_criterias_confirmation_user_value)
 
    current_time = datetime.now(timezone.utc).isoformat()
    update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="sourcing_criterias_confirmation_time", new_value=current_time)
    
    logger.debug(f"Sourcing criterias confirmation user decision: {sourcing_criterias_confirmation_user_decision} at {current_time}")

    # ----- IF USER CHOSE "YES" download video to local storage -----              

    if sourcing_criterias_confirmation_user_decision == "yes":

        await send_message_to_user(update, context, text=f"{SUCCESS_TO_GET_SOURCING_CRITERIAS_CONFIRMATION_TEXT}\n{SUCCESS_TO_START_SOURCING_TEXT}")
        await send_message_to_admin(application=context.application, text=f"User {bot_user_id} has confirmed sourcing criterias. Start sourcing manually.")

    elif sourcing_criterias_confirmation_user_decision == "no":

        await send_message_to_user(update, context, text="Хорошо, расскажите, почему вы не согласны с критериями отбора кандидатов.\n\nПришлите аудио-запись прямо в этот чат, пожалуйста.\n\nЯ подправлю критерии и пришлю на согласование снова.")
        await send_message_to_admin(application=context.application, text=f"User {bot_user_id} has NOT confirmed sourcing criterias. Asked for feedback. Waiting.")

    else:   

        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


########################################################################################
# ------------ COMMANDS EXECUTED on ADMIN request ------------
########################################################################################

async def source_negotiations_triggered_by_admin_command(vacancy_id: str) -> None:
    # TAGS: [resume_related]
    """Sources negotiations collection."""
    
    try:
        logger.info(f"source_negotiations_triggered_by_admin_command started. vacancy_id: {vacancy_id}")

        # ----- IDENTIFY USER and pull required data from records -----
        
        manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
        access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")

        # ----- IMPORTANT: do not check if NEGOTIATIONS COLLECTION file exists, we update it every time -----

        # ----- PULL COLLECTIONS of negotiations and save it to file -----

        #Define what employer_state to use for pulling the collection
        employer_state = EMPLOYER_STATE_RESPONSE

        #Get collection of negotiations data for the target collection status "response"
        """
        negotiations_collection_data = get_negotiations_collection_with_status_response(access_token=access_token, vacancy_id=vacancy_id)
        """

        # !!! TESTING !!!
        # !!! TESTING !!!
        # !!! TESTING !!!

        fake_negotiations_file_path = "/Users/gridavyv/HRVibe/hrvibe_2.1/test_data/fake_negotiations_collections_response.json"
        with open(fake_negotiations_file_path, "r", encoding="utf-8") as f:
            negotiations_collection_data = json.load(f)

        # !!! TESTING !!!
        # !!! TESTING !!!
        # !!! TESTING !!!

        await parse_negotiations_collection_to_db(vacancy_id=vacancy_id, negotiations_json=negotiations_collection_data)

        logger.info(f"source_negotiations_triggered_by_admin_command: successfully completed for vacancy_id: {vacancy_id}")
    except Exception as e:
        logger.error(f"source_negotiations_triggered_by_admin_command: Failed to source negotiations for vacancy_id {vacancy_id}: {e}", exc_info=True)
        raise
        

async def parse_negotiations_collection_to_db(vacancy_id: str, negotiations_json: dict, ) -> None:
    # TAGS: [negotiations_related]
    """
    Parse negotiations collection JSON and update Negotiations table in database.
    Args:
        negotiations_json: Dictionary containing negotiations data with structure:
            {
                "items": [
                    {
                        "id": "negotiation_id",
                        "resume": {
                            "id": "resume_id"
                        }
                    },
                    ...
                ]
            }
        vacancy_id: The vacancy ID to associate negotiations with (required foreign key)
    
    Updates Negotiations table:
        - id: Set to [items][id] (negotiation ID)
        - resume_id: Set to [items][resume][id] (resume ID)
        - vacancy_id: Set to provided vacancy_id
    """

    logger.info(f"_parse_negotiations_collection_to_db: started. vacancy_id: {vacancy_id}")
    try:
        if not negotiations_json or "items" not in negotiations_json:
            raise ValueError("Invalid negotiations_json: missing 'items' key")
        
        items = negotiations_json.get("items", [])
        if not items:
            logger.warning("parse_negotiations_collection_to_db: No items found in negotiations_json")
            return
        
        logger.info(f"parse_negotiations_collection_to_db: Processing {len(items)} negotiations for vacancy {vacancy_id}")
        
        for item in items:
            # Extract negotiation ID and resume ID
            negotiation_id = item.get("id")
            resume = item.get("resume", {})
            resume_id = resume.get("id") if isinstance(resume, dict) else None
            
            if not negotiation_id:
                logger.warning(f"parse_negotiations_collection_to_db: Skipping item with missing 'id': {item}")
                continue
            
            if not resume_id:
                logger.warning(f"parse_negotiations_collection_to_db: Skipping negotiation {negotiation_id} with missing resume.id")
                continue
            
            # Ensure negotiation_id and resume_id are strings
            negotiation_id = str(negotiation_id)
            resume_id = str(resume_id)
            
            # Check if negotiation record already exists
            if not is_value_in_db(db_model=Negotiations, field_name="id", value=negotiation_id):
                # Create new record
                create_new_record_in_db(
                    db_model=Negotiations,
                    record_id=negotiation_id,
                    initial_values={
                        "resume_id": resume_id,
                        "vacancy_id": vacancy_id
                    }
                )
                logger.debug(f"parse_negotiations_collection_to_db: Created negotiation {negotiation_id} with resume_id {resume_id}")
            else:        
                logger.debug(f"parse_negotiations_collection_to_db: Skipping^ cause negotiation {negotiation_id} exists in database")
        
        logger.info(f"parse_negotiations_collection_to_db: Successfully processed {len(items)} negotiations for vacancy {vacancy_id}")
    
    except Exception as e:
        logger.error(f"parse_negotiations_collection_to_db: Failed to parse negotiations: {e}", exc_info=True)
        raise




async def source_resumes_triggered_by_admin_command(bot_user_id: str) -> None:
    # TAGS: [resume_related]
    """Sources resumes from negotiations."""
    
    try:
        logger.info(f"source_resumes_triggered_by_admin_command: started. User_id: {bot_user_id}")
        
        # ----- IDENTIFY USER and pull required data from records -----
        
        access_token = get_access_token_from_records(bot_user_id=bot_user_id)
        target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)
        target_employer_state = EMPLOYER_STATE_RESPONSE
        
        # ----- CHECK IF NEGOTIATIONS COLLECTION file exists, otherwise trigger source negotiations command -----
        
        """if not is_negotiations_collection_file_exists(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, target_employer_state=target_employer_state):"""
        if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="negotiations_collection_recieved"):
            raise ValueError(f"source_resumes_triggered_by_admin_command: Negotiations collection with status {target_employer_state} file does not exist for user {bot_user_id} and vacancy {target_vacancy_id}")

        # ----- CHECK IF RESUME RECORDS file exists, otherwise trigger source resumes command -----
        """
        if not is_resume_records_file_exists(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id):
            create_resumes_directory_and_subdirectories(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_subdirectories=RESUME_SUBDIRECTORIES_LIST)
            create_resume_records_file(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        """
        # ----- SOURCE FRESH RESUMES IDs from negotiations collection -----

        #Build path to the file for the collection of negotiations data
        vacancy_data_dir = get_vacancy_directory(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        negotiations_collection_file_path = vacancy_data_dir / f"negotiations_collections_{target_employer_state}.json"
        #Open negotiations collection data file and get resumes IDs
        with open(negotiations_collection_file_path, "r", encoding="utf-8") as f:
            negotiations_collection_data = json.load(f)

        fresh_resume_id_and_negotiation_id_dict = {} # used to update resume records file with negotiation_id
        
        for negotiations_collection_item in negotiations_collection_data["items"]:
            negotiation_id = negotiations_collection_item["id"]
            resume_id = negotiations_collection_item["resume"]["id"]
            """if not is_resume_id_exists_in_resume_records(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id):"""
            if not is_value_in_db(db_model=Negotiations, field_name="id", value=resume_id):
                fresh_resume_id_and_negotiation_id_dict[resume_id] = negotiation_id
        
        logger.debug(f"source_resumes_triggered_by_admin_command: fresh resume ID and negotiation ID dictionary: {fresh_resume_id_and_negotiation_id_dict}")

        #if not fresh_resume_ids_from_negotiations_collection:
        if not fresh_resume_id_and_negotiation_id_dict:
            raise ValueError(f"source_resumes_triggered_by_admin_command: No fresh resumes found in negotiations collection for user {bot_user_id} and vacancy {target_vacancy_id}")

        # ----- PREPARE RESUME directory for 'new' resumes -----

        resume_data_dir = get_resume_directory(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        #Get path to the directory for new resumes
        new_resume_data_dir = Path(resume_data_dir) / "new"

        # ----- DOWNLOAD RESUMES from HH.ru to "new" resumes -----

        #Download resumes from HH.ru and save to file
        success_count = 0
        fail_count = 0
        
        #for resume_id in fresh_resume_ids_from_negotiations_collection:
        for resume_id, negotiation_id in fresh_resume_id_and_negotiation_id_dict.items():
            try:
                resume_file_path = new_resume_data_dir / f"resume_{resume_id}.json"
                resume_data = get_resume_info(access_token=access_token, resume_id=resume_id)
                # Write resume data JSON into resume_file_path
                create_json_file_with_dictionary_content(file_path=str(resume_file_path), content_to_write=resume_data)
                logger.debug(f"source_resumes_triggered_by_admin_command: successfully downloaded resume {resume_id} to file: {resume_file_path}")

                # ----- UPDATE RESUME_RECORDS file with new resume_record_id and contact data -----

                #Create new resume record in resume records file with specific structure
                create_record_for_new_resume_id_in_resume_records(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id)
                logger.debug(f"source_resumes_triggered_by_admin_command: successfully created new resume record in resume records file with resume_record_id: {resume_id}")
        
                # ----- ENRICH RESUME_RECORDS file with resume data -----

                # Update resume records with new resume data
                first_name = resume_data.get("first_name", "")
                last_name = resume_data.get("last_name", "")
                
                # Safely extract phone and email from contact array
                phone = ""
                email = ""
                contacts_list = resume_data.get("contact", [])
                
                for contact in contacts_list:
                    # Handle both "value" and "contact_value" keys
                    contact_data = contact.get("contact_value") or contact.get("value")
                    
                    # Skip if contact_data is None or not a string
                    if not isinstance(contact_data, str):
                        continue
                    
                    # Filter email by '@' sign
                    if "@" in contact_data:
                        email = contact_data
                    elif not phone:
                        # If it's a string but not email, assume it's phone (if phone not set yet)
                        phone = contact_data
                
                # Log warning if contact data is missing
                if not phone:
                    logger.warning(f"source_resumes_triggered_by_admin_command: No phone found for resume {resume_id}")
                if not email:
                    logger.debug(f"source_resumes_triggered_by_admin_command: No email found for resume {resume_id}")

                update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="negotiation_id", value=negotiation_id) # ValueError raised if fails
                update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="first_name", value=first_name) # ValueError raised if fails
                update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="last_name", value=last_name) # ValueError raised if fails
                update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="phone", value=phone) # ValueError raised if fails
                update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="email", value=email) # ValueError raised if fails
                logger.debug(f"source_resumes_triggered_by_admin_command: successfully updated resume records file with new resume_record_id: {resume_id}")
                success_count += 1
            except Exception as e:
                logger.error(f"source_resumes_triggered_by_admin_command: Failed to process resume {resume_id} for user {bot_user_id}: {e}", exc_info=True)
                fail_count += 1
                continue

        logger.info(f"source_resumes_triggered_by_admin_command: Completed for user_id: {bot_user_id}. Success: {success_count}, Failed: {fail_count}, Total: {len(fresh_resume_id_and_negotiation_id_dict.keys())}")
    
    except Exception as e:
        logger.error(f"source_resumes_triggered_by_admin_command: Failed to source resumes for user_id {bot_user_id}: {e}", exc_info=True)
        raise


async def analyze_resume_triggered_by_admin_command(bot_user_id: str) -> None:
    # TAGS: [resume_related]
    """Analyzes resume with AI. 
    Sorts resumes into "passed" or "failed" directories based on the final score. 
    Triggers 'send_message_to_applicants_command' and 'change_employer_state_command' for each resume.
    Does not trigger any other commands once done.
    """
    
    try:
        logger.info(f"analyze_resume_triggered_by_admin_command: started. User_id: {bot_user_id}")

        # ----- IDENTIFY USER and pull required data from records -----
        
        target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)

        # ----- PREPARE paths and files for AI analysis -----

        #Get files paths for AI analysis
        vacancy_data_dir = get_vacancy_directory(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        vacancy_description_file_path = vacancy_data_dir / "vacancy_description.json"
        sourcing_criterias_file_path = vacancy_data_dir / "sourcing_criterias.json"
        resume_analysis_prompt_file_path = Path(PROMPT_DIR) / "for_resume.txt"
        resume_data_dir = get_resume_directory(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        new_resume_data_path = Path(resume_data_dir) / "new"
        passed_resume_data_path = Path(resume_data_dir) / "passed"
        failed_resume_data_path = Path(resume_data_dir) / "failed"

        # Load inputs for AI analysis
        with open(vacancy_description_file_path, "r", encoding="utf-8") as f:
            vacancy_description = json.load(f)
        with open(sourcing_criterias_file_path, "r", encoding="utf-8") as f:
            sourcing_criterias = json.load(f)
        with open(resume_analysis_prompt_file_path, "r", encoding="utf-8") as f:
            resume_analysis_prompt = f.read() 

        # ----- QUEUE RESUMES for AI ANALYSIS -----

        # Add resumes to AI analysis queue
        new_resume_data_path.mkdir(parents=True, exist_ok=True)
        new_resume_json_paths_list = list(new_resume_data_path.glob("*.json"))
        num_of_new_resumes = len(new_resume_json_paths_list)
        logger.debug(f"Total resumes: {num_of_new_resumes} in directory {new_resume_data_path}")
        queued_resumes = 0
        failed_resumes = 0
        
        # Open each resume file and add AI analysis task to queue
        for resume_json_path in new_resume_json_paths_list:
            try:
                resume_id = resume_json_path.stem.split("_")[1]
                with open(resume_json_path, "r", encoding="utf-8") as rf:
                    resume_json = json.load(rf)
                
                # Add AI analysis task to queue
                await ai_task_queue.put(
                    resume_analysis_from_ai_to_user_sort_resume,
                    bot_user_id,
                    target_vacancy_id,
                    vacancy_description,
                    sourcing_criterias,
                    resume_id,
                    resume_json_path,
                    resume_json,
                    resume_analysis_prompt,
                    passed_resume_data_path,
                    failed_resume_data_path,
                    task_id=f"resume_analysis_{bot_user_id}_{target_vacancy_id}_{resume_id}"
                )
                queued_resumes += 1
                logger.info(f"Added resume {resume_id} to analysis queue. Total queued: {queued_resumes} out of {num_of_new_resumes}")
            except Exception as e:
                logger.error(f"Failed to queue resume analysis for '{resume_json_path}': {e}", exc_info=True)
                failed_resumes += 1
                continue

        # ----- COMMUNICATE RESULT of QUEUING RESUMES -----
        logger.info(f"analyze_resume_triggered_by_admin_command: Completed for user_id: {bot_user_id}. Success: {queued_resumes}, Failed: {failed_resumes}, Total: {num_of_new_resumes}")
    
    except Exception as e:
        logger.error(f"analyze_resume_triggered_by_admin_command: Failed. user_id {bot_user_id}: {e}", exc_info=True)
        raise


async def resume_analysis_from_ai_to_user_sort_resume(
    bot_user_id: str,
    target_vacancy_id: str,
    vacancy_description: dict,
    sourcing_criterias: dict,
    resume_id: str,
    resume_json_path: Path,
    resume_json: dict,
    resume_analysis_prompt: str,
    passed_resume_data_path: Path,
    failed_resume_data_path: Path,
    ) -> None:
    """
    Wrapper function to process resume analysis result.
    This function is executed through TaskQueue.
    """
    try:
        # Call AI analyzer
        ai_analysis_result = analyze_resume_with_ai(
            vacancy_description=vacancy_description,
            sourcing_criterias=sourcing_criterias,
            resume_data=resume_json,
            prompt_resume_analysis_text=resume_analysis_prompt
        )
        
        # Update resume records with AI analysis results
        update_resume_record_with_top_level_key(
            bot_user_id=bot_user_id,
            vacancy_id=target_vacancy_id,
            resume_record_id=resume_id,
            key="ai_analysis",
            value=ai_analysis_result
        )
        # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()

        # Send message to applicant
        """
        await send_message_to_applicant_command(bot_user_id=bot_user_id, resume_id=resume_id)
        """
        
        # Change employer state
        await change_employer_state_command(bot_user_id=bot_user_id, resume_id=resume_id)
        
        # Sort resume based on final score
        resume_final_score = int(ai_analysis_result.get("final_score", 0))
        if resume_final_score >= RESUME_PASSED_SCORE:
            shutil.move(resume_json_path, passed_resume_data_path)
            update_resume_record_with_top_level_key(
                bot_user_id=bot_user_id,
                vacancy_id=target_vacancy_id,
                resume_record_id=resume_id,
                key="resume_sorting_status",
                value="passed"
            )
            # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()
        else:
            shutil.move(resume_json_path, failed_resume_data_path)
            update_resume_record_with_top_level_key(
                bot_user_id=bot_user_id,
                vacancy_id=target_vacancy_id,
                resume_record_id=resume_id,
                key="resume_sorting_status",
                value="failed"
            )
            # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()
    except Exception as e:
        logger.error(f"Failed to process resume analysis for {resume_id}: {e}", exc_info=True)
        raise


async def send_message_to_applicant_command(bot_user_id: str, resume_id: str) -> None:
    # TAGS: [resume_related]
    """Sends message to applicant. Triggers 'change_employer_state_command'."""
    
    # ----- IDENTIFY USER and pull required data from records -----
    
    access_token = get_access_token_from_records(bot_user_id=bot_user_id)
    target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)

    # ----- SEND MESSAGE TO APPLICANT  -----

    # Get negotiation ID from resume record
    negotiation_id = get_negotiation_id_from_resume_record(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id)
    # Create Telegram bot link for applicant
    tg_link = create_tg_bot_link_for_applicant(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_id=resume_id)
    negotiation_message_text = APPLICANT_MESSAGE_TEXT_WITHOUT_LINK + f"{tg_link}"
    logger.debug(f"Sending message to applicant for negotiation ID: {negotiation_id}")
    try:
        send_negotiation_message(access_token=access_token, negotiation_id=negotiation_id, user_message=negotiation_message_text)
        logger.info(f"Message to applicant for negotiation ID: {negotiation_id} has been successfully sent")
    except Exception as send_err:
        logger.error(f"Failed to send message for negotiation ID {negotiation_id}: {send_err}", exc_info=True)
        # stop method execution in this case, because no need to update resume_records and negotiations status
        return

    # ----- UPDATE RESUME_RECORDS file with new status of request to shoot resume video -----

    new_status_of_request_to_shoot_resume_video = "yes"
    update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="request_to_shoot_resume_video_sent", value=new_status_of_request_to_shoot_resume_video)
    # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()


async def change_employer_state_command(bot_user_id: str, resume_id: str) -> None:
    # TAGS: [resume_related]
    """Trigger send message to applicant command handler - allows users to send message to applicant."""

    logger.info(f"change_employer_state_command started. user_id: {bot_user_id}")
    
    # ----- IDENTIFY USER and pull required data from records -----
    
    access_token = get_access_token_from_records(bot_user_id=bot_user_id)
    target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)
    negotiation_id = get_negotiation_id_from_resume_record(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id)

   # ----- CHANGE EMPLOYER STATE  -----

    #await update.message.reply_text(f"Изменяю статус приглашения кандидата на {NEW_EMPLOYER_STATE}...")
    logger.debug(f"Changing collection status of negotiation ID: {negotiation_id} to {EMPLOYER_STATE_CONSIDER}")
    try:
        change_negotiation_collection_status_to_consider(
            access_token=access_token,
            negotiation_id=negotiation_id
        )
        logger.info(f"Collection status of negotiation ID: {negotiation_id} has been successfully changed to {EMPLOYER_STATE_CONSIDER}")
    except Exception as status_err:
        logger.error(f"Failed to change collection status for negotiation ID {negotiation_id}: {status_err}", exc_info=True)


async def update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command(bot_user_id: str, vacancy_id: str) -> None:
    # TAGS: [resume_related]
    """Update resume records with fresh videos from applicants directory.
    Sends notification to admin if fails"""

    logger.info(f"update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command: started. user_id: {bot_user_id}")
    
    try:
        # ----- PREPARE PATHS to video files -----

        """video_from_applicants_dir = get_directory_for_video_from_applicants(bot_user_id=bot_user_id, vacancy_id=vacancy_id) # ValueError raised if fails"""
        video_from_applicants_dir = get_data_subdirectory_path(subdirectory_name="videos")# ValueError raised if fails
        all_video_paths_list = list(video_from_applicants_dir.glob("*.mp4"))
        fresh_videos_list = []
        success_count = 0
        fail_count = 0
        
        for video_path in all_video_paths_list:
            try:
                # Parse video path to get resume ID. Video shall have the following structure: 
                # - type #1: applicant_{applicant_user_id}_resume_{resume_id}_time_{timestamp}_note.mp4
                # - type #2: - applicant_{applicant_user_id}_resume_{resume_id}_time_{timestamp}.mp4
                resume_id = video_path.stem.split("_")[3]
                logger.debug(f"update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command: Found applicant video. Video path: {video_path} / Resume ID: {resume_id}")
                # If video not recorded, update list and update resume records
                """if not is_applicant_video_recorded(bot_user_id=bot_user_id, vacancy_id=vacancy_id, resume_id=resume_id):"""
                if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_video_received"):
                    fresh_videos_list.append(resume_id)
                    update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=vacancy_id, resume_record_id=resume_id, key="resume_video_received", value="yes") # ValueError raised if fails
                    update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=vacancy_id, resume_record_id=resume_id, key="resume_video_path", value=str(video_path)) # ValueError raised if fails
                    success_count += 1
            except Exception as e:
                logger.error(f"update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command: Failed to process video {video_path} for user {bot_user_id}: {e}", exc_info=True)
                fail_count += 1
                continue
        
        logger.info(f"update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command: Completed for user_id: {bot_user_id}. Success: {success_count}, Failed: {fail_count}, Total: {len(all_video_paths_list)}")
    
    except Exception as e:
        logger.error(f"update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command: Failed. user_id {bot_user_id}: {e}", exc_info=True)
        raise

async def recommend_resumes_triggered_by_admin_command(bot_user_id: str, application: Application) -> None:
    # TAGS: [recommendation_related]
    """Recommend resumes. Criteria:
    1. Resume is passed
    2. Resume has video
    3. Resume is not recommended yet
    Sends notification to admin if fails"""

    logger.info(f"recommend_resumes_triggered_by_admin_command: started. user_id: {bot_user_id}")

    # ----- IDENTIFY USER and pull required data from records -----
        
    target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)
    target_vacancy_name = get_target_vacancy_name_from_records(record_id=bot_user_id)

    # ----- VALIDATE VACANCY IS SELECTED and has description and sourcing criterias exist -----

    try:

        validation_errors = []
        for field_name in (
            "vacancy_selected",
            "vacancy_description_recieved",
            "vacancy_sourcing_criterias_recieved",
        ):
            if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name=field_name):
                validation_errors.append(f"{field_name} - False")
        if validation_errors:
            raise ValueError(f"Validation failed: {', '.join(validation_errors)}")

        # ----- GET LIST of RESUME IDs that passed and have video -----

        resume_ids_for_recommendation = get_list_of_resume_ids_for_recommendation(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id)
        logger.debug(f"recommend_resumes_triggered_by_admin_command: List of resume IDs for recommendation has been fetched: {resume_ids_for_recommendation}.")

        # ----- COMMUNICATE SUMMARY of recommendation -----

        num_resume_ids_for_recommendation = len(resume_ids_for_recommendation)
        # if there are no suitable applicants, communicate the result
        if num_resume_ids_for_recommendation == 0:
            if application and application.bot:
                logger.info(f"recommend_resumes_triggered_by_admin_command: No suitable resumes found for recommendation. Sending message to user {bot_user_id}.")
                await application.bot.send_message(chat_id=int(bot_user_id), text=f"Вакансия: '{target_vacancy_name}'.\nПока нет подходящих кандидатов.")
            else:
                logger.warning(f"recommend_resumes_triggered_by_admin_command: Cannot send message to user {bot_user_id}: application or bot instance not provided")
            return

        # ----- COMMUNICATE RESULT of resumes with video -----

        # build text based on data from resume records
        for resume_id in resume_ids_for_recommendation:

            try:
                # ----- GET RECOMMENDATION TEXT and VIDEO PATH for each applicant -----

                recommendation_text = get_resume_recommendation_text_from_resume_records(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id)
                # If nothing in resume records, ValueError is raised from method: get_resume_recommendation_text_from_resume_records()
                """
                applicant_video_file_path = get_path_to_video_from_applicant_from_resume_records(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id)
                # If nothing in resume records, ValueError is raised from method: get_path_to_video_from_applicant_from_resume_records()
                """
                # ----- SEND RECOMMENDATION TEXT and VIDEO for each applicant -----
                
                if application and application.bot:
                    await application.bot.send_message(chat_id=int(bot_user_id), text=recommendation_text, parse_mode=ParseMode.HTML)
                    logger.info(f"recommend_resumes_triggered_by_admin_command: Recomendation text for resume {resume_id} has been successfully sent to user {bot_user_id}")
                    """
                    await application.bot.send_video(chat_id=int(bot_user_id), video=str(applicant_video_file_path))
                    logger.info(f"recommend_resumes_triggered_by_admin_command: Video for resume {resume_id} has been successfully sent to user {bot_user_id}")
                    """
                    update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=target_vacancy_id, resume_record_id=resume_id, key="resume_recommended", value="yes")
                    # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()
                    logger.info(f"recommend_resumes_triggered_by_admin_command: Resume records for resume {resume_id} has been successfully updated with recommended status 'yes'")
                    
                    # ----- SEND BUTTON TO INVITE APPLICANT TO INTERVIEW -----
                    # cannot use "questionnaire_service.py", because requires update and context objects
                    
                    # Create inline keyboard with invite button
                    if not resume_id:
                        raise ValueError(f"Missing required resume_id for invite button callback_data")
                    
                    callback_data = f"{INVITE_TO_INTERVIEW_CALLBACK_PREFIX}:{resume_id}"
                    
                    invite_button = InlineKeyboardButton(
                        text=BTN_INVITE_TO_INTERVIEW,
                        callback_data=callback_data
                    )
                    keyboard = InlineKeyboardMarkup([[invite_button]])
                    await application.bot.send_message(
                        chat_id=int(bot_user_id),
                        text=f"Хотите пригласить кандидата на интервью?", 
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                else:
                    raise ValueError(f"Missing required application or bot instance for sending message to user {bot_user_id}")
            except Exception as e:
                logger.error(f"recommend_resumes_triggered_by_admin_command: Failed to process resume {resume_id}: {e}. Skipping this resume and continuing with others.", exc_info=True)
                continue
    except Exception as e:
        logger.error(f"recommend_resumes_triggered_by_admin_command: Failed: {e}", exc_info=True)
        raise


async def handle_invite_to_interview_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [recommendation_related]
    """Handle invite to interview button click. Sends notification to admin.
    Sends notification to admin if fails"""
    
    if not update.callback_query:
        return
    
    try:
        # ----- IDENTIFY USER and pull required data from callback -----
        
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"handle_invite_to_interview_button started. user_id: {bot_user_id}")
        
        # Use handle_answer() from questionnaire_service to extract callback_data and handle keyboard removal
        callback_data = await handle_answer(update, context, remove_keyboard=True)
        
        if not callback_data or not callback_data.startswith(INVITE_TO_INTERVIEW_CALLBACK_PREFIX):
            raise ValueError(f"Invalid callback_data for invite to interview: {callback_data}")


        # ----- EXTRACT DATA from callback_data -----

        parts = callback_data.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid callback_data format for invite to interview: {callback_data}")
        
        # Unpack (destruct) tuple to assign values from a list to variables.
        callback_prefix, resume_id = parts
        
        # Get user_id and vacancy_id from records (user_id is bot_user_id from update)
        user_id = bot_user_id
        vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)
        vacancy_name = get_target_vacancy_name_from_records(record_id=bot_user_id)

        # ----- SEND NOTIFICATION TO ADMIN -----
            
        if context.application:
            admin_message = (
                f"📞 Пользователь {user_id}.\n"
                f"хочет пригласить кандидата {resume_id} на интервью.\n"
                f"Вакансия: {vacancy_id}: {vacancy_name}.\n"
                f"Резюме кандидата: {resume_id}."
            )
            await send_message_to_admin(
                application=context.application,
                text=admin_message
            )
            

            resume_records_file_path = get_resume_records_file_path(bot_user_id=bot_user_id, vacancy_id=vacancy_id)
            # Read existing data
            with open(resume_records_file_path, "r", encoding="utf-8") as f:
                resume_records = json.load(f)
            resume_record_id_data = resume_records[resume_id]

            # ----- GET VALUES for TEXT -----

            first_name = resume_record_id_data["first_name"]
            last_name = resume_record_id_data["last_name"]
            
            msg_text = INVITE_TO_INTERVIEW_SENT_TEXT_START + f"'{first_name} {last_name}'" + INVITE_TO_INTERVIEW_SENT_TEXT_END
            # Confirm to user (keyboard already removed by handle_answer())
            await send_message_to_user(update, context, text=msg_text)

            update_resume_record_with_top_level_key(bot_user_id=bot_user_id, vacancy_id=vacancy_id, resume_record_id=resume_id, key="resume_accepted", value="yes")
            # If cannot update resume records, ValueError is raised from method: update_resume_record_with_top_level_key()
            logger.info(f"handle_invite_to_interview_button: Resume records for resume {resume_id} has been successfully updated with accepted status 'yes'")
            
        else:
            raise ValueError(f"Invalid callback_data format for invite to interview: {callback_data}")
    except Exception as e:
        logger.error(f"Failed to handle invite to interview: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error handling invite to interview: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )



########################################################################################
# ------------ MAIN MENU related commands ------------
########################################################################################

async def user_status(bot_user_id: str) -> dict:
    status_dict = {}
    """status_dict["bot_authorization"] = is_user_in_records(record_id=bot_user_id)"""
    status_dict["bot_authorization"] = is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id)
    """status_dict["privacy_policy_confirmation"] = is_manager_privacy_policy_confirmed(bot_user_id=bot_user_id)"""
    status_dict["hh_authorization"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmation")
    """status_dict["hh_authorization"] = is_user_authorized(record_id=bot_user_id)"""
    status_dict["hh_authorization"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token_recieved")
    """status_dict["vacancy_selection"] = is_vacancy_selected(record_id=bot_user_id)"""
    status_dict["vacancy_selection"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_selected")

    vacancy_id = get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_id")
    """status_dict["welcome_video_recording"] = is_welcome_video_recorded(record_id=bot_user_id)"""
    status_dict["vacancy_video_received"] = is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="vacancy_video_received")
    target_vacancy_id = get_target_vacancy_id_from_records(record_id=bot_user_id)
    # depends on vacancy selection
    if target_vacancy_id: # not None
        """status_dict["vacancy_description_recieved"] = is_vacancy_description_recieved(record_id=bot_user_id)"""
        status_dict["vacancy_description_recieved"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_description_recieved")
        """status_dict["sourcing_criterias_recieved"] = is_vacancy_sourcing_criterias_recieved(record_id=bot_user_id)"""
        status_dict["sourcing_criterias_recieved"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="sourcing_criterias_recieved")
    else:
        status_dict["vacancy_description_recieved"] = False
        status_dict["sourcing_criterias_recieved"] = False
    return status_dict


async def build_user_status_text(bot_user_id: str, status_dict: dict) -> str:

    status_to_text_transcription = {
        "bot_authorization": " Авторизация в боте.",
        "privacy_policy_confirmation": " Согласие на обработку перс. данных.",
        "hh_authorization": " Авторизация в HeadHunter.",
        "vacancy_selection": " Выбор вакансии.",
        "welcome_video_recording": " Приветственное видео.",
        "vacancy_description_recieved": " Описание вакансии.",
        "sourcing_criterias_recieved": " Критерии отбора.",
    }
    status_images = {True: "✅", False: "❌"}
    user_status_text = "Статус пользователя:\n"
    for key, value_bool in status_dict.items():
        status_image = status_images[value_bool]
        status_text = status_to_text_transcription[key]
        user_status_text += f"{status_image}{status_text}\n"

    target_vacancy_name = get_target_vacancy_name_from_records(record_id=bot_user_id)
    if target_vacancy_name: # not None
        user_status_text += f"\nВакансия в работе: {target_vacancy_name}.\n"
    return user_status_text


async def show_chat_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    # ----- IDENTIFY USER and pull required data from records -----
    
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"show_chat_menu_command started. user_id: {bot_user_id}")
    status_dict = await user_status(bot_user_id=bot_user_id)
    status_text = await build_user_status_text(bot_user_id=bot_user_id, status_dict=status_dict)

    status_to_button_transcription = {
        "bot_authorization": "Авторизация в боте",
        "privacy_policy_confirmation": "Обработка перс. данных",
        "hh_authorization": "Авторизоваться на HeadHunter",
        "vacancy_selection": "Выбрать вакансию",
        "welcome_video_recording": "Записать приветственное видео",
        "vacancy_description_recieved": "Запросить описание вакансии",
        "sourcing_criterias_recieved": "Выработать критерии отбора",
    }
    answer_options = []
    for key, value_bool in status_dict.items():
        # add button only if status is False (not completed)
        if key in status_to_button_transcription and value_bool == False:
            answer_options.append((status_to_button_transcription[key], "menu_action:" + key))
    logger.debug(f"Answer options for chat menu: {answer_options}")

    # ----- STORE ANSWER OPTIONS in CONTEXT -----
    
    context.user_data["chat_menu_action_options"] = answer_options
    
    # ----- SEND MESSAGE WITH STATUS AND BUTTONS USING ask_question_with_options -----
    
    # Always send status text, even if no options available
    if answer_options:
        await ask_question_with_options(
            update=update,
            context=context,
            question_text=status_text,
            answer_options=answer_options
        )
    else:
        # If no options, just send status text without buttons
        await send_message_to_user(update, context, text=status_text)


async def handle_chat_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle chat menu action button clicks."""

    # ----- IDENTIFY USER and pull required data from records -----
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_chat_menu_action started. user_id: {bot_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------
    
    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)
    
    if not selected_callback_code:
        logger.warning("No callback_code received from handle_answer")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return
    
    # ----- UNDERSTAND TEXT on clicked button from option taken from context -----
    
    # Get options from context or return empty list [] if not found
    chat_menu_action_options = context.user_data.get("chat_menu_action_options", [])
    # find selected button text from callback_data
    selected_button_text = None
    for button_text, callback_code in chat_menu_action_options:
        if selected_callback_code == callback_code:
            selected_button_text = button_text
            # Clear chat menu action options from "context" object, because now use "selected_button_text" variable instead
            context.user_data.pop("chat_menu_action_options", None)
            break
    
    # ----- INFORM USER about selected option -----
    
    # If "options" is NOT an empty list execute the following code
    if chat_menu_action_options and selected_button_text:
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No options available, inform user and return
        logger.warning(f"Could not find button text for callback_code '{selected_callback_code}'. Available options: {chat_menu_action_options}")
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return
    
    # ----- EXTRACT ACTION from callback_data and route to appropriate command -----
    
    # Extract action from callback_data (format: "menu_action:action_name")
    action = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
    logger.debug(f"Extracted action from callback_code '{selected_callback_code}': '{action}'")
 

    if action == "bot_authorization":
        await start_command(update=update, context=context)
    elif action == "privacy_policy_confirmation" or action == "privacy_policy":
        await ask_privacy_policy_confirmation_command(update=update, context=context)
    elif action == "hh_authorization":
        await hh_authorization_command(update=update, context=context)
    elif action == "vacancy_selection":
        await select_vacancy_command(update=update, context=context)
    elif action == "welcome_video_recording":
        await ask_to_record_video_command(update=update, context=context)
    elif action == "vacancy_description_recieved":
        await read_vacancy_description_command(update=update, context=context)
    elif action == "sourcing_criterias_recieved":
        await define_sourcing_criterias_command(update=update, context=context)
    else:
        logger.warning(f"Unknown action '{action}' from callback_code '{selected_callback_code}'. Available actions: bot_authorization, privacy_policy_confirmation, privacy_policy, hh_authorization, hh_auth, select_vacancy, record_video, get_recommendations")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


async def handle_feedback_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle feedback button click. Sets flag to wait for user feedback message."""
        
    # ----- IDENTIFY USER and pull required data from records -----
    
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_feedback_button_click started. user_id: {bot_user_id}")

    # ----- SET WAITING FOR FEEDBACK FLAG TO TRUE -----

    # Reset flag and allow new feedback (user can click button again to send new message)
    context.user_data["waiting_for_feedback"] = True
    await send_message_to_user(update, context, text=FEEDBACK_REQUEST_TEXT)


async def handle_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle feedback message from user. Forwards it to admin."""
    
    # ----- CHECK IF MESSAGE IS NOT EMPTY -----

    if not update.message:
        return
    
    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_feedback_message started. user_id: {bot_user_id}")
    
    # ----- CHECK FOR WAITING FOR FEEDBACK FLAG -----

    # if not waiting for feedback, ignore this message
    if not context.user_data.get("waiting_for_feedback", False):
        return  # Not waiting for feedback, ignore this message
    # if waiting for feedback, clear the flag (only allow 1 message)
    context.user_data["waiting_for_feedback"] = False

    # ----- GET FEEDBACK TEXT -----

    feedback_text = update.message.text.strip()
    
    # ----- FORWARD FEEDBACK TO ADMIN -----

    try:
        if context.application:
            # Get user info for admin message
            """
            user_records_path = get_users_records_file_path()
            user_info = ""
            """
            try:
                """
                with open(user_records_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    if is_user_in_records(record_id=bot_user_id):
                        username = records[bot_user_id].get("username", "N/A")
                        first_name = records[bot_user_id].get("first_name", "N/A")
                        last_name = records[bot_user_id].get("last_name", "N/A")
                        user_info = f"Пользователь: ID: {bot_user_id}, @{username}, {first_name} {last_name})"
                    else:
                        user_info = f"Пользователь ID: {bot_user_id}, не найден в records."
                """
                if is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
                    username = get_column_value_in_db(db_model=Managers, field_name="username", value=bot_user_id)
                    first_name = get_column_value_in_db(db_model=Managers, field_name="first_name", value=bot_user_id)
                    last_name = get_column_value_in_db(db_model=Managers, field_name="last_name", value=bot_user_id)
                    user_info = f"Пользователь: ID: {bot_user_id}, @{username}, {first_name} {last_name})"
                else:
                    user_info = f"Пользователь ID: {bot_user_id}, не найден в records."

            except Exception as e:
                logger.error(f"Failed to get user info for feedback: {e}")
                user_info = f"Пользователь ID: {bot_user_id}"
            
            admin_message = f"⚠️  Обратная связь от пользователя\n\n{user_info}\n\nСообщение:\n{feedback_text}"
            await send_message_to_admin(
                application=context.application,
                text=admin_message
            )
            # Confirm to user
            await send_message_to_user(update, context, text=FEEDBACK_SENT_TEXT)
        else:
            logger.error("Cannot send feedback to admin: application not available")
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
    except Exception as e:
        logger.error(f"Failed to send feedback to admin: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


async def handle_feedback_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle non-text messages when waiting for feedback (reject audio, images, etc.)."""
    
    if not update.message:
        return
    
    # Check if we're waiting for feedback
    if not context.user_data.get("waiting_for_feedback", False):
        return  # Not waiting for feedback, ignore this message
    
    # User sent non-text content (audio, image, document, etc.)
    await send_message_to_user(update, context, text=FEEDBACK_ONLY_TEXT_ALLOWED_TEXT)


async def handle_bottom_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom manager menu buttons."""

    if not update.message:
        return

    message_text = (update.message.text or "").strip()

    if message_text == BTN_MENU:
        # Clear all unprocessed inline keyboards before showing status
        # IMPORTANT: to avoid showing old keyboards when user clicks "Статус" button to avoid data rewriting
        chat_id = update.message.chat.id
        await clear_all_unprocessed_keyboards(update, context, chat_id)
        await show_chat_menu_command(update, context)
    elif message_text == BTN_FEEDBACK:
        # Handle feedback button click
        await handle_feedback_button_click(update, context)




########################################################################################
# ------------  APPLICATION SETUP ------------
########################################################################################


def create_manager_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CallbackQueryHandler(handle_answer_select_vacancy, pattern=r"^\d+$"))
    application.add_handler(CallbackQueryHandler(handle_answer_video_record_request, pattern=r"^record_video_request:"))
    application.add_handler(CallbackQueryHandler(handle_answer_confrim_sending_video, pattern=r"^sending_video_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_answer_policy_confirmation, pattern=r"^privacy_policy_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_answer_sourcing_criterias_confirmation, pattern=r"^sourcing_criterias_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_chat_menu_action, pattern=r"^menu_action:"))
    application.add_handler(CallbackQueryHandler(handle_invite_to_interview_button, pattern=r"^invite_to_interview:"))
    
    menu_buttons_pattern = f"^({re.escape(BTN_MENU)}|{re.escape(BTN_FEEDBACK)})$"
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(menu_buttons_pattern), handle_bottom_menu_buttons)
    )
    # Handler for feedback messages (text only, when waiting_for_feedback flag is set)
    # This handler must be added AFTER menu buttons handler to avoid conflicts
    # Exclude commands (~filters.COMMAND) so command handlers can process them first
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.Regex(menu_buttons_pattern) & ~filters.COMMAND, handle_feedback_message)
    )
    # Handler for non-text messages when waiting for feedback (reject audio, images, etc.)
    # This must be added BEFORE video and audio handlers so it can check the flag first
    # Exclude videos and audio so they can be handled by their specific handlers
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.TEXT & ~(filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO) & ~(filters.AUDIO | filters.VOICE | filters.Document.AUDIO),
            handle_feedback_non_text_message
        )
    )
    # this handler listens to all video messages and passes them to the video service - 
    # "MessageHandler" works specifically with messages, not callback queries
    # "filters.ALL & (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO)" means handler will work only with video messages
    # when handler is triggered, it calls the defined lambda function
    application.add_handler(MessageHandler(filters.ALL & (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO), lambda update, context: process_incoming_video(update, context)))
    # this handler listens to all audio messages and passes them to the audio service -
    # "MessageHandler" works specifically with messages, not callback queries
    # "filters.ALL & (filters.AUDIO | filters.VOICE | filters.Document.AUDIO)" means handler will work only with audio messages
    # when handler is triggered, it calls the defined lambda function
    application.add_handler(MessageHandler(filters.ALL & (filters.AUDIO | filters.VOICE | filters.Document.AUDIO), lambda update, context: process_incoming_audio(update, context)))
    return application


