"""
Video handling functionality
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

from shared_services.db_service import (
    get_column_value_in_db,
    update_record_in_db,
    get_column_value_by_field,
    update_column_value_by_field
)
from database import Managers, Vacancies, Negotiations

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)
"""
from shared_services.data_service import (
    get_target_vacancy_id_from_records,
    get_directory_for_video_from_managers,
    update_user_records_with_top_level_key,
    )
"""
"""from services.questionnaire_service import send_message_to_user"""
from shared_services.questionnaire_service import send_message_to_user

from shared_services.constants import (
    MAX_DURATION_SECS,
    SUCCESS_TO_SAVE_VIDEO_TEXT
    )

from shared_services.data_service import (
    get_data_subdirectory_path
    )



def _validate_incoming_video(file_size: int, duration: int, max_duration: int = MAX_DURATION_SECS) -> str:
    """Validate incoming video file and return error message if invalid, empty string if valid"""
    # Check duration
    if duration > max_duration:
        return f"Видео слишком длиннее. Пожалуйста, перезапишите более короткое до 60 секунд."
    
    # Check file size (50MB limit)
    if file_size:
        file_size_mb = file_size / (1024 * 1024)
        if file_size_mb > 50:
            return f"Видео больше максимального размера 50 MB. Пожалуйста, запишите кружочек, он точно меньше 50 MB."
    
    return ""


def _clear_pending_video_data_from_context_object(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear pending video data from context object"""
    context.user_data.pop("pending_file_id", None)
    context.user_data.pop("pending_kind", None)
    context.user_data.pop("pending_duration", None)
    context.user_data.pop("pending_file_size", None)


async def process_incoming_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    1) Collect incoming video data, validate it, and store it in "context" object's "user_data" for later processing
    2) Trigger 'ask_confirm_sending_video' method
    """
 
    # ----- GET VIDEO DETAILS from message -----
 
    # Get different video details depending on the type of video
    tg_video = update.message.video
    tg_vnote = update.message.video_note
    tg_doc = update.message.document if update.message.document and (update.message.document.mime_type or "").startswith("video/") else None

    file_id = None
    kind = None
    duration = None
    file_size = None
    
    if tg_video:
        file_id = tg_video.file_id
        kind = "video"
        duration = tg_video.duration
        file_size = getattr(tg_video, 'file_size', None)
    elif tg_vnote:
        file_id = tg_vnote.file_id
        kind = "video_note"
        duration = tg_vnote.duration
        file_size = getattr(tg_vnote, 'file_size', None)
    elif tg_doc:
        file_id = tg_doc.file_id
        kind = "document_video"
        file_size = getattr(tg_doc, 'file_size', None)

    # ----- IF NO VIDEO DETECTED, ask to reupload video -----

    if not file_id:
        await update.message.reply_text("Не удалось определить видео. Пришлите, пожалуйста, еще раз не текст, не фото или аудио, а именно видео.")
        return

    # ----- VALIDATE THAT VIDEO matches requirements -----

    # Validate video using the helper function
    error_msg = _validate_incoming_video(file_size or 0, duration or 0)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    # ----- STORE VIDEO DETAILS in "context" object's "user_data" for later processing -----

    # Store video details in "context" object's "user_data" for later processing
    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_kind"] = kind
    context.user_data["pending_duration"] = duration
    context.user_data["pending_file_size"] = file_size


    # Local import to avoid circular dependency with manager_bot
    from manager_bot import ask_confirm_sending_video_command

    await ask_confirm_sending_video_command(update, context)


async def download_incoming_video_locally(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_file_id: str, user_type: str, user_id: int, file_type: str) -> None:
    """Download video file to local storage"""

    log_prefix = "download_incoming_video_locally"
    logger.info(f"{log_prefix}: start")
    logger.info(f"{log_prefix}: tg_file_id={tg_file_id}, user_type={user_type}, user_id={user_id}, file_type={file_type}")

    
    try:
        query = update.callback_query
        bot_user_id = user_id

        video_dir_path = get_data_subdirectory_path(subdirectory_name="videos")
        logger.info(f"{log_prefix}: target video_dir_path={video_dir_path}")

        if video_dir_path is None:
            raise ValueError(f"Video directory path not found.")

        # ----- GENERATE UNIQUE FILENAME WITH APPROPRIATE EXTENSION -----

        if user_type == "manager":
            vacancy_id = get_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="id")
            # Generate unique filename with appropriate extension
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            if file_type == "video_note":
                filename = f"vacancy_id_{vacancy_id}_time_{timestamp}_note.mp4"
            else:
                filename = f"vacancy_id_{vacancy_id}_time_{timestamp}.mp4"

        elif user_type == "applicant":
            negotiation_id = get_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=bot_user_id, target_field_name="id")
            # Generate unique filename with appropriate extension
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            if file_type == "video_note":
                filename = f"negotiation_id_{negotiation_id}_time_{timestamp}_note.mp4"
            else:
                filename = f"negotiation_id_{negotiation_id}_time_{timestamp}.mp4"

        else:
            raise ValueError(f"{log_prefix}: Invalid user type: {user_type}")

        video_file_path = video_dir_path / filename
        logger.info(f"{log_prefix}: Target video file path to save video: {video_file_path}")

        # Download the file
        if not tg_file_id:
            raise ValueError(f"{log_prefix}: Telegram file identifier is empty.")

        try:
            tg_file = await context.bot.get_file(tg_file_id)
        except Exception as fetch_error:
            raise RuntimeError(f"{log_prefix}: Failed to fetch Telegram file: {fetch_error}") from fetch_error

        await tg_file.download_to_drive(custom_path=str(video_file_path))
        logger.info(f"{log_prefix}: Target video file downloaded to: {video_file_path}")

        # ----- UPDATE USER RECORDS WITH VIDEO RECEIVED AND VIDEO PATH -----

        if user_type == "manager":
            update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="video_received", new_value=True)
            update_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="video_path", new_value=str(video_file_path))
        
        elif user_type == "applicant":
            update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="video_received", new_value=True)
            update_column_value_by_field(db_model=Negotiations, search_field_name="id", search_value=negotiation_id, target_field_name="video_path", new_value=str(video_file_path))

        
        logger.info(f"{log_prefix}: User records updated with video received and video path")

        # Clear pending video data from context object
        _clear_pending_video_data_from_context_object(context=context)
        logger.info(f"{log_prefix}: Pending video data cleared from context object")
        
        # Verify the file was created successfully
        if video_file_path.exists():

            logger.info(f"{log_prefix}: Video file was created successfully.")
            await send_message_to_user(update, context, text=SUCCESS_TO_SAVE_VIDEO_TEXT)



            # ----- CALL NEXT COMMAND BASED ON USER TYPE -----
            if user_type == "manager":

                # ----- READ VACANCY DESCRIPTION -----

                from manager_bot import read_vacancy_description_command

                try:
                    await read_vacancy_description_command(update=update, context=context)
                    logger.info(f"{log_prefix}: read_vacancy_description_command completed successfully")
                except Exception as e:
                    logger.error(f"{log_prefix}: Failed to call read_vacancy_description_command: {e}", exc_info=True)
                    raise  

            elif user_type == "applicant":

                # ----- SAY GOODBYE  -----

                from applicant_bot import say_goodbye_command

                try:
                    await say_goodbye_command(update=update, context=context)
                    logger.info(f"{log_prefix}: say_goodbye_command completed successfully")
                except Exception as e:
                    logger.error(f"{log_prefix}: Failed to call say_goodbye_command: {e}", exc_info=True)
                    raise 

        else:
            logger.error(f"{log_prefix}: Video file not created after download: {video_file_path}")
            await send_message_to_user(update, context, text="Ошибка при скачивании видео. Пришлите заново, пожалуйста.")
            raise FileNotFoundError(f"{log_prefix}: Video file was not created at {video_file_path}")

    except Exception as e:
        logger.error(f"{log_prefix}: Failed: {str(e)}", exc_info=True)
        raise

