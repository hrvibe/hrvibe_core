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

from shared_services.video_service import (
    process_incoming_video,
    download_incoming_video_locally
)


from shared_services.data_service import (
    get_decision_status_from_selected_callback_code,
    get_tg_user_data_attribute_from_update_object
)

from shared_services.questionnaire_service import (
    ask_question_with_options,
    handle_answer,
    send_message_to_user,
    clear_all_unprocessed_keyboards,
    ask_single_question_from_update,
    single_question_callback_handler,
)

from database import (
    Managers,
    Vacancies,
    Negotiations,
)

from shared_services.db_service import (
    is_boolean_field_true_in_db,
    update_record_in_db,
    is_value_in_db,
    get_column_value_in_db,
    get_column_value_by_field,
    update_column_value_by_field
)

from shared_services.constants import *

##########################################
# ------------ ADMIN COMMANDS ------------``
##########################################


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
    """Start command handler. """
    # ----- SETUP NEW USER and send welcome message -----

    log_prefix = "start_command"
    logger.info(f"{log_prefix}: start")

    # if existing user, setup_new_user_command will be skipped
    await setup_new_applicant_user_command(update=update, context=context)

    # ----- ASK PRIVACY POLICY CONFIRMATION -----
    
    # if already confirmed, second confirmation will be skipped
    await process_payload(update=update, context=context)


async def setup_new_applicant_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "setup_new_user_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ------ COLLECT NEW USER ID and CREATE record and user directory if needed ------

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

        negotiation_id = await extract_negotiation_id_from_payload(update=update, context=context)

        if negotiation_id is None:
            logger.debug(f"{log_prefix}: No negotiation_id found in payload")
            return

        # ----- CHECK IF NEGOTIATION exists in records and CREATE record and user directory if needed -----

        if not is_value_in_db(db_model=Negotiations, field_name="id", value=negotiation_id):
            logger.debug(f"{log_prefix}: Negotiation {negotiation_id} not found in database")
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
            return

        # ------ ENRICH APPLICANT RECORDS with NEW USER DATA from Telegram user attributes ------

        username = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="username")
        first_name = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="first_name")
        last_name = get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="last_name")
        user_details =f"Negotiation ID: {negotiation_id}\nApplicant User ID: {bot_user_id}\nUsername: {username}\nFirst Name: {first_name}\nLast Name: {last_name}\n"

        # ----- UPDATE APPLICANT BOT RECORDS with PAYLOAD DATA -----

        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"applicant_visited_bot": True})
        current_time = datetime.now(timezone.utc).isoformat()
        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"first_time_seen": current_time})
        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"tg_user_id": bot_user_id})
        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"tg_username": username})
        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"tg_first_name": first_name})
        update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"tg_last_name": last_name})

        logger.debug(f"{log_prefix}: Negotiation {negotiation_id} updated with applicant user data.")

        # ----- ASK PRIVACY POLICY CONFIRMATION -----

        # if already confirmed, second confirmation will be skipped
        await ask_privacy_policy_confirmation_command(update=update, context=context)
        # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----

        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"🤓 New applicant user has been setup.\n{user_details}"
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


async def extract_negotiation_id_from_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        
        log_prefix = "extract_negotiation_id_from_payload"
        logger.info(f"{log_prefix}: start")

        # ----- EXTRACT PAYLOAD from Telegram start command -----
        # Link structure: Example: https://t.me/{BOT_FOR_APPLICANTS_USERNAME}?start={negotiation_id}
        
        payload = None
        if update.message and update.message.text:
            logger.debug(f"update.message.text: {update.message.text}")
            # Telegram sends /start PAYLOAD as the message text
            text_parts = update.message.text.split(maxsplit=1)
            logger.debug(f"text_parts: {text_parts}")
            if len(text_parts) > 1:
                payload = text_parts[1]  # Get the payload, which is a second part after "/start"

        # ----- PARSE PAYLOAD and EXTRACT negotiation_id -----

        if payload:
            # Parse payload format: "negotiation_id"
            negotiation_id = payload
            logger.debug(f"{log_prefix}: Parsed payload - negotiation_id: {negotiation_id}")

            return negotiation_id
        else:

            logger.debug(f"{log_prefix}: No payload found in start command")
            return None


async def ask_privacy_policy_confirmation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]

    log_prefix = "ask_privacy_policy_confirmation_command"
    logger.info(f"{log_prefix}: start")

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")

        negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=bot_user_id, target_field_name="id")

        # ----- CHECK IF PRIVACY POLICY is already confirmed and STOP if it is -----

        if is_boolean_field_true_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="privacy_policy_confirmed"):
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

    negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=bot_user_id, target_field_name="id")

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
            db_model=Negotiations,
            record_id=negotiation_id,
            updates={"privacy_policy_confirmed": privacy_policy_confirmation_user_value},
        )

        current_time = datetime.now(timezone.utc).isoformat()
        update_record_in_db(
            db_model=Negotiations,
            record_id=negotiation_id,
            updates={"privacy_policy_confirmation_time": current_time},
        )

        logger.debug(f"{log_prefix}: Privacy policy confirmation user {bot_user_id} decision: {privacy_policy_confirmation_user_decision} at {current_time}")

        # ----- IF USER CHOSE "YES" -----

        if privacy_policy_confirmation_user_decision == "yes":
            await send_message_to_user(update, context, text=SUCCESS_TO_GET_PRIVACY_POLICY_CONFIRMATION_TEXT)

            # ----- SEND NEW USER SETUP NOTIFICATION to admin  -----
            if context.application:
                await send_message_to_admin(
                    application=context.application,
                    text=f"🤓 New applicant user {bot_user_id} has given privacy policy confirmation.",
                )

            # ----- SEND AUTHENTICATION REQUEST and wait for user to authorize -----
            await show_welcome_video_command(update=update, context=context)

        # ----- IF USER CHOSE "NO" -----
        else:
            await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)


async def show_welcome_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    # TAGS: [user_related]
    """Show welcome video command."""

    log_prefix = "show_welcome_video_command"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
    negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=bot_user_id, target_field_name="id")
    vacancy_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="vacancy_id")

    # ----- CHECK IF SUCH VACANCY exists and STOP if not -----

    if not is_value_in_db(db_model=Vacancies, field_name="id", value=vacancy_id):
        logger.debug(f"{log_prefix}: Vacancy {vacancy_id} not found in database")
        await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_PAYLOAD_TEXT)
        return

    # ----- CHECK IF WELCOME VIDEO is already shown and STOP if it is -----

    if is_boolean_field_true_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="welcome_video_shown"):
        await send_message_to_user(update, context, text=SUCCESS_TO_GET_WELCOME_VIDEO_TEXT)
        return

    await send_message_to_user(update, context, text=INFO_UPLOADING_WELCOME_VIDEO_TEXT)

    # ----- GET WELCOME VIDEO from managers -----

    video_path = get_column_value_by_field(db_model=Vacancies, search_field_name="id", search_value=vacancy_id, target_field_name="video_path")
    if video_path is None:
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        return

    # ----- SEND WELCOME VIDEO to applicant -----
    
    await context.application.bot.send_video(chat_id=int(bot_user_id), video=str(video_path))
    update_record_in_db(db_model=Negotiations, record_id=negotiation_id, updates={"welcome_video_shown": True})
    await asyncio.sleep(1)
    
    await ask_to_record_video_command(update=update, context=context)


async def ask_to_record_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Ask to record video command.""" 

    log_prefix = "ask_to_record_video_command"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----

    bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: user_id fetched {bot_user_id}")
    negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=bot_user_id, target_field_name="id")

    if is_boolean_field_true_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="video_received"):
        logger.debug(f"{log_prefix}: user {bot_user_id} already has welcome video recorded.")
        await send_message_to_user(update, context, text=SUCCESS_TO_RECORD_VIDEO_TEXT)
        return

    # ----- CHECK MUST CONDITIONS are met and STOP if not -----

    if not is_boolean_field_true_in_db(db_model=Managers, record_id=bot_user_id, field_name="privacy_policy_confirmed"):
        logger.debug(f"{log_prefix}: user {bot_user_id} doesn't have privacy policy confirmed.")
        await send_message_to_user(update, context, text=MISSING_PRIVACY_POLICY_CONFIRMATION_TEXT)
        return


    await send_message_to_user(update, context, text=INSTRUCTIONS_TO_SHOOT_VIDEO_TEXT_APPLICANT)
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
    negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=bot_user_id, target_field_name="id")

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

        update_column_value_by_field(
            db_model=Negotiations,
            search_field_name="id",
            search_value=negotiation_id,
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
            user_type="applicant",
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
                text=f"🤓 New applicant user {bot_user_id} has sent video."
            )

    else:

    # ----- IF USER CHOSE "NO" ask for another video -----

        await send_message_to_user(update, context, text=WAITING_FOR_ANOTHER_VIDEO_TEXT)


async def say_goodbye_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TAGS: [user_related]
    """Say goodbye command."""

    log_prefix = "say_goodbye_command"
    logger.info(f"{log_prefix}: start")

    await send_message_to_user(update, context, text=GOODBYE_TEXT_APPLICANT)




########################################################################################
# ------------ MAIN MENU related commands ------------
########################################################################################

async def user_status(applicant_user_id: str) -> dict:
    """Return high-level status flags for the applicant user."""
    status_dict: dict[str, bool] = {}

    # Has this Telegram user ever created a negotiation record?
    has_negotiation = is_value_in_db(
        db_model=Negotiations,
        field_name="tg_user_id",
        value=applicant_user_id,
    )
    status_dict["bot_authorization"] = has_negotiation

    # If there is no negotiation yet, the rest of the steps are definitely not completed
    if not has_negotiation:
        status_dict["privacy_policy_confirmation"] = False
        status_dict["welcome_video_shown"] = False
        status_dict["resume_video_recorded"] = False
        return status_dict

    # Fetch negotiation id for this applicant
    negotiation_id = get_column_value_by_field(
        db_model=Negotiations,
        search_field_name="tg_user_id",
        search_value=applicant_user_id,
        target_field_name="id",
    )

    status_dict["privacy_policy_confirmation"] = is_boolean_field_true_in_db(
        db_model=Negotiations,
        record_id=negotiation_id,
        field_name="privacy_policy_confirmed",
    )
    status_dict["welcome_video_shown"] = is_boolean_field_true_in_db(
        db_model=Negotiations,
        record_id=negotiation_id,
        field_name="welcome_video_shown",
    )
    status_dict["resume_video_recorded"] = is_boolean_field_true_in_db(
        db_model=Negotiations,
        record_id=negotiation_id,
        field_name="video_received",
    )

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

    log_prefix = "show_chat_menu_command"
    logger.info(f"{log_prefix}: start")

    # ----- IDENTIFY USER and pull required data from records -----
    
    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: applicant_user_id fetched {applicant_user_id}")
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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: applicant_user_id fetched {applicant_user_id}")

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
    elif action == "privacy_policy_confirmation":
        await ask_privacy_policy_confirmation_command(update=update, context=context)
    elif action == "welcome_video_shown":
        await show_welcome_video_command(update=update, context=context)
    elif action == "resume_video_recorded":
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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: applicant_user_id fetched {applicant_user_id}")

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

    applicant_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
    logger.info(f"{log_prefix}: applicant_user_id fetched {applicant_user_id}")
    
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
            user_info = ""
            try:
                if is_value_in_db(db_model=Negotiations, field_name="tg_user_id", value=applicant_user_id):
                    negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="tg_user_id", search_value=applicant_user_id, target_field_name="id")
                    vacancy_id = get_column_value_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="vacancy_id")
                    vacancy_name = get_column_value_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="name")
                    username = get_column_value_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="tg_username")
                    first_name = get_column_value_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="hh_first_name")
                    last_name = get_column_value_in_db(db_model=Negotiations, record_id=negotiation_id, field_name="hh_last_name")
                    user_info = (
                        f"Вакансия:{vacancy_name} / ID:{vacancy_id}",
                        f"Соискатель: Negotiation ID {negotiation_id} / User ID {applicant_user_id}, @{username}, {first_name} {last_name})"
                    )
                else:
                    user_info = f"Пользователь User ID: {applicant_user_id}, не найден в базе данных."
            except Exception as e:
                logger.error(f"{log_prefix}: failed to get user info for feedback: {e}")
                user_info = f"Пользователь ID: {applicant_user_id}"
            
            admin_message = f"⚠️  Applicant user feedback:\n\n{user_info}\n\nMessage:\n{feedback_text}"
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


