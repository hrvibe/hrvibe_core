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
from database import Managers, Vacancies

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



def _validate_incoming_audio(file_size: int, duration: int, max_duration: int = MAX_DURATION_SECS) -> str:
    """Validate incoming audio file and return error message if invalid, empty string if valid"""
    # Check duration
    if duration > max_duration:
        return f"Аудио слишком длиннее. Пожалуйста, перезапишите более короткое до 60 секунд."
    
    # Check file size (50MB limit)
    if file_size:
        file_size_mb = file_size / (1024 * 1024)
        if file_size_mb > 50:
            return f"Аудио больше максимального размера 50 MB."
    
    return ""


def _clear_pending_audio_data_from_context_object(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear pending video data from context object"""
    context.user_data.pop("pending_file_id", None)
    context.user_data.pop("pending_kind", None)
    context.user_data.pop("pending_duration", None)
    context.user_data.pop("pending_file_size", None)


async def process_incoming_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    1) Collect incoming audio data, validate it
    2) Download audio file directly to local storage
    """
 
    # ----- GET AUDIO DETAILS from message -----
 
    # Get different audio details depending on the type of audio
    tg_audio = update.message.audio
    tg_voice = update.message.voice
    tg_doc = update.message.document if update.message.document and (update.message.document.mime_type or "").startswith("audio/") else None

    file_id = None
    kind = None
    duration = None
    file_size = None
    
    if tg_audio:
        file_id = tg_audio.file_id
        kind = "audio"
        duration = tg_audio.duration
        file_size = getattr(tg_audio, 'file_size', None)
    elif tg_voice:
        file_id = tg_voice.file_id
        kind = "voice"
        duration = tg_voice.duration
        file_size = getattr(tg_voice, 'file_size', None)
    elif tg_doc:
        file_id = tg_doc.file_id
        kind = "document_audio"
        file_size = getattr(tg_doc, 'file_size', None)

    # ----- IF NO AUDIO DETECTED, ask to reupload audio -----

    if not file_id:
        await update.message.reply_text("Не удалось определить аудио. Пришлите, пожалуйста, еще раз не текст, не фото или видео, а именно аудио.")
        return

    # ----- VALIDATE THAT AUDIO matches requirements -----

    # Validate audio using the helper function
    error_msg = _validate_incoming_audio(file_size or 0, duration or 0)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    # ----- DOWNLOAD AUDIO DIRECTLY -----
    
    # Get user_id from the update
    user_id = update.message.from_user.id
    
    # Trigger download directly
    await download_incoming_audio_locally(
        update=update,
        context=context,
        tg_file_id=file_id,
        user_id=user_id,
        file_type=kind
    )


async def download_incoming_audio_locally(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_file_id: str, user_id: int, file_type: str) -> None:
    """Download audio file to local storage"""
    logger.info(f"download_incoming_audio_locally called: user_id={user_id}, file_type={file_type}")
    try:
        query = update.callback_query
        bot_user_id = str(user_id)

        audio_dir_path = get_data_subdirectory_path(subdirectory_name="audio")
        logger.info(f"download_incoming_audio_locally: target audio_dir_path={audio_dir_path}")

        vacancy_id = get_column_value_by_field(db_model=Vacancies, search_field_name="manager_id", search_value=bot_user_id, target_field_name="id")
        

        if audio_dir_path is None:
            logger.error(f"download_incoming_audio_locally: Target audio_dir_path to save audio not found.")
            raise ValueError(f"Audio directory path not found.")

        # Generate unique filename with appropriate extension
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        if file_type == "audio_note":
            filename = f"manager_id_{bot_user_id}_vacancy_id_{vacancy_id}_time_{timestamp}_note.ogg"
        else:
            filename = f"manager_id_{bot_user_id}_vacancy_id_{vacancy_id}_time_{timestamp}.ogg"

        audio_file_path = audio_dir_path / filename
        logger.info(f"download_incoming_audio_locally: Target audio file path to save audio for managers: {audio_file_path}")

        # Download the file
        if not tg_file_id:
            raise ValueError("download_incoming_audio_locally: Telegram file identifier is empty.")

        try:
            tg_file = await context.bot.get_file(tg_file_id)
        except Exception as fetch_error:
            raise RuntimeError(f"download_incoming_audio_locally: Failed to fetch Telegram file: {fetch_error}") from fetch_error

        await tg_file.download_to_drive(custom_path=str(audio_file_path))
        logger.info(f"download_incoming_audio_locally: Target audio file from manager downloaded to: {audio_file_path}")
        
        # Verify the file was created successfully
        if audio_file_path.exists():
            logger.info(f"download_incoming_audio_locally: Audio file was created successfully")
            
            await send_message_to_user(update, context, text="Аудио успешно скачано и сохранено.")

            # Local import to avoid circular dependency with manager_bot
            from manager_bot.manager_bot import send_message_to_admin
            await send_message_to_admin(application=context.application, text=f"User {bot_user_id} recorded audio for vacancy {vacancy_id}. Here is the audio file path: {audio_file_path}")

            # Clear any pending audio data from context object after successful download
            _clear_pending_audio_data_from_context_object(context=context)
            logger.info(f"download_incoming_audio_locally: Pending audio data cleared from context object")

        else:
            logger.error(f"download_incoming_audio_locally: Audio file not created after download: {audio_file_path}")
            await send_message_to_user(update, context, text="Ошибка при скачивании аудио. Пришлите заново, пожалуйста.")
            raise FileNotFoundError(f"download_incoming_audio_locally: Audio file was not created at {audio_file_path}")

    except Exception as e:
        logger.error(f"download_incoming_audio_locally: Failed to download audio: {str(e)}", exc_info=True)
        raise

