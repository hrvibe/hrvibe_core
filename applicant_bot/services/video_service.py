"""
Video handling functionality
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from re import U
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.data_service import (
    get_manager_user_id_from_applicant_bot_records,
    get_vacancy_id_from_applicant_bot_records,
    get_directory_for_video_from_applicants,
    get_resume_id_from_applicant_bot_records,
    update_applicant_bot_records_with_top_level_key
)
from shared_services.constants import (
    FAIL_TECHNICAL_SUPPORT_TEXT,
    SUCCESS_TO_SAVE_VIDEO_TEXT_APPLICANT as SUCCESS_TO_SAVE_VIDEO_TEXT,
    INFO_ABOUT_VIDEO_DELETION_TEXT,
    FAIL_TO_DOWNLOAD_VIDEO_TEXT,
    INFO_DOWNLOADING_APPLICANT_VIDEO_STARTED_TEXT,
    FAIL_TO_IDENTIFY_VIDEO_TEXT,
    MAX_DURATION_SECS
)


logger = logging.getLogger(__name__)

"""from services.questionnaire_service import send_message_to_user"""
from shared_services.questionnaire_service import send_message_to_user


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
        await update.message.reply_text(FAIL_TO_IDENTIFY_VIDEO_TEXT)
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


    # Local import to avoid circular dependency with applicant_bot
    from applicant_bot import ask_confirm_sending_video_command

    await ask_confirm_sending_video_command(update, context)


async def download_incoming_video_locally(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_file_id: str, applicant_user_id: int, file_type: str) -> None:
    """Download video file to local storage"""
    try:
        query = update.callback_query
        manager_user_id = get_manager_user_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)
        vacancy_id = get_vacancy_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)
        video_dir_path = get_directory_for_video_from_applicants(user_record_id=manager_user_id, vacancy_id=vacancy_id) # ValueError raised if fails
        resume_id = get_resume_id_from_applicant_bot_records(applicant_record_id=applicant_user_id)

        await send_message_to_user(update, context, text=INFO_DOWNLOADING_APPLICANT_VIDEO_STARTED_TEXT)


        if video_dir_path is None:
            logger.warning(f"Video directory path for applicant not found. Applicant user id: {applicant_user_id}")
            raise ValueError(f"Video directory path not found for applicant user id: {applicant_user_id}")

        # Generate unique filename with appropriate extension
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        if file_type == "video_note":
            filename = f"applicant_{applicant_user_id}_resume_{resume_id}_time_{timestamp}_note.mp4"
        else:
            filename = f"applicant_{applicant_user_id}_resume_{resume_id}_time_{timestamp}.mp4"

        video_file_path = video_dir_path / filename
        logger.debug(f"Video file path: {video_file_path}")

        # Download the file
        if not tg_file_id:
            raise ValueError("Telegram file identifier is empty.")

        try:
            tg_file = await context.bot.get_file(tg_file_id)
        except Exception as fetch_error:
            raise RuntimeError(f"Failed to fetch Telegram file: {fetch_error}") from fetch_error

        await tg_file.download_to_drive(custom_path=str(video_file_path))
        logger.debug(f"Video file downloaded to: {video_file_path}")

        # Update user records with video received and video path
        update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="resume_video_received", value="yes")
        update_applicant_bot_records_with_top_level_key(applicant_record_id=applicant_user_id, key="resume_video_path", value=str(video_file_path))

        # Clear pending video data from context object
        _clear_pending_video_data_from_context_object(context=context)
        logger.debug(f"Pending video data cleared from context object")
        # Verify the file was created successfully
        if video_file_path.exists():
            logger.debug(f"Video file created successfully: {video_file_path}")
            await send_message_to_user(update, context, text=SUCCESS_TO_SAVE_VIDEO_TEXT)
            await asyncio.sleep(1)
            await send_message_to_user(update, context, text=INFO_ABOUT_VIDEO_DELETION_TEXT)
        else:
            logger.warning(f"Video file not created: {video_file_path}")
            await send_message_to_user(update, context, text=FAIL_TO_DOWNLOAD_VIDEO_TEXT)

    except Exception as e:
        logger.error(f"Failed to download video: {str(e)}", exc_info=True)
        # Send error message to user
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        try:
            from applicant_bot import send_message_to_admin
            if context.application:
                error_message = (
                    f"⚠️ Error downloading video from applicant\n\n"
                    f"Applicant User ID: {applicant_user_id}\n"
                    f"File ID: {tg_file_id}\n"
                    f"File Type: {file_type}\n"
                    f"Error: {str(e)}"
                )
                await send_message_to_admin(
                    application=context.application,
                    text=error_message
                )
        except Exception as admin_error:
            logger.error(f"Failed to send admin notification: {admin_error}", exc_info=True)

