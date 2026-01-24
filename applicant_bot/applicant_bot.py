# TAGS: [admin], [user_related], [vacancy_related], [resume_related], [recommendation_related]

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
import os
import json
import re

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
"""
from services.video_service import (
    process_incoming_video,
    download_incoming_video_locally
)
"""
from shared_services.video_service import (
    process_incoming_video,
    download_incoming_video_locally
)

from services.status_validation_service import (
    is_applicant_in_applicant_bot_records,
    is_applicant_privacy_policy_confirmed,
    is_welcome_video_shown_to_applicant,
    is_resume_video_received,
    is_vacancy_exist,
)

from shared_services.data_service import (
    get_directory_for_video_from_managers,
    get_manager_user_id_from_applicant_bot_records,
    get_vacancy_id_from_applicant_bot_records,
    create_new_applicant_in_applicant_bot_records,
    update_applicant_bot_records_with_top_level_key,
    get_applicant_bot_records_file_path,
)

from shared_services.data_service import (
    get_decision_status_from_selected_callback_code,
    get_tg_user_data_attribute_from_update_object
)
"""
from services.questionnaire_service import (
    ask_question_with_options, 
    handle_answer,
    send_message_to_user,
    clear_all_unprocessed_keyboards
)
"""
from shared_services.questionnaire_service import (
    ask_question_with_options, 
    handle_answer,
    send_message_to_user,
    clear_all_unprocessed_keyboards
)

from shared_services.constants import *


########################################################
# ------------ APPLICANT FLOW STARTS HERE ------------ #
########################################################
# - setup user
# - ask privacy policy confirmation
# - handle answer privacy policy confirmation
# - show welcome video
# - ask to record video
# - handle answer video record request
# - send instructions to shoot video
# - ask confirm sending video
# - handle answer confirm sending video


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler. 
    Called from: 'start' button in main menu.
    Triggers: 1) setup new user 2) ask privacy policy confirmation
    """
    # ----- SETUP NEW USER and send welcome message -----

    # if existing user, setup_new_user_command will be skipped
    await setup_new_applicant_command(update=update, context=context)


async def setup_new_applicant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Setup new applicant user in system.
    Called from: 'start_command'.
    Triggers: nothing.
    Sends notification to admin if fails"""

    try:
        # ------ COLLECT NEW USER ID and CREATE record and user directory if needed ------

        applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"setup_new_applicant_command started. applicant_user_id: {applicant_user_id}")

        if not is_applicant_in_applicant_bot_records(applicant_record_id=applicant_user_id):
            create_new_applicant_in_applicant_bot_records(applicant_record_id=applicant_user_id)
        else:
            logger.debug(f"Applicant {applicant_user_id} already in applicant bot records")

        # ------ ENRICH APPLICANT RECORDS with NEW USER DATA from Telegram user attributes ------

        tg_user_attributes = ["username", "first_name", "last_name"]
        for item in tg_user_attributes:
            tg_user_attribute_value = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute=item)
            update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key=item, value=tg_user_attribute_value)
        logger.debug(f"{applicant_user_id} in user records is updated with telegram user attributes.")

        # ----- EXTRACT PAYLOAD from Telegram start command -----
        # Link structure: https://t.me/{BOT_FOR_APPLICANTS_USERNAME}?start={manager_user_id}_{vacancy_id}_{resume_id}"
        
        payload = None
        if update.message and update.message.text:
            logger.debug(f"update.message.text: {update.message.text}")
            # Telegram sends /start PAYLOAD as the message text
            text_parts = update.message.text.split(maxsplit=1)
            logger.debug(f"text_parts: {text_parts}")
            if len(text_parts) > 1:
                payload = text_parts[1]  # Get the payload, which is a second part after "/start"
        
        # ----- PARSE PAYLOAD and EXTRACT resume_id and vacancy_id -----
        
        if payload:
            # Parse payload format: "resume_id:vacancy_id"
            payload_parts = payload.split("_")
            logger.debug(f"payload_parts: {payload_parts}")
            if len(payload_parts) == 3:
                manager_user_id = payload_parts[0]
                vacancy_id = payload_parts[1]
                resume_id = payload_parts[2]
                logger.debug(f"Parsed payload - resume_id: {resume_id}, vacancy_id: {vacancy_id}")

                # ----- CHECK IF SUCH VACANCY exists in vacancy_records and STOP if not -----

                if not is_vacancy_exist(user_record_id=manager_user_id, vacancy_id=vacancy_id):
                    logger.debug(f"Vacancy {vacancy_id} not found for manager {manager_user_id}")
                    await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
                    return

                # ----- UPDATE APPLICANT BOT RECORDS with PAYLOAD DATA -----

                update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="manager_user_id", value=manager_user_id)
                update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="vacancy_id", value=vacancy_id)
                update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="resume_id", value=resume_id)

                logger.debug(f"Applicant bot records updated for applicant_user_id: {applicant_user_id} with payload - manager_user_id: {manager_user_id}, vacancy_id: {vacancy_id}, resume_id: {resume_id}.")

                # ----- ASK PRIVACY POLICY CONFIRMATION -----

                # if already confirmed, second confirmation will be skipped
                await ask_privacy_policy_confirmation_command(update=update, context=context)

                # IMPORTANT: ALL OTHER COMMANDS will be triggered from functions if PRIVACY POLICY is confirmed

            else:
                logger.warning(f"Invalid payload format: {payload}")
                await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
        else:
            logger.debug("No payload found in start command")
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
    except Exception as e:
        logger.error(f"Failed to setup new applicant: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error setting up new applicant: {e}\nUser ID: {applicant_user_id if 'applicant_user_id' in locals() else 'unknown'}"
            )


async def ask_privacy_policy_confirmation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask privacy policy confirmation command handler. 
    Called from: 'setup_new_applicant_command'.
    Triggers: nothing."""

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"ask_privacy_policy_confirmation_command started. applicant_user_id: {applicant_user_id}")
    manager_user_id = get_manager_user_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)
    vacancy_id = get_vacancy_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)

    # ----- CHECK IF SUCH VACANCY exists and STOP if not -----

    if not is_vacancy_exist(user_record_id=manager_user_id, vacancy_id=vacancy_id):
        logger.debug(f"Vacancy {vacancy_id} not found for manager {manager_user_id}")
        await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
        return

    # ----- CHECK IF PRIVACY POLICY is already confirmed and STOP if it is -----

    if is_applicant_privacy_policy_confirmed(applicant_record_id=applicant_user_id):
        await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)
        return

    # Build options (which will be tuples of (button_text, callback_data))
    answer_options = [
        ("Ознакомлен, даю согласие на обработку.", "privacy_policy_confirmation:yes"),
        ("Не даю согласие на обрабоку.", "privacy_policy_confirmation:no"),
    ]
    # Store button_text and callback_data options in context to use it later for button _text identification as this is not stored in "update.callback_query" object
    context.user_data["privacy_policy_confirmation_answer_options"] = answer_options
    await ask_question_with_options(update, context, question_text=PRIVACY_POLICY_CONFIRMATION_TEXT_APPLICANT, answer_options=answer_options)


async def handle_answer_policy_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click, updates confirmation status in user records.
    Called from: nowhere.
    Triggers commands:
    - If user agrees to process personal data, triggers 'show_welcome_video_command'.
    - If user does not agree to process personal data, informs user how to give consent."""

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_policy_confirmation started. applicant_user_id: {applicant_user_id}")
    
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
        update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="privacy_policy_confirmed", value=privacy_policy_confirmation_user_decision)
        current_time = datetime.now(timezone.utc).isoformat()
        update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="privacy_policy_confirmation_time", value=current_time)
        logger.debug(f"Applicant privacy policy confirmation user decision: {privacy_policy_confirmation_user_decision} at {current_time}")

        # ----- IF USER CHOSE "YES" download video to local storage -----

        if privacy_policy_confirmation_user_decision == "yes":
            await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)
            
        # ----- SEND AUTHENTICATION REQUEST and wait for user to authorize -----
    
            # if already authorized, second authorization will be skipped
            await show_welcome_video_command(update=update, context=context)
        
        # ----- IF USER CHOSE "NO" inform user about need to give consent to process personal data -----
        
        else:
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)


async def show_welcome_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Show welcome video command. 
    Called from: 'handle_answer_policy_confirmation'.
    Triggers: 'ask_to_record_video_command'."""

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"show_welcome_video_command started. applicant_user_id: {applicant_user_id}")
    manager_user_id = get_manager_user_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)
    vacancy_id = get_vacancy_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)

    # ----- CHECK IF SUCH VACANCY exists and STOP if not -----

    if not is_vacancy_exist(user_record_id=manager_user_id, vacancy_id=vacancy_id):
        logger.debug(f"Vacancy {vacancy_id} not found for manager {manager_user_id}")
        await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
        return

    # ----- CHECK IF WELCOME VIDEO is already shown and STOP if it is -----

    if is_welcome_video_shown_to_applicant(applicant_record_id=applicant_user_id):
        await send_message_to_user(update, context, text=SUCCESS_TO_GET_WELCOME_VIDEO_TEXT)
        return

    await send_message_to_user(update, context, text=INFO_UPLOADING_WELCOME_VIDEO_TEXT)

    # ----- GET WELCOME VIDEO from managers -----

    managers_video_data_dir = get_directory_for_video_from_managers(user_record_id=manager_user_id, vacancy_id=vacancy_id)
    if managers_video_data_dir is None:
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return
    welcome_video_file_paths = list(managers_video_data_dir.glob("*.mp4"))
    if not welcome_video_file_paths:
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return
    welcome_video_file_path = welcome_video_file_paths[0]


    # ----- SEND WELCOME VIDEO to applicant -----
    
    await context.application.bot.send_video(chat_id=int(applicant_user_id), video=str(welcome_video_file_path))
    update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="welcome_video_shown", value="yes")
    await asyncio.sleep(1)
    
    await ask_to_record_video_command(update=update, context=context)


async def ask_to_record_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask to record video command. 
    Called from: 'show_welcome_video_command'.
    Triggers: nothing."""

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"ask_to_record_video_command started. applicant_user_id: {applicant_user_id}")
    manager_user_id = get_manager_user_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)
    vacancy_id = get_vacancy_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)


    # ----- CHECK IF SUCH VACANCY exists and STOP if not -----

    if not is_vacancy_exist(user_record_id=manager_user_id, vacancy_id=vacancy_id):
        logger.debug(f"Vacancy {vacancy_id} not found for manager {manager_user_id}")
        await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
        return


    if is_resume_video_received(applicant_record_id=applicant_user_id):
        await send_message_to_user(update, context, text=INFO_VIDEO_ALREADY_SAVED_TEXT)
        return

    # ----- CHECK MUST CONDITIONS are met and STOP if not -----

    if not is_applicant_privacy_policy_confirmed(applicant_record_id=applicant_user_id):
        await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
        return


    # ----- ASK USER IF WANTS TO RECORD or drop welcome video for the selected vacancy -----

    # Build options (which will be tuples of (button_text, callback_data))
    answer_options = [
        ("Хочу записать или загрузить видео", "record_video_request:yes"), 
        ("Продолжить без видео", "record_video_request:no")
        ]
    # Store button_text and callback_data options in context to use it later for button _text identification as this is not stored in "update.callback_query" object
    context.user_data["video_record_request_options"] = answer_options
    await ask_question_with_options(update, context, question_text=WELCOME_VIDEO_RECORD_REQUEST_TEXT_APPLICANT, answer_options=answer_options)
    logger.debug(f"Record applicant's video request question with options asked")


async def handle_answer_video_record_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle button click. 
    Called from: nowhere.
    Triggers commands:
    - If user agrees to record, sends instructions to shoot video command'.
    - If user does not agree to record, triggers 'read_vacancy_description_command'.

    This is called AUTOMATICALLY by Telegram when a button is clicked (via CallbackQueryHandler).

    Note: Bot knows which user clicked because:
    - update.effective_user.id contains the user ID (works for both messages and callbacks)
    - context.user_data is automatically isolated per user by python-telegram-bot framework
    """

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_answer_video_record_request started. applicant_user_id: {applicant_user_id}")
    
    # ------- UNDERSTAND WHAT BUTTON was clicked and get "callback_data" from it -------

    # Get the "callback_data" extracted from "update.callback_query" object created once button clicked
    selected_callback_code = await handle_answer(update, context)
    
    logger.debug(f"Callback code found: {selected_callback_code}")

    # ----- UNDERSTAND TEXT on clicked buttton from option taken from context -----

    if not selected_callback_code:
        if update.callback_query and update.callback_query.message:
            logger.debug(f"No callback code found in update.callback_query.message")
            await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
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
        # Update user records with selected vacancy data
        update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="agreed_to_record_resume_video", value=video_record_request_user_decision)
        logger.debug(f"User records updated")
    
    # ----- PROGRESS THROUGH THE VIDEO FLOW BASED ON THE USER'S RESPONSE -----

    # ----- IF USER CHOSE "YES" send instructions to shoot video -----

    if video_record_request_user_decision == "yes":
        logger.debug(f"Video record request user decision is yes")
        await send_message_to_user(update, context, text=INSTRUCTIONS_TO_SHOOT_VIDEO_TEXT_APPLICANT)
        
        # ----- NOW HANDLER LISTENING FOR VIDEO from user -----

        # this line just for info that handler will work from "create_applicant_application" method in file "applicant_bot.py"
        # once handler will be triggered, it will trigget "handle_video" method from file "services.video_service.py"

    # ----- IF USER CHOSE "NO" inform user about need to continue without video -----

    else:
        await send_message_to_user(update, context, text=CONTINUE_WITHIOUT_APPLICANT_VIDEO_TEXT)


async def ask_confirm_sending_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask confirm sending video command handler. 
    Called from: 'process_incoming_video' from file "services.video_service.py".
    Triggers: nothing. """

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"ask_confirm_sending_video_command started. applicant_user_id: {applicant_user_id}")

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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    
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
            applicant_user_id=applicant_user_id,
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



##########################################
# ------------ ADMIN COMMANDS ------------``
##########################################


async def send_message_to_admin(application: Application, text: str, parse_mode: Optional[ParseMode] = None) -> None:
    #TAGS: [admin]

    # ----- GET ADMIN ID from environment variables -----
    
    admin_id = os.getenv("ADMIN_ID", "")
    if not admin_id:
        logger.error("ADMIN_ID environment variable is not set. Cannot send admin notification.")
        return
    
    # ----- SEND NOTIFICATION to admin -----
    
    try:
        if application and application.bot:
            await application.bot.send_message(
                chat_id=int(admin_id),
                text=text,
                parse_mode=parse_mode
            )
            logger.debug(f"Admin notification sent successfully to admin_id: {admin_id}")
        else:
            logger.warning("Cannot send admin notification: application or bot instance not available")
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}", exc_info=True)


async def admin_get_list_of_applicants_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to list all applicant IDs from applicant records.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

    admin_id = os.getenv("ADMIN_ID", "")
    if not admin_id or bot_user_id != admin_id:
        await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
        logger.error(f"Unauthorized for {bot_user_id}")
        return

    # ----- SEND LIST OF USERS IDs from records -----

    applicant_records_file_path = get_applicant_bot_records_file_path()
    with open(applicant_records_file_path, "r", encoding="utf-8") as f:
        applicant_records = json.load(f)
    applicant_user_ids = list(applicant_records.keys())

    await send_message_to_user(update, context, text=f"📋 List of applicant user IDs: {applicant_user_ids}")


async def admin_send_message_to_applicant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to send a message to a specific applicant by user_id (chat_id).
    Usage: /admin_send_message_to_applicant <user_id> <message_text>
    Usage example: /admin_send_message_to_applicant 7853115214 Привет! Как дела?
    Sends notification to admin if fails
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        
    
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        if not context.args or len(context.args) < 2:
            await send_message_to_user(
                update, 
                context, 
                text="⚠️ Неверный формат команды.\nИспользование: /admin_send_message_to_applicant <user_id> <текст_сообщения>"
            )
            return
        
        target_user_id = context.args[0]
        message_text = " ".join(context.args[1:])  # Join all remaining arguments as message text

        # ----- VALIDATE USER_ID -----

        try:
            target_user_id_int = int(target_user_id)
        except ValueError:
            await send_message_to_user(update, context, text=f"❌ Неверный формат user_id: {target_user_id}")
            return

        # ----- SEND MESSAGE TO USER -----

        if context.application and context.application.bot:
            try:
                await context.application.bot.send_message(
                    chat_id=target_user_id_int,
                    text=message_text
                )
                await send_message_to_user(update, context, text=f"✅ Сообщение отправлено пользователю {target_user_id}:\n'{message_text}'")
                logger.info(f"Admin {bot_user_id} sent message to user {target_user_id}: {message_text}")
            except Exception as send_err:
                error_msg = f"❌ Не удалось отправить сообщение пользователю {target_user_id}: {send_err}"
                await send_message_to_user(update, context, text=error_msg)
                logger.error(f"Failed to send message to user {target_user_id}: {send_err}", exc_info=True)
                raise
        else:
            raise ValueError("Application or bot instance not available")
    
    except Exception as e:
        logger.error(f"Failed to execute admin_send_message_to_applicant command: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error executing admin_send_message_to_user command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )



########################################################################################
# ------------ MAIN MENU related commands ------------
########################################################################################

async def user_status(applicant_user_id: str) -> dict:
    status_dict = {}
    status_dict["bot_authorization"] = is_applicant_in_applicant_bot_records(applicant_record_id=applicant_user_id)
    status_dict["privacy_policy_confirmation"] = is_applicant_privacy_policy_confirmed(applicant_record_id=applicant_user_id)
    status_dict["welcome_video_shown"] = is_welcome_video_shown_to_applicant(applicant_record_id=applicant_user_id)
    status_dict["resume_video_recorded"] = is_resume_video_received(applicant_record_id=applicant_user_id)
    return status_dict


async def build_user_status_text(status_dict: dict) -> str:

    status_to_text_transcription = {
        "bot_authorization": " Авторизация в боте.",
        "privacy_policy_confirmation": " Согласие на обработку перс. данных.",
        "welcome_video_shown": " Просмотр приветственного видео менеджера.",
        "resume_video_recorded": " Запись видео-визитки."
    }
    status_images = {True: "✅", False: "❌"}
    user_status_text = "Статус пользователя:\n"
    for key, value_bool in status_dict.items():
        status_image = status_images[value_bool]
        status_text = status_to_text_transcription[key]
        user_status_text += f"{status_image}{status_text}\n"
    return user_status_text


async def show_chat_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    # ----- IDENTIFY USER and pull required data from records -----
    
    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"show_chat_menu_command started. applicant_user_id: {applicant_user_id}")
    status_dict = await user_status(applicant_user_id=applicant_user_id)
    status_text = await build_user_status_text(status_dict=status_dict)

    status_to_button_transcription = {
        "bot_authorization": "Авторизация в боте",
        "privacy_policy_confirmation": "Обработка перс. данных",
        "welcome_video_shown": "Посмотреть приветственное видео менеджера",
        "resume_video_recorded": "Записать видео-визитку",
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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_chat_menu_action started. applicant_user_id: {applicant_user_id}")

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
    elif action == "privacy_policy_confirmation":
        await ask_privacy_policy_confirmation_command(update=update, context=context)
    elif action == "welcome_video_shown":
        await show_welcome_video_command(update=update, context=context)
    elif action == "resume_video_recorded":
        await ask_to_record_video_command(update=update, context=context)
    else:
        logger.warning(f"Unknown action '{action}' from callback_code '{selected_callback_code}'. Available actions: bot_authorization, privacy_policy_confirmation, privacy_policy, hh_authorization, hh_auth, select_vacancy, record_video, get_recommendations")
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)


async def handle_feedback_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Handle feedback button click. Sets flag to wait for user feedback message."""

    # ----- IDENTIFY USER and pull required data from records -----

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_feedback_button_click started. applicant_user_id: {applicant_user_id}")

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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"handle_feedback_message started. applicant_user_id: {applicant_user_id}")
    
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
            applicant_records_file_path = get_applicant_bot_records_file_path()
            user_info = ""
            try:
                with open(applicant_records_file_path, "r", encoding="utf-8") as f:
                    applicant_records = json.load(f)
                    if is_applicant_in_applicant_bot_records(applicant_record_id=applicant_user_id):
                        manager_user_id = applicant_records[applicant_user_id].get("manager_user_id", "N/A")
                        vacancy_id = applicant_records[applicant_user_id].get("vacancy_id", "N/A")
                        resume_id = applicant_records[applicant_user_id].get("resume_id", "N/A")
                        username = applicant_records[applicant_user_id].get("username", "N/A")
                        first_name = applicant_records[applicant_user_id].get("first_name", "N/A")
                        last_name = applicant_records[applicant_user_id].get("last_name", "N/A")
                        user_info = (
                            f"Вакансия: менеджер ID {manager_user_id}, вакансия {vacancy_id}, резюме {resume_id})",
                            f"Соискатель: ID {applicant_user_id}, @{username}, {first_name} {last_name})"
                        )
                    else:
                        user_info = f"Пользователь ID: {applicant_user_id}, не найден в applicant_bot_records."
            except Exception as e:
                logger.error(f"Failed to get user info for feedback: {e}")
                user_info = f"Пользователь ID: {applicant_user_id}"
            
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


def create_applicant_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CallbackQueryHandler(handle_answer_video_record_request, pattern=r"^record_video_request:"))
    application.add_handler(CallbackQueryHandler(handle_answer_confrim_sending_video, pattern=r"^sending_video_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_answer_policy_confirmation, pattern=r"^privacy_policy_confirmation:"))
    application.add_handler(CallbackQueryHandler(handle_chat_menu_action, pattern=r"^menu_action:"))
    menu_buttons_pattern = f"^({re.escape(BTN_MENU)}|{re.escape(BTN_FEEDBACK)})$"
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(menu_buttons_pattern), handle_bottom_menu_buttons)
    )
    # Handler for feedback messages (text only, when waiting_for_feedback flag is set)
    # This handler must be added AFTER menu buttons handler to avoid conflicts
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.Regex(menu_buttons_pattern), handle_feedback_message)
    )
    # Handler for non-text messages when waiting for feedback (reject audio, images, etc.)
    # This must be added BEFORE video handler so it can check the flag first
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.TEXT & ~(filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO),
            handle_feedback_non_text_message
        )
    )
    # this handler listens to all video messages and passes them to the video service - 
    # "MessageHandler" works specifically with messages, not callback queries
    # "filters.ALL & (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO)" means handler will work only with video messages
    # when handler is triggered, it calls the defined lambda function
    application.add_handler(MessageHandler(filters.ALL & (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO), lambda update, context: process_incoming_video(update, context)))
    return application


