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
import re
import json

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
    clear_all_unprocessed_keyboards,
    ask_single_question_from_update,
    single_question_callback_handler,
    ask_single_question_from_application,
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
    format_oauth_link_text,
    get_resume_recommendation_text_from_resume_records,
    get_data_subdirectory_path,
)

from shared_services.database import (
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

    log_prefix = "send_message_to_admin"

    # ----- GET ADMIN ID from environment variables -----
    
    admin_id = os.getenv("ADMIN_ID", "")
    if not admin_id:
        logger.error(f"{log_prefix}: ADMIN_ID environment variable is not set. Cannot send admin notification.")
        return
    
    # ----- SEND NOTIFICATION to admin -----
    
    try:
        if application and application.bot:
            await application.bot.send_message(
                chat_id=int(admin_id),
                text=text,
                parse_mode=parse_mode
            )
            logger.debug(f"{log_prefix}: Admin notification sent successfully to admin_id: {admin_id}")
        else:
            logger.warning(f"{log_prefix}: Cannot send admin notification: application or bot instance not available")
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)

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
    """Start command handler."""

    log_prefix = "start_command"
    logger.info(f"{log_prefix}: start")

    # ----- SETUP NEW USER and send welcome message -----

    # if existing user, setup_new_user_command will be skipped
    await setup_new_user_command(update=update, context=context)

    # ----- ASK PRIVACY POLICY CONFIRMATION -----
    
    # if already confirmed, second confirmation will be skipped
    await ask_privacy_policy_confirmation_command(update=update, context=context)

    # IMPORTANT: ALL OTHER COMMANDS will be triggered from functions if PRIVACY POLICY is confirmed


async def setup_new_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "setup_new_user_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ------ COLLECT NEW USER ID and CREATE record and user directory if needed ------

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

        # ----- CHECK IF USER is in records and CREATE record and user directory if needed -----
        
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            create_new_record_in_db(db_model=Managers, record_id=bot_user_id)
            logger.info(f"{log_prefix}: user record created for user_id {bot_user_id}")

        # ------ ENRICH RECORDS with NEW USER DATA ------

        user_details = f"tg_user_id: {bot_user_id}\n"
        tg_user_attributes = ["username", "first_name", "last_name"]
        for item in tg_user_attributes:
            tg_user_attribute_value = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute=item)
            user_details += f"{item}: {tg_user_attribute_value}\n"
            update_record_in_db(db_model=Managers, record_id=bot_user_id, updates={item: tg_user_attribute_value})
            # If cannot update user records, ValueError is raised from method: update_user_records_with_top_level_key()
        logger.debug(f"{log_prefix}: user {bot_user_id} in user records is updated with telegram user attributes.")
        
        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"😎 New user has been setup.\n{user_details}"
            )
        
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def ask_privacy_policy_confirmation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "ask_privacy_policy_confirmation_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            await send_message_to_user(update, context, text=FAIL_TO_FIND_USER_IN_RECORDS_TEXT)
            raise ValueError(f"{log_prefix}: user {bot_user_id} not found in database")

        # ----- CHECK IF PRIVACY POLICY is already confirmed and STOP if it is -----

        if is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
            await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)
            logger.info(f"{log_prefix}: privacy policy already confirmed for user_id {bot_user_id}")
            return

        # Build options (button_text, answer_key)
        local_answer_options = [
            ("Ознакомлен, даю согласие на обработку.", "yes"),
            ("Не даю согласие на обрабоку.", "no"),
        ]

        # Store mapping in context for later use in handler (for echoing selected text)
        context.user_data["privacy_policy_confirmation_answer_options"] = local_answer_options

        # Ask single question using new questionnaire service
        await ask_single_question_from_update(
            update=update,
            context=context,
            question_text=PRIVACY_POLICY_CONFIRMATION_TEXT,
            options=local_answer_options,
            callback_prefix="privacy_policy_confirmation",
        )
        logger.info(f"{log_prefix}: privacy policy confirmation question with options asked")

    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def handle_answer_policy_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "handle_answer_policy_confirmation"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

    # ------- UNDERSTAND WHAT BUTTON was clicked and get answer_key -------

    answer_key = await single_question_callback_handler(
        update=update,
        context=context,
        callback_prefix="privacy_policy_confirmation",
    )
    if answer_key is None:
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        logger.error(f"{log_prefix}: no answer_key found")
        return

    # ----- UNDERSTAND TEXT on clicked buttton from options stored in context -----

    privacy_policy_confirmation_answer_options = context.user_data.get(
        "privacy_policy_confirmation_answer_options",
        [],
    )

    selected_button_text = None
    for button_text, key in privacy_policy_confirmation_answer_options:
        if key == answer_key:
            selected_button_text = button_text
            logger.info(f"{log_prefix}: selected button text fetched {selected_button_text}")
            break

    # Clear stored options as they are no longer needed
    context.user_data.pop("privacy_policy_confirmation_answer_options", None)

    # ----- INFORM USER about selected option -----

    if selected_button_text is not None:
        await send_message_to_user(update, context, text=f"Вы выбрали: '{selected_button_text}'")
    else:
        # No options available, inform user and return
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        logger.error(f"{log_prefix}: no selected button text found")
        return

    # ----- UPDATE USER RECORDS with selected decision -----

    if update.callback_query and update.callback_query.message:
        privacy_policy_confirmation_user_decision = answer_key  # "yes" or "no"

        privacy_policy_confirmation_user_value = True if privacy_policy_confirmation_user_decision == "yes" else False
        update_record_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            updates={"privacy_policy_confirmed": privacy_policy_confirmation_user_value},
        )

        current_time = datetime.now(timezone.utc).isoformat()
        update_record_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            updates={"privacy_policy_confirmation_time": current_time},
        )

        logger.debug(f"{log_prefix}: Privacy policy confirmation user {bot_user_id} decision: {privacy_policy_confirmation_user_decision} at {current_time}")

        # ----- IF USER CHOSE "YES" -----

        if privacy_policy_confirmation_user_decision == "yes":

            # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----
            if context.application:
                await send_message_to_admin(
                    application=context.application,
                    text=f"😎 New user {bot_user_id} has given privacy policy confirmation.",
                )

            # ----- SEND AUTHENTICATION REQUEST and wait for user to authorize -----
            await hh_authorization_command(update=update, context=context)

        # ----- IF USER CHOSE "NO" -----
        else:
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)


async def hh_authorization_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "hh_authorization_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
        
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
            raise ValueError(f"Server authorization is not available. User {bot_user_id} cannot authorize.")

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

                    logger.info(f"{log_prefix}: Authorization successful on attempt {attempt}. Access token '{access_token}' and expires_at '{expires_at}' updated in records.")
                    await send_message_to_user(update, context, text=AUTH_SUCCESS_TEXT)

                    if context.application:
                        await send_message_to_admin(
                            application=context.application,
                            text=f"😎 New user {bot_user_id} has authorized on attempt {attempt}."
                        )

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
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def pull_user_data_from_hh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Pull user data from HH and enrich records with it."""

    log_prefix = "pull_user_data_from_hh_command"
    logger.info(f"{log_prefix}: start")
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
        access_token = get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token")

        # ----- CHECK IF USER DATA is already in records and STOP if it is -----

        # Check if user is already authorized, if not, pull user data from HH
        if get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="hh_data") is not None:
            logger.debug(f"{log_prefix}: user {bot_user_id} already has HH data in user record.")
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
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def ask_to_record_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask to record video command.""" 

    log_prefix = "ask_to_record_video_command"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

    # Get status of video received from Vacancies table by manager_id
    is_vacancy_video_received = get_column_value_by_field(
        db_model=Vacancies,
        search_field_name="manager_id",
        search_value=bot_user_id,
        target_field_name="video_received"
    )

    if is_vacancy_video_received:
        logger.debug(f"{log_prefix}: user {bot_user_id} already has welcome video recorded.")
        await send_message_to_user(update, context, text=SUCCESS_TO_RECORD_VIDEO_TEXT)
        return

    # ----- CHECK MUST CONDITIONS are met and STOP if not -----

    if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
        logger.debug(f"{log_prefix}: user {bot_user_id} doesn't have privacy policy confirmed.")
        await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
        return

    if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_selected"):
        logger.debug(f"{log_prefix}: user {bot_user_id} doesn't have target vacancy selected.")
        await send_message_to_user(update, context, text=MISSING_VACANCY_SELECTION_TEXT)
        return

    await send_message_to_user(update, context, text=INSTRUCTIONS_TO_SHOOT_VIDEO_TEXT_MANAGER)
    await asyncio.sleep(1)
    await send_message_to_user(update, context, text=INFO_DROP_VIDEO_HERE_TEXT)
    logger.debug(f"{log_prefix}: instructions to shoot video sent")


async def ask_confirm_sending_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask confirm sending video command handler. """

    log_prefix = "ask_confirm_sending_video_command"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

    # Use generic single-question helper from questionnaire_service
    options = [
        ("Да. Отправить это.", "yes"),
        ("Нет. Попробую еще раз.", "no"),
    ]
    await ask_single_question_from_update(
        update=update,
        context=context,
        question_text=VIDEO_SENDING_CONFIRMATION_TEXT,
        options=options,
        callback_prefix="sending_video_confirmation",
    )


async def handle_answer_confrim_sending_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to send video, triggers 'download_incoming_video_locally' method.
    - If user does not agree to send video, inform that waiting for another video to be sent by user.
    """
    
    log_prefix = "handle_answer_confrim_sending_video"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

    # ------- UNDERSTAND WHAT BUTTON was clicked using generic questionnaire helper -------

    answer_key = await single_question_callback_handler(
        update=update,
        context=context,
        callback_prefix="sending_video_confirmation",
    )
    if answer_key is None:
        logger.debug(f"{log_prefix}: no matching answer_key returned")
        return


    # --- UPDATE USER RECORDS with selected option ---

    sending_video_confirmation_user_decision = answer_key

    # ----- IF USER CHOSE "YES" start video download  -----

    if sending_video_confirmation_user_decision == "yes":

        await send_message_to_user(update, context, text="⏳ Сохраняем видео...")

        update_column_value_by_field(
            db_model=Vacancies,
            search_field_name="manager_id",
            search_value=bot_user_id,
            target_field_name="video_sending_confirmed",
            new_value=True,
        )
        
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
            user_type="manager",
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

        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"😎 New user {bot_user_id} has sent video."
            )

    else:

    # ----- IF USER CHOSE "NO" ask for another video -----

        await send_message_to_user(update, context, text=WAITING_FOR_ANOTHER_VIDEO_TEXT)


async def select_vacancy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Asks users to select a vacancy to work with. 
    Called from: 'pull_user_data_from_hh_command'."""

    log_prefix = "select_vacancy_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
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

        # Store options in context so handler can access them (name ↔ id mapping)
        context.user_data["vacancy_options"] = answer_options

        # Use generic single-question helper from questionnaire_service
        await ask_single_question_from_update(
            update=update,
            context=context,
            question_text="🎯 Выберите c какой из вакансий вы хотите работать.",
            options=answer_options,
            callback_prefix="vacancy_select",
        )
    
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def handle_answer_select_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Handle button click.
    Called from: nowhere.
    Triggers 'ask_to_record_video_command'.

    This is called AUTOMATICALLY by Telegram when a button is clicked (via CallbackQueryHandler).
    The options list should be stored in context.user_data["vacancy_options"] when asking the question.
    
    Note: Bot knows which user clicked because:
    - update.effective_user.id contains the user ID (works for both messages and callbacks)
    - context.user_data is automatically isolated per user by python-telegram-bot framework
    Sends notification to admin if fails
    """
    

    log_prefix = "handle_answer_select_vacancy"
    logger.info(f"{log_prefix}: start")

    try:
        # ----- IDENTIFY USER and pull required data from records -----
        
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
        
        # ------- UNDERSTAND WHAT BUTTON was clicked -------

        answer_key = await single_question_callback_handler(
            update=update,
            context=context,
            callback_prefix="vacancy_select",
        )
        if answer_key is None:
            logger.debug(f"{log_prefix}: no matching answer_key returned")
            return

        # ------- CREATE VACANCY RECORD for selected vacancy  -------

        target_vacancy_id = str(answer_key)
        logger.debug(f"{log_prefix}: target vacancy id fetched {target_vacancy_id}")
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
            if str(answer_key) == str(callback_code):
                selected_option = (button_text, callback_code)
                # Clear vacancy options from "context" object, because now use "selected_option" variable instead
                context.user_data.pop("vacancy_options", None)
                break

        if not selected_option:
            raise ValueError(f"{log_prefix}: Selected vacancy option not found for callback_data {answer_key}")

        vacancy_name_value = selected_option[0]

        # Create Vacancies record with required NOT NULL fields set immediately
        update_record_in_db(
            db_model=Managers,
            record_id=bot_user_id,
            updates={"vacancy_selected": True},
        )
        logger.debug(f"{log_prefix}: Managers record updated with vacancy_selected = True")
        create_new_record_in_db(
            db_model=Vacancies,
            record_id=target_vacancy_id,
            initial_values={
                "manager_id": bot_user_id,
                "name": vacancy_name_value,
            },
        )
        logger.debug(f"{log_prefix}: Vacancies record created for vacancy {target_vacancy_id}")

        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"😎 New user {bot_user_id} has selected vacancy: {vacancy_name_value}."
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
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def read_vacancy_description_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [vacancy_related]
    """Read vacancy description and save it. 
    Called from: 'download_incoming_video_locally' from file "services.video_service.py"."""

    log_prefix = "read_vacancy_description_command"
    logger.info(f"{log_prefix}: start")
    # ----- IDENTIFY USER and pull required data from records -----
    
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

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
        
        vacancy_description = get_vacancy_description_from_hh(access_token=access_token, vacancy_id=target_vacancy_id)


        if vacancy_description is None:
            logger.error(f"{log_prefix}: Failed to get vacancy description from HH: {target_vacancy_name}")
            return
        
        await send_message_to_user(update, context, text=INFO_ABOUT_ANALYZING_VACANCY_TEXT)
        
        # ----- SAVE VACANCY DESCRIPTION to file and update records -----

        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=target_vacancy_id, target_field_name="description_recieved", new_value=True)
        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=target_vacancy_id, target_field_name="description_json", new_value=vacancy_description)

        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"😎 Vacancy description recieved for vacancy: {target_vacancy_name} (id: {target_vacancy_id}) for new user {bot_user_id}.\n ❗️ACTION REQUIRED❗️: Define sourcing criterias for this vacancy."
            )
    
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )
    

########################################################################################
# ------------ DEFINING SOURCING CRITERIAS on ADMIN request ------------
########################################################################################


async def define_sourcing_criterias_triggered_by_admin_command(vacancy_id: str) -> None:
    # TAGS: [vacancy_related]
    """Prepare everything for vacancy description analysis and 
    create TaksQueue job to get sourcing criteria from AI and save it to file.
    """

    log_prefix = "define_sourcing_criterias_triggered_by_admin_command"

    try:

        logger.info(f"{log_prefix}: started. vacancy_id: {vacancy_id}")

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
        logger.error(f"Error {log_prefix}: {e}", exc_info=True)
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

    log_prefix = "get_sourcing_criterias_from_ai_and_save_to_db"

    # ----- IDENTIFY USER and pull required data from records -----

    logger.info(f"{log_prefix}: started. vacancy_id: {vacancy_id}")


    try:
        # ----- CALL AI ANALYZER -----

        vacancy_analysis_result = analyze_vacancy_with_ai(
            vacancy_data=vacancy_description,
            prompt_vacancy_analysis_text=prompt_text
        )

        # ----- SAVE SOURCING CRITERIAS to DB -----

        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="sourcing_criterias_recieved", new_value=True)
        update_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="sourcing_criterias_json", new_value=vacancy_analysis_result)
        

        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----
    except Exception as e:
        logger.error(f"Failed to get sourcing criterias and save to DB for vacancy {vacancy_id}: {e}", exc_info=True)        # Send notification to admin about the error
        raise


async def send_sourcing_criterias_and_questionnaire_to_user_triggered_by_admin_command(vacancy_id: str, application: Application) -> None:

    """
    Sends sourcing criterias analysis result to user and then asks for confirmation.
    This function is triggered by admin command and therefore works with `Application`
    instance instead of `update` / `context`.
    """

    log_prefix = "send_sourcing_criterias_and_questionnaire_to_user_triggered_by_admin_command"
    logger.info(f"{log_prefix}: started. vacancy_id: {vacancy_id}")

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
        logger.error(f"{log_prefix}: Failed to send sourcing criterias result to user: {e}", exc_info=True)
        raise


async def ask_sourcing_criterias_confirmation_via_application(bot_user_id: str, application: Application) -> None:
    """
    Variant of `ask_sourcing_criterias_confirmation_command` that works with `Application`
    and `bot_user_id` only (no `update` / `context`). Used when flow is triggered by admin
    command and not directly by the user.
    """

    log_prefix = "ask_sourcing_criterias_confirmation_via_application"

    try:
        logger.info(f"{log_prefix}: started. user_id: {bot_user_id}")

        # ----- CHECK IF USER EXISTS IN DATABASE -----
        if not is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
            if application and application.bot:
                await application.bot.send_message(
                    chat_id=int(bot_user_id),
                    text=FAIL_TO_FIND_USER_IN_RECORDS_TEXT,
                )
            raise ValueError(
                f"User {bot_user_id} not found in database"
            )

        # Use generic single-question helper from questionnaire_service
        options = [
            ("Согласен с критериями отбора.", "yes"),
            ("Не согласен, хочу изменить критерии отбора.", "no"),
        ]

        await ask_single_question_from_application(
            application=application,
            target_user_id=int(bot_user_id),
            question_text=SOURCING_CRITERIAS_CONFIRMATION_TEXT,
            options=options,
            callback_prefix="sourcing_criterias_confirmation",
        )

        logger.info(
            f"{log_prefix}: sourcing criterias confirmation question with options asked"
        )

    except Exception as e:
        logger.error(
            f"{log_prefix}: Failed to ask sourcing criterias confirmation via Application: {e}",
            exc_info=True,
        )
        # Notify admin about the error if possible
        try:
            if application:
                await send_message_to_admin(
                    application=application,
                    text=(
                        f"⚠️ Error {log_prefix}: {e}\n"
                        f"User ID: {bot_user_id if bot_user_id else 'unknown'}"
                    ),
                )
        except Exception:
            logger.error(
                f"{log_prefix}: Failed to send admin notification",
                exc_info=True,
            )


async def handle_answer_sourcing_criterias_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click, updates confirmation status in user records.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to sourcing criterias, triggers 'start_sourcing_command'.
    - If user does not agree to sourcing criterias, asks user for feedback"""

    log_prefix = "handle_answer_sourcing_criterias_confirmation"

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: started. user_id: {bot_user_id}")
    
    # ------- HANDLE ANSWER via generic single-question helper -------

    answer_key = await single_question_callback_handler(
        update=update,
        context=context,
        callback_prefix="sourcing_criterias_confirmation",
    )
    logger.debug(f"{log_prefix}: answer_key: {answer_key}")

    if answer_key is None:
        logger.warning(f"{log_prefix}: answer_key is None")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # Map answer_key to human-readable button text
    options_text_map = {
        "yes": "Согласен с критериями отбора.",
        "no": "Не согласен, хочу изменить критерии отбора.",
    }
    selected_button_text = options_text_map.get(answer_key)

    # ----- INFORM USER about selected option -----
    if selected_button_text:
        logger.debug(
            f"{log_prefix}: selected_button_text resolved from answer_key: {selected_button_text}"
        )
        await send_message_to_user(
            update,
            context,
            text=f"Вы выбрали: '{selected_button_text}'",
        )
    else:
        logger.warning(
            f"{log_prefix}: Unknown answer_key={answer_key} for user_id={bot_user_id}"
        )
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- UPDATE USER RECORDS with selected vacancy data -----

    
    sourcing_criterias_confirmation_user_decision = answer_key
    
    # ----- IF USER CHOSE "YES" download video to local storage -----  
     
    current_time = datetime.now(timezone.utc).isoformat()
    logger.debug(f"{log_prefix}: Sourcing criterias confirmation user decision: {sourcing_criterias_confirmation_user_decision} at {current_time}")
 
    if sourcing_criterias_confirmation_user_decision == "yes":

        sourcing_criterias_confirmation_user_value = True
        update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="sourcing_criterias_confirmed", new_value=sourcing_criterias_confirmation_user_value)
        update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="sourcing_criterias_confirmation_time", new_value=current_time)
        
        user_msg = f"{SUCCESS_TO_GET_SOURCING_CRITERIAS_CONFIRMATION_TEXT}\n{SUCCESS_TO_START_SOURCING_TEXT}"
        admin_msg = f"😎 User {bot_user_id} has confirmed sourcing criterias. Start sourcing manually."

    elif sourcing_criterias_confirmation_user_decision == "no":

        sourcing_criterias_confirmation_user_value = False
        update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="sourcing_criterias_confirmed", new_value=sourcing_criterias_confirmation_user_value)

        user_msg = f"Хорошо, расскажите, почему вы не согласны с критериями отбора кандидатов.\n\nПришлите аудио-запись прямо в этот чат, пожалуйста.\n\nЯ подправлю критерии и пришлю на согласование снова."
        admin_msg = f"😎 User {bot_user_id} has NOT confirmed sourcing criterias. Asked for feedback. Waiting."

    else:   

        user_msg = FAIL_TECHNICAL_SUPPORT_TEXT
        admin_msg = f"😎 User {bot_user_id} something went wrong with sourcing criterias!"

    await send_message_to_user(update, context, text=user_msg)
    await send_message_to_admin(application=context.application, text=admin_msg)


########################################################################################
# ------------ COMMANDS EXECUTED on ADMIN request ------------
########################################################################################

async def source_negotiations_triggered_by_admin_command(vacancy_id: str) -> None:
    # TAGS: [resume_related]
    """Sources negotiations collection."""

    log_prefix = "source_negotiations_triggered_by_admin_command"

    try:
        logger.info(f"{log_prefix}: started. vacancy_id: {vacancy_id}")

        # ----- IDENTIFY USER and pull required data from records -----
        
        manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
        access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")

        # ----- IMPORTANT: do not check if NEGOTIATIONS COLLECTION file exists, we update it every time -----

        # ----- PULL COLLECTIONS of negotiations and save it to file -----

        #Define what employer_state to use for pulling the collection
        employer_state = EMPLOYER_STATE_RESPONSE

        #Get collection of negotiations data for the target collection status "response"
        negotiations_collection_data = get_negotiations_collection_with_status_response(
            access_token=access_token,
            vacancy_id=vacancy_id,
        )

        # Persist negotiations collection to a timestamped JSON file under users_data/negotiations
        negotiations_dir = get_data_subdirectory_path(subdirectory_name="negotiations")
        if negotiations_dir is None:
            raise ValueError(f"{log_prefix}: negotiations data directory not found")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_name = f"negotiation_collection_{vacancy_id}_time_{timestamp}.json"
        file_path = get_data_subdirectory_path(subdirectory_name="negotiations") / file_name

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(negotiations_collection_data, f, ensure_ascii=False, indent=2)
            logger.info(f"{log_prefix}: negotiations collection saved to {file_path}")
        except Exception as file_err:
            logger.error(f"{log_prefix}: Failed to save negotiations collection to file {file_path}: {file_err}", exc_info=True)
            # Re-raise to make sure admin sees the failure
            raise

        # Parse and persist negotiations into the database
        await parse_negotiations_collection_to_db(
            vacancy_id=vacancy_id,
            negotiations_json=negotiations_collection_data,
        )

        logger.info(f"{log_prefix}: successfully completed for vacancy_id: {vacancy_id}")
    except Exception as e:
        logger.error(f"{log_prefix}: Failed to source negotiations for vacancy_id {vacancy_id}: {e}", exc_info=True)
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


async def send_tg_link_to_applicant_and_change_employer_state_triggered_by_admin_command(negotiation_id: str) -> None:
    # TAGS: [resume_related]

    log_prefix = "send_tg_link_to_applicant_and_change_employer_state_triggered_by_admin_command"
    logger.info(f"{log_prefix}: started. negotiation_id: {negotiation_id}")

    """Sources negotiations collection."""
    
    try:
        logger.info(f"{log_prefix}: started. negotiation_id: {negotiation_id}")

        send_message_to_applicant_command(negotiation_id=negotiation_id)
        change_employer_state_command(negotiation_id=negotiation_id)
        

        logger.info(f"{log_prefix}: successfully completed for negotiation_id: {negotiation_id}")
    except Exception as e:
        logger.error(f"{log_prefix}: Failed to send message to applicant for negotiation_id {negotiation_id}: {e}", exc_info=True)
        raise


async def send_message_to_applicant_command(negotiation_id: str) -> None:
    # TAGS: [resume_related]
    """Sends message to applicant. Triggers 'change_employer_state_command'."""
    

    log_prefix = "send_message_to_applicant_command"
    logger.info(f"{log_prefix}: started. negotiation_id: {negotiation_id}")

    # ----- IDENTIFY USER and pull required data from records -----
    
    vacancy_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="vacancy_id")
    manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
    access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")

    tg_link = create_tg_bot_link_for_applicant(negotiation_id=negotiation_id)
    negotiation_message_text = APPLICANT_MESSAGE_TEXT_WITHOUT_LINK + f"{tg_link}"
    try:
        send_negotiation_message(access_token=access_token, negotiation_id=negotiation_id, user_message=negotiation_message_text)
        logger.info(f"{log_prefix}: Message to applicant for negotiation ID: {negotiation_id} has been successfully sent")
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="link_to_tg_bot_sent", new_value=True)
        current_time = datetime.now(timezone.utc).isoformat()
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="link_to_tg_bot_sent_time", new_value=current_time)
    except Exception as send_err:
        logger.error(f"{log_prefix}: Failed to send message for negotiation ID {negotiation_id}: {send_err}", exc_info=True)
        # stop method execution in this case, because no need to update resume_records and negotiations status
        return


async def change_employer_state_command(negotiation_id: str) -> None:
    # TAGS: [resume_related]
    """Trigger send message to applicant command handler - allows users to send message to applicant."""

    log_prefix = "change_employer_state_command"
    logger.info(f"{log_prefix}: started. negotiation_id: {negotiation_id}")
    
    # ----- IDENTIFY USER and pull required data from records -----
        
    vacancy_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="vacancy_id")
    manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
    access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")

   # ----- CHANGE EMPLOYER STATE  -----

    #await update.message.reply_text(f"Изменяю статус приглашения кандидата на {NEW_EMPLOYER_STATE}...")
    logger.debug(f"{log_prefix}: negotiation ID: {negotiation_id} to {EMPLOYER_STATE_CONSIDER}")
    try:
        change_negotiation_collection_status_to_consider(
            access_token=access_token,
            negotiation_id=negotiation_id
        )
        logger.info(f"{log_prefix}: Collection status of negotiation ID: {negotiation_id} has been successfully changed to {EMPLOYER_STATE_CONSIDER}")
    except Exception as status_err:
        logger.error(f"{log_prefix}: Failed to change collection status for negotiation ID {negotiation_id}: {status_err}", exc_info=True)


async def source_resume_triggered_by_admin_command(negotiation_id: str) -> None:
    # TAGS: [resume_related]
    """Sources resumes from hh."""
    func_name = "source_resume_triggered_by_admin_command"
    log_prefix = f"{func_name}. Arguments {negotiation_id}"
    
    logger.info(f"{log_prefix}: started")

    try:
        
        # ----- IDENTIFY USER and pull required data from records -----
        err_msg = None
        vacancy_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="vacancy_id")
        if vacancy_id is None: err_msg = f"vacancy_id"
        manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
        if manager_id is None: err_msg = f"manager_id"
        access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")
        if access_token is None: err_msg = f"access_token"            
        resume_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_id")
        if resume_id is None: err_msg = f"resume_id"
        if err_msg:
            raise ValueError(f"{log_prefix}: {err_msg} not found in database")

        
        # ----- DOWNLOAD RESUMES from HH.ru to "new" resumes -----

        #Download resumes from HH.ru and save to file
        
        resume_data = get_resume_info(access_token=access_token, resume_id=resume_id)
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_json", new_value=resume_data)
        logger.debug(f"{log_prefix}: downloaded resume data to database")

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
            logger.warning(f"{log_prefix}: No phone found in resume data")
        if not email:
            logger.debug(f"{log_prefix}: No email found in resume data")


        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="hh_first_name", new_value=first_name)    
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="hh_last_name", new_value=last_name)
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="hh_phone", new_value=phone)
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="hh_email", new_value=email)

        logger.debug(f"{log_prefix}: updated resume details in database")
 
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        raise


async def analyze_resume_triggered_by_admin_command(negotiation_id: str) -> None:
    # TAGS: [resume_related]
    """Analyzes resume with AI. 
    Sorts resumes into "passed" or "failed" directories based on the final score. 
    Triggers 'send_message_to_applicants_command' and 'change_employer_state_command' for each resume.
    Does not trigger any other commands once done.
    """
    
    func_name = "analyze_resume_triggered_by_admin_command"
    log_prefix = f"{func_name}. Arguments {negotiation_id}"
    
    logger.info(f"{log_prefix}: started")

    try:
        
        # ----- IDENTIFY USER and pull required data from records -----
        err_msg = None
        vacancy_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="vacancy_id")
        if vacancy_id is None: err_msg = f"vacancy_id"
        manager_id = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="manager_id")
        if manager_id is None: err_msg = f"manager_id"
        access_token = get_column_value_by_field(db_model=Managers, search_field_name="id", search_value=manager_id, target_field_name="access_token")
        if access_token is None: err_msg = f"access_token"            
        resume_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_id")
        if resume_id is None: err_msg = f"resume_id"
        
        resume_json = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_json")
        if resume_json is None: err_msg = f"resume_json"
        vacancy_description = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="description_json")
        if vacancy_description is None: err_msg = f"vacancy_description"
        sourcing_criterias = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="sourcing_criterias_json")
        if sourcing_criterias is None: err_msg = f"sourcing_criterias"

        if err_msg:
            raise ValueError(f"{log_prefix}: {err_msg} not found in database")

        # ----- QUEUE RESUMES for AI ANALYSIS -----
        
        # Add AI analysis task to queue
        await ai_task_queue.put(
            resume_analysis_from_ai_to_user_sort_resume,
            negotiation_id,
            vacancy_description,
            sourcing_criterias,
            resume_id,
            resume_json,
            task_id=f"resume_analysis_{negotiation_id}"
        )
        logger.info(f"{log_prefix}: Added resume to analysis queue.")
    except Exception as e:
        logger.error(f"{log_prefix}: Failed to queue resume analysis: {e}", exc_info=True)
        raise
   


async def resume_analysis_from_ai_to_user_sort_resume(
    negotiation_id: str,
    vacancy_description: dict,
    sourcing_criterias: dict,
    resume_json: dict,
    resume_analysis_prompt: str,
    ) -> None:
    """
    Wrapper function to process resume analysis result.
    This function is executed through TaskQueue.
    """

    func_name = "resume_analysis_from_ai_to_user_sort_resume"
    log_prefix = f"{func_name}. Arguments: {negotiation_id}"
    
    logger.info(f"{log_prefix}: started")

    try:
        # Call AI analyzer
        ai_analysis_result = analyze_resume_with_ai(
            vacancy_description=vacancy_description,
            sourcing_criterias=sourcing_criterias,
            resume_data=resume_json,
            prompt_resume_analysis_text=resume_analysis_prompt
        )
        
        # Update resume records with AI analysis results
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_ai_analysis", new_value=ai_analysis_result)
        logger.debug(f"{log_prefix}: updated resume ai analysis in database")

        resume_ai_score = str(ai_analysis_result.get("final_score", 0))
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_ai_score", new_value=resume_ai_score)
        logger.debug(f"{log_prefix}: updated resume ai score in database")

        # Sort resume based on final score
        resume_ai_score = int(ai_analysis_result.get("final_score", 0))
        if resume_ai_score >= RESUME_PASSED_SCORE:
            new_status = "passed"
        else:
            new_status = "failed"

        resume_ai_score_str = str(resume_ai_score)
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_sorting_status", new_value=new_status)
        logger.debug(f"{log_prefix}: updated resume sorting status in database")
        update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="resume_ai_score", new_value=resume_ai_score_str)
        logger.debug(f"{log_prefix}: updated resume ai score in database")

    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        raise


async def send_recommendation_text_to_specified_user(whom_to_send: str, negotiation_id: str, application: Application) -> None:
    
    func_name = "send_recommendation_text_to_specified_user"
    log_prefix = f"{func_name}. Arguments: {whom_to_send}, {negotiation_id}"
    logger.info(f"{log_prefix}: start")

    try:

        if not is_value_in_db(db_model=Negotiations, field_name="id", value=negotiation_id):
            raise ValueError(f"{log_prefix}: negotiation_id not found in database")

        recommendation_text = get_resume_recommendation_text_from_resume_records(negotiation_id=negotiation_id)
        if recommendation_text is None:
            raise ValueError(f"{log_prefix}: recommendation_text not found in database")

        if not application or not application.bot:
            raise ValueError(f"{log_prefix}: application or bot instance not provided")

        await application.bot.send_message(
            chat_id=int(whom_to_send),
            text=recommendation_text,
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"{log_prefix}: recommendation text has been successfully sent to user {whom_to_send}")
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        raise


async def send_recommendation_video_to_specified_user_without_questionnaire(whom_to_send: str, negotiation_id: str, application: Application) -> None:

    func_name = "send_recommendation_video_to_specified_user"
    log_prefix = f"{func_name}. Arguments: {whom_to_send}, {negotiation_id}"
    logger.info(f"{log_prefix}: start")

    try:
        if not is_value_in_db(db_model=Negotiations, field_name="id", value=negotiation_id):
            raise ValueError(f"{log_prefix}: negotiation_id not found in database")

        video_path = get_column_value_in_db(
            db_model=Negotiations,
            record_id=negotiation_id,
            field_name="video_path",
        )
        if not video_path:
            raise ValueError(f"{log_prefix}: video_path not found in database for negotiation {negotiation_id}")

        video_path_object = Path(video_path)
        if not video_path_object.exists():
            raise FileNotFoundError(f"{log_prefix}: video file does not exist at path {video_path_object}")

        if not application or not application.bot:
            raise ValueError(f"{log_prefix}: application or bot instance not provided")

        try:
            with open(video_path_object, "rb") as video_file:
                await application.bot.send_video(
                    chat_id=int(whom_to_send),
                    video=InputFile(video_file, filename=video_path_object.name),
                )
            logger.info(f"{log_prefix}: recommendation video has been successfully sent to user {whom_to_send}")
        except Exception as e:
            logger.error(f"{log_prefix}: Failed to send video to user {whom_to_send}: {e}", exc_info=True)
            raise
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        raise
    

async def send_recommendation_video_to_specified_user_with_questionnaire(whom_to_send: str, negotiation_id: str, application: Application) -> None:

    func_name = "send_recommendation_video_to_specified_user"
    log_prefix = f"{func_name}. Arguments: {whom_to_send}, {negotiation_id}"
    logger.info(f"{log_prefix}: start")

    try:
        if not is_value_in_db(db_model=Negotiations, field_name="id", value=negotiation_id):
            raise ValueError(f"{log_prefix}: negotiation_id not found in database")

        video_path = get_column_value_in_db(
            db_model=Negotiations,
            record_id=negotiation_id,
            field_name="video_path",
        )
        if not video_path:
            raise ValueError(f"{log_prefix}: video_path not found in database for negotiation {negotiation_id}")

        video_path_object = Path(video_path)
        if not video_path_object.exists():
            raise FileNotFoundError(f"{log_prefix}: video file does not exist at path {video_path_object}")

        if not application or not application.bot:
            raise ValueError(f"{log_prefix}: application or bot instance not provided")

        try:
            # Send video
            with open(video_path_object, "rb") as video_file:
                await application.bot.send_video(
                    chat_id=int(whom_to_send),
                    video=InputFile(video_file, filename=video_path_object.name),
                )
            logger.info(f"{log_prefix}: recommendation video has been successfully sent to user {whom_to_send}")

            current_time = datetime.now(timezone.utc).isoformat()
            update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"resume_recommended": True, "resume_recommended_time": current_time})
            logger.debug(f"{log_prefix}: updated resume recommended status and time in database")

            # Ask a question with actions using generic questionnaire helper
            # callback_data format will be:
            #   "<INVITE_TO_INTERVIEW_CALLBACK_PREFIX>:<action>:<negotiation_id>"
            options = [
                ("Позвать кандидата", f"invite:{negotiation_id}"),
                ("Отказать кандидату", f"reject:{negotiation_id}"),
            ]

            await ask_single_question_from_application(
                application=application,
                target_user_id=int(whom_to_send),
                question_text="Хотите пригласить кандидата на интервью?",
                options=options,
                callback_prefix=INVITE_TO_INTERVIEW_CALLBACK_PREFIX,
            )
            logger.info(f"{log_prefix}: action question sent to user {whom_to_send}")

        except Exception as e:
            logger.error(f"{log_prefix}: Failed to send video or question to user {whom_to_send}: {e}", exc_info=True)
            raise
    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        raise


async def handle_answer_invite_to_interview_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [recommendation_related] 
    """Handle invite to interview button click. Sends notification to admin.
    Sends notification to admin if fails"""
    

    log_prefix = "handle_answer_invite_to_interview_button"
    logger.info(f"{log_prefix}: start")

    try:
        if not update.callback_query:
            return

        # ----- IDENTIFY USER and pull required data from callback -----
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

        # Use generic single-question helper from questionnaire_service
        answer_key = await single_question_callback_handler(
            update=update,
            context=context,
            callback_prefix=INVITE_TO_INTERVIEW_CALLBACK_PREFIX,
        )
        logger.debug(f"{log_prefix}: answer_key: {answer_key}")

        if not answer_key:
            raise ValueError("Empty answer_key for invite to interview question")

        # ----- EXTRACT DATA from answer_key -----

        # answer_key format: "<action>:<negotiation_id>"
        try:
            action, negotiation_id = answer_key.split(":", 1)
            logger.debug(f"{log_prefix}: action: {action}, negotiation_id: {negotiation_id}")
        except ValueError:
            raise ValueError(f"Invalid answer_key format for invite to interview: {answer_key}")

        vacancy_id = get_column_value_in_db(
            db_model=Negotiations,
            record_id=negotiation_id,
            field_name="vacancy_id",
        )
        if not vacancy_id:
            raise ValueError(f"{log_prefix}: vacancy_id not found in database for negotiation {negotiation_id}")
        vacancy_name = get_column_value_in_db(
            db_model=Vacancies,
            record_id=vacancy_id,
            field_name="name",
        )
        if not vacancy_name:
            raise ValueError(f"{log_prefix}: vacancy_name not found in database for vacancy {vacancy_id}")
        manager_id = get_column_value_in_db(
            db_model=Vacancies,
            record_id=vacancy_id,
            field_name="manager_id",
        )
        if not manager_id:
            raise ValueError(f"{log_prefix}: manager_id not found in database for negotiation {negotiation_id}")

        current_time = datetime.now(timezone.utc).isoformat()

        # Build admin message based on user action
        if action == "invite":
            
            update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"resume_accepted": True, "resume_decision_time": current_time})

            user_msg = f"✅ Свяжемся с вами, чтобы назначить время интервью."

            admin_message = (
                f"📞 Пользователь {manager_id}.\n"
                f"хочет пригласить кандидата {negotiation_id} на интервью.\n"
                f"Вакансия: {vacancy_id}: {vacancy_name}.\n"
            )

        elif action == "reject":

            update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"resume_accepted": False, "resume_decision_time": current_time})
            logger.debug(f"{log_prefix}: updated resume recommended status and time in database")

            user_msg = f"Хорошо, приглашать этого кандидата не будем.\nРасскажите, почему вы не согласны с критериями отбора кандидатов.\n\nПришлите аудио-запись прямо в этот чат, пожалуйста.\n\nЯ учту ваши пожелания и подправлю критерии отбора кандидатов."

            admin_message = (
                f"📞 Пользователь {manager_id}.\n"
                f"решил ОТКАЗАТЬ кандидату {negotiation_id}.\n"
                f"Вакансия: {vacancy_id}: {vacancy_name}.\n"
                f"Ждем обратную связь по аудио"
            )
        else:

            user_msg = FAIL_TECHNICAL_SUPPORT_TEXT
            admin_message = f"😎 User {bot_user_id} something went wrong with invite to interview!"

            raise ValueError(f"Unknown action '{action}' in invite to interview flow")

        await send_message_to_user(update, context, text=user_msg)
        # ----- SEND NOTIFICATION TO ADMIN & UPDATE STATE -----
        if context.application:
            await send_message_to_admin(application=context.application, text=admin_message)
        else:
            raise ValueError(f"{log_prefix}: application instance not provided")

    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error {log_prefix}: {e}\nUser ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )



########################################################################################
# ------------ MAIN MENU related commands ------------
########################################################################################

async def user_status(bot_user_id: str) -> dict:
    
    log_prefix = "user_status"
    logger.info(f"{log_prefix}: start")
    logger.info(f"{log_prefix}: bot_user_id: {bot_user_id}")

    status_dict = {}
    status_dict["bot_authorization"] = is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id)
    status_dict["privacy_policy_confirmation"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed")
    status_dict["hh_authorization"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="access_token_recieved")
    status_dict["vacancy_selection"] = is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_selected")

    vacancy_id = get_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="id")
    logger.info(f"{log_prefix}: vacancy_id: {vacancy_id}")
    status_dict["vacancy_video_received"] = is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="video_received")
    status_dict["sourcing_criterias_confirmed"] = is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="sourcing_criterias_confirmed")


    logger.info(f"{log_prefix}: status_dict: {status_dict}")

    return status_dict


async def build_user_status_text(bot_user_id: str, status_dict: dict) -> str:

    status_to_text_transcription = {
        "bot_authorization": " Авторизация в боте.",
        "privacy_policy_confirmation": " Согласие на обработку перс. данных.",
        "hh_authorization": " Авторизация в HeadHunter.",
        "vacancy_selection": " Выбор вакансии.",
        "vacancy_video_received": " Приветственное видео.",
        "sourcing_criterias_confirmed": " Критерии отбора согласованы.",
    }
    status_images = {True: "✅", False: "❌"}
    user_status_text = "Статус пользователя:\n"
    for key, value_bool in status_dict.items():
        status_image = status_images[value_bool]
        status_text = status_to_text_transcription[key]
        user_status_text += f"{status_image}{status_text}\n"

    vacancy_id = get_column_value_in_db(db_model=Managers, record_id=bot_user_id, field_name="vacancy_id")
    if vacancy_id: # not None
        vacancy_name = get_column_value_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="name")
        if vacancy_name: # not None
            user_status_text += f"\nВакансия в работе: {vacancy_name}.\n"
    return user_status_text


async def show_chat_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    # ----- IDENTIFY USER and pull required data from records -----
    
    log_prefix = "show_chat_menu_command"
    logger.info(f"{log_prefix}: start")

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
    status_dict = await user_status(bot_user_id=bot_user_id)
    status_text = await build_user_status_text(bot_user_id=bot_user_id, status_dict=status_dict)

    status_to_button_transcription = {
        "bot_authorization": "Авторизация в боте",
        "privacy_policy_confirmation": "Обработка перс. данных",
        "hh_authorization": "Авторизоваться на HeadHunter",
        "vacancy_selection": "Выбрать вакансию",
        "vacancy_video_received": "Записать приветственное видео",
    }
    answer_options = []
    for key, value_bool in status_dict.items():
        # add button only if status is False (not completed)
        if key in status_to_button_transcription and value_bool == False:
            answer_options.append((status_to_button_transcription[key], "menu_action:" + key))
    logger.debug(f"{log_prefix}: answer options for chat menu: {answer_options}")

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


    log_prefix = "handle_chat_menu_action"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------
    
    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)
    
    if not selected_callback_code:
        logger.warning(f"{log_prefix}: no callback_code received from handle_answer")
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
        logger.warning(f"{log_prefix}: could not find button text for callback_code '{selected_callback_code}'. Available options: {chat_menu_action_options}")
        if update.callback_query and update.callback_query.message:
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return
    
    # ----- EXTRACT ACTION from callback_data and route to appropriate command -----
    
    # Extract action from callback_data (format: "menu_action:action_name")
    action = get_decision_status_from_selected_callback_code(selected_callback_code=selected_callback_code)
    logger.debug(f"{log_prefix}: extracted action from callback_code '{selected_callback_code}': '{action}'")
 

    if action == "bot_authorization":
        await start_command(update=update, context=context)
    elif action == "privacy_policy_confirmation" or action == "privacy_policy":
        await ask_privacy_policy_confirmation_command(update=update, context=context)
    elif action == "hh_authorization":
        await hh_authorization_command(update=update, context=context)
    elif action == "vacancy_selection":
        await select_vacancy_command(update=update, context=context)
    elif action == "vacancy_video_received":
        await ask_to_record_video_command(update=update, context=context)
    else:
        logger.warning(f"{log_prefix}: unknown action '{action}' from callback_code '{selected_callback_code}'. Available actions: bot_authorization, privacy_policy_confirmation, privacy_policy, hh_authorization, hh_auth, select_vacancy, record_video, get_recommendations")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


async def handle_feedback_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle feedback button click. Sets flag to wait for user feedback message."""
        
    log_prefix = "handle_feedback_button_click"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----
    
    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

    # ----- SET WAITING FOR FEEDBACK FLAG TO TRUE -----

    # Reset flag and allow new feedback (user can click button again to send new message)
    context.user_data["waiting_for_feedback"] = True
    await send_message_to_user(update, context, text=FEEDBACK_REQUEST_TEXT)


async def handle_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle feedback message from user. Forwards it to admin."""
    
    log_prefix = "handle_feedback_message"
    logger.info(f"{log_prefix}: start")

    # ----- CHECK IF MESSAGE IS NOT EMPTY -----

    if not update.message:
        return
    
    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
    
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

            try:
                if is_value_in_db(db_model=Managers, field_name="id", value=bot_user_id):
                    username = get_column_value_in_db(db_model=Managers, field_name="username", value=bot_user_id)
                    first_name = get_column_value_in_db(db_model=Managers, field_name="first_name", value=bot_user_id)
                    last_name = get_column_value_in_db(db_model=Managers, field_name="last_name", value=bot_user_id)
                    user_info = f"Пользователь: ID: {bot_user_id}, @{username}, {first_name} {last_name})"
                else:
                    user_info = f"Пользователь ID: {bot_user_id}, не найден в records."

            except Exception as e:
                logger.error(f"{log_prefix} Failed: {e}")
                user_info = f"Пользователь ID: {bot_user_id}"
            
            admin_message = f"⚠️ User feedback from {bot_user_id}\n\n{user_info}\n\nMessage:\n{feedback_text}"
            await send_message_to_admin(
                application=context.application,
                text=admin_message
            )
            # Confirm to user
            await send_message_to_user(update, context, text=FEEDBACK_SENT_TEXT)
        else:
            logger.error(f"{log_prefix}: cannot send feedback to admin: application not available")
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
    except Exception as e:
        logger.error(f"{log_prefix}: failed to send feedback to admin: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


async def handle_feedback_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle non-text messages when waiting for feedback (reject audio, images, etc.)."""
    

    log_prefix = "handle_feedback_non_text_message"
    logger.info(f"{log_prefix}: start")

    if not update.message:
        return
    
    # Check if we're waiting for feedback
    if not context.user_data.get("waiting_for_feedback", False):
        return  # Not waiting for feedback, ignore this message
    
    # User sent non-text content (audio, image, document, etc.)
    await send_message_to_user(update, context, text=FEEDBACK_ONLY_TEXT_ALLOWED_TEXT)


async def handle_bottom_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom manager menu buttons."""

    log_prefix = "handle_bottom_menu_buttons"
    logger.info(f"{log_prefix}: start")

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
    application.add_handler(CallbackQueryHandler(handle_answer_select_vacancy, pattern=r"^vacancy_select:"))
    application.add_handler(CallbackQueryHandler(handle_answer_confrim_sending_video, pattern=r"^sending_video_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_answer_policy_confirmation, pattern=r"^privacy_policy_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_answer_sourcing_criterias_confirmation, pattern=r"^sourcing_criterias_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_chat_menu_action, pattern=r"^menu_action:"))
    application.add_handler(CallbackQueryHandler(handle_answer_invite_to_interview_button, pattern=r"^invite_to_interview:"))
    
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


