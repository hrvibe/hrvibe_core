# TAGS: [admin]
# Shared admin commands for manager_bot, applicant_bot, and consultant_bot

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Any

# Add project root to path to access shared_services and manager_bot services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from telegram import Update, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, Application
from telegram.error import TelegramError

from shared_services.constants import (
    FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT,
    FAIL_TECHNICAL_SUPPORT_TEXT,
)

from shared_services.db_service import (
    is_value_in_db,
    is_boolean_field_true_in_db,
    update_record_in_db,
    get_column_value_in_db,
    get_column_value_by_field
)

from database import Managers, Vacancies, Negotiations, Base



from shared_services.data_service import (
    is_vacany_data_enough_for_resume_analysis,
    get_tg_user_data_attribute_from_update_object,
)

from shared_services.questionnaire_service import send_message_to_user

from manager_bot.manager_bot import send_message_to_admin

logger = logging.getLogger(__name__)


async def admin_get_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to list all user IDs from user records.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_get_users_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- SEND LIST OF USERS IDs from records -----

        user_ids = get_list_of_users_from_records()

        await send_message_to_user(update, context, text=f"📋 List of users: {user_ids}")
    
    except Exception as e:
        logger.error(f"admin_get_users_command: Failed to execute admin_get_list_of_users command: {e}", exc_info=True)        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_get_users_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_anazlyze_sourcing_criterais_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to analyze sourcing criterias for a specific vacancy.
    Usage: /admin_analyze_sourcing_criterais <vacancy_id>
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_anazlyze_sourcing_criterais_command: started. User_id: {bot_user_id}")

        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        vacancy_id = None
        if context.args and len(context.args) == 1:
            vacancy_id = context.args[0]
            if vacancy_id:
                # Verify that the vacancy exists
                if is_value_in_db(db_model=Vacancies, field_name="id", value=vacancy_id):
                    # Check if vacancy has description received
                    if is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="description_recieved"):
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import define_sourcing_criterias_triggered_by_admin_command
                        await define_sourcing_criterias_triggered_by_admin_command(vacancy_id=vacancy_id)
                        await send_message_to_user(update, context, text=f"Task for analysing sourcing criterias is in task_queue for vacancy {vacancy_id}.")
                    else:
                        raise ValueError(f"Vacancy {vacancy_id} does not have vacancy description received.")     
                else:
                    raise ValueError(f"Vacancy {vacancy_id} not found in database.")  
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_analyze_criterias <vacancy_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_analyze_criterias <vacancy_id>")
    
    except Exception as e:
        logger.error(f"admin_anazlyze_sourcing_criterais_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_anazlyze_sourcing_criterais_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_send_sourcing_criterais_to_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to send sourcing criterias to a specific vacancy.
    Usage: /admin_send_sourcing_criterais_to_user [vacancy_id]
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_send_sourcing_criterais_to_user_command: started. User_id: {bot_user_id}")

        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----


        vacancy_id = None
        if context.args and len(context.args) == 1:
            vacancy_id = context.args[0]
            if vacancy_id:
                # Verify that the vacancy exists
                if is_value_in_db(db_model=Vacancies, field_name="id", value=vacancy_id):
                    # Check if vacancy has sourcing criterias received
                    if is_boolean_field_true_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="sourcing_criterias_recieved"):
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import send_to_user_sourcing_criterias_triggered_by_admin_command
                        await send_to_user_sourcing_criterias_triggered_by_admin_command(vacancy_id=vacancy_id, application=context.application)
                        await send_message_to_user(update, context, text=f"Sent sourcing criteria for vacancy {vacancy_id} to user. Waiting for feedback.")
                    else:
                        raise ValueError(f"Vacancy {vacancy_id} does not have sourcing criterias received.")     
                else:
                    raise ValueError(f"Vacancy {vacancy_id} not found in database.")  
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_send_sourcing_criterais_to_user <vacancy_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_send_sourcing_criterais_to_user <vacancy_id>")
    
    except Exception as e:
        logger.error(f"admin_send_sourcing_criterais_to_user_command: Failed: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_send_sourcing_criterais_to_user_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_update_negotiations_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to update negotiations for specific vacancy.
    Usage: /admin_update_negotiations [vacancy_id]
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_update_negotiations_command: started. User_id: {bot_user_id}")

        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        vacancy_id = None
        if context.args and len(context.args) == 1:
            vacancy_id = context.args[0]
            if vacancy_id:
                # Verify that the vacancy exists
                if is_value_in_db(db_model=Vacancies, field_name="id", value=vacancy_id):
                    
                    # Import here to avoid circular dependency
                    from manager_bot.manager_bot import source_negotiations_triggered_by_admin_command
                    from shared_services.constants import EMPLOYER_STATE_RESPONSE
                    
                    # Fetch negotiations collection (saves to file)
                    await source_negotiations_triggered_by_admin_command(vacancy_id=vacancy_id)
                    await send_message_to_user(update, context, text=f"Negotiations collection updated and parsed to DB for vacancy {vacancy_id}.")
                else:
                    raise ValueError(f"Vacancy {vacancy_id} not found in database.")
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_update_negotiations <vacancy_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_update_negotiations <vacancy_id>")
    
    except Exception as e:
        logger.error(f"admin_update_negotiations_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_update_negotiations_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_get_fresh_resumes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to get fresh resumes for all users.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_get_fresh_resumes_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        target_user_id = None
        if context.args and len(context.args) == 1:
            target_user_id = context.args[0]
            if target_user_id:
                """if is_user_in_records(record_id=target_user_id):"""
                if is_value_in_db(db_model=Managers, field_name="id", value=target_user_id):
                    if is_vacany_data_enough_for_resume_analysis(user_id=target_user_id):
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import source_resumes_triggered_by_admin_command
                        await source_resumes_triggered_by_admin_command(bot_user_id=target_user_id)
                        await send_message_to_user(update, context, text=f"Fresh resumes collected for user {target_user_id}.")
                    else:
                        raise ValueError(f"User {target_user_id} does not have enough vacancy data for resume analysis.")
                else:
                    raise ValueError(f"User {target_user_id} not found in records.")
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_get_fresh_resumes <user_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_get_fresh_resumes <user_id>")

    except Exception as e:
        logger.error(f"admin_get_fresh_resumes_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_get_fresh_resumes_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_anazlyze_resumes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to analyze fresh resumes for all users.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_anazlyze_resumes_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        target_user_id = None
        if context.args and len(context.args) == 1:
            target_user_id = context.args[0]
            if target_user_id:
                """if is_user_in_records(record_id=target_user_id):"""
                if is_value_in_db(db_model=Managers, field_name="id", value=target_user_id):
                    if is_vacany_data_enough_for_resume_analysis(user_id=target_user_id):
                        await send_message_to_user(update, context, text=f"Start creating tasks for analysis of the fresh resumes for user {target_user_id}.")
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import analyze_resume_triggered_by_admin_command
                        await analyze_resume_triggered_by_admin_command(bot_user_id=target_user_id)
                        await send_message_to_user(update, context, text=f"Analysis of fresh resumes is done for user {target_user_id}.")
                    else:
                        raise ValueError(f"User {target_user_id} does not have enough vacancy data for resume analysis.")
                else:
                    raise ValueError(f"User {target_user_id} not found in records.")
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_analyze_resumes <user_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_analyze_resumes <user_id>")
    
    except Exception as e:
        logger.error(f"admin_anazlyze_resumes_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_anazlyze_resumes_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_update_resume_records_with_applicants_video_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to update resume records with fresh videos from applicants for all users.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_update_resume_records_with_applicants_video_status_command: started. User_id: {bot_user_id}")

        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        target_user_id = None
        if context.args and len(context.args) == 1:
            target_user_id = context.args[0]
            if target_user_id:
                """if is_user_in_records(record_id=target_user_id):"""
                if is_value_in_db(db_model=Managers, field_name="id", value=target_user_id):
                    if is_vacany_data_enough_for_resume_analysis(user_id=target_user_id):
                        target_user_vacancy_id = get_target_vacancy_id_from_records(record_id=target_user_id)
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command
                        await update_resume_records_with_fresh_video_from_applicants_triggered_by_admin_command(bot_user_id=target_user_id, vacancy_id=target_user_vacancy_id)
                        await send_message_to_user(update, context, text=f"Resume records updated with fresh videos from applicants for user {target_user_id}.")
                    else:
                        raise ValueError(f"User {target_user_id} does not have enough vacancy data for resume analysis.")
                else:
                    raise ValueError(f"User {target_user_id} not found in records.")
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_update_resume_records_with_applicants_video_status_for_all <user_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_update_resume_records_with_applicants_video_status_for_all <user_id>")

    
    except Exception as e:
        logger.error(f"admin_update_resume_records_with_applicants_video_status_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_update_resume_records_with_applicants_video_status_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            ) 


async def admin_recommend_resumes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to recommend applicants with video for all users.
    Only accessible to users whose ID is in the ADMIN_IDS whitelist.
    """

    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_recommend_resumes_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        target_user_id = None
        if context.args and len(context.args) == 1:
            target_user_id = context.args[0]
            if target_user_id:
                """if is_user_in_records(record_id=target_user_id):"""
                if is_value_in_db(db_model=Managers, field_name="id", value=target_user_id):
                    if is_vacany_data_enough_for_resume_analysis(user_id=target_user_id):
                        # Import here to avoid circular dependency
                        from manager_bot.manager_bot import recommend_resumes_triggered_by_admin_command
                        await recommend_resumes_triggered_by_admin_command(bot_user_id=target_user_id, application=context.application)
                        await send_message_to_user(update, context, text=f"Recommending resumes is triggered for user {target_user_id}.")
                    else:
                        raise ValueError(f"User {target_user_id} does not have enough vacancy data for resume analysis.")
                else:
                    raise ValueError(f"User {target_user_id} not found in records.")
            else:
                raise ValueError(f"Invalid command arguments. Usage: /admin_recommend <user_id>")
        else:
            raise ValueError(f"Invalid number of arguments. Usage: /admin_recommend <user_id>")
    
    except Exception as e:
        logger.error(f"admin_recommend_resumes_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_recommend_resumes_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to send a message to a specific user by user_id (chat_id).
    Usage: /admin_send_message <user_id> <message_text>
    Usage example: /admin_send_message 7853115214 Привет! Как дела?
    Sends notification to admin if fails
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_send_message_command triggered by user_id: {bot_user_id}")
        
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
                text="⚠️ Неверный формат команды.\nИспользование: /admin_send_message <user_id> <текст_сообщения>"
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
        logger.error(f"Failed to execute admin_send_message_to_user command: {e}", exc_info=True)
        await send_message_to_user(update, context, text=FAIL_TECHNICAL_SUPPORT_TEXT)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error executing admin_send_message_to_user command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_pull_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to pull and send files (logs, videos, audio, etc.).
    Usage: /admin_pull_file <file_relative_path>
    Usage example: /admin_pull_file logs/manager_bot_logs/1234432.log
    Usage example: /admin_pull_file audio/manager_id_123_vacancy_id_456_time_20260123_120622.ogg
    Sends the file as a document to the admin chat.
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_pull_file_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        if not context.args or len(context.args) != 1:
            invalid_args_text = "Invalid arguments.\nValid: /admin_pull_file <file_relative_path>"
            raise ValueError(invalid_args_text)
        
        file_relative_path = context.args[0]

        # ----- CONSTRUCT LOG FILE PATH -----

        data_dir = Path(os.getenv("USERS_DATA_DIR", "./users_data"))
        file_path = data_dir / file_relative_path
        file_name = file_path.name

        # ----- VALIDATE FILE EXTENSION -----

        valid_extensions = [".log", ".json", ".mp4", ".ogg", ".mp3", ".wav", ".m4a", ".flac"]
        file_extension = file_path.suffix
        if file_extension not in valid_extensions:
            invalid_extension_text = f"Invalid file extension.\nValid: {', '.join(valid_extensions)}"
            raise ValueError(invalid_extension_text)

        # ----- CHECK IF FILE EXISTS -----

        if not file_path.exists():
            invalid_path_text = f"Invalid file relative path'{file_relative_path}'. File not found"
            raise FileNotFoundError(invalid_path_text)

        # ----- SEND LOG FILE TO USER -----

        if context.application and context.application.bot:
            try:
                chat_id = update.effective_chat.id
                with open(file_path, 'rb') as file:
                    await context.application.bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(file, filename=file_name)
                    )
                logger.info(f"admin_pull_file_command: file '{file_path}' sent to user {bot_user_id}")
            except Exception as send_err:
                raise TelegramError(f"Failed to send file '{file_path}': {send_err}")
        else:
            raise RuntimeError("Application or bot instance not available")
    except Exception as e:
        logger.error(f"admin_pull_file_command: Failed to execute: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_pull_file_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_push_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to upload a file to a specified location.
    Usage: /admin_push_file <file_relative_path>
    Usage example: /admin_push_file logs/manager_bot_logs/1234432.log
    After calling the command, send the file (json, txt, or mp4) as a document.
    The file will be saved to the specified location.
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_push_file_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return

        # ----- PARSE COMMAND ARGUMENTS -----

        if not context.args or len(context.args) != 1:
            invalid_args_text = "Invalid arguments.\nValid: /admin_push_file <file_path>"
            raise ValueError(invalid_args_text)
        
        file_path_str = context.args[0]
        file_path = Path(file_path_str)
        file_name = file_path.name

        # ----- VALIDATE FILE EXTENSION -----

        valid_extensions = [".json", ".txt", ".mp4", ".log"]
        file_extension = file_path.suffix
        if file_extension not in valid_extensions:
            invalid_extension_text = f"Invalid file extension.\nValid: {', '.join(valid_extensions)}"
            raise ValueError(invalid_extension_text)

        # ----- STORE FILE PATH IN CONTEXT FOR DOCUMENT HANDLER -----

        context.user_data["admin_push_file_path"] = str(file_path)
        context.user_data["admin_push_file_waiting"] = True

        # ----- NOTIFY ADMIN TO SEND FILE -----

        if context.application and context.application.bot:
            chat_id = update.effective_chat.id
            await context.application.bot.send_message(
                chat_id=chat_id,
                text=f"📤 Ready to receive file.\nTarget path: `{file_path_str}`\n\nPlease send the file as a document (json, txt, or mp4).",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"admin_push_file_command: Waiting for file to upload to '{file_path}' for user {bot_user_id}")
        else:
            raise RuntimeError("Application or bot instance not available")
    except Exception as e:
        logger.error(f"admin_push_file_command: Failed to execute: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_push_file_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )


async def admin_push_file_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Handler for document uploads when admin_push_file_command is waiting for a file.
    Saves the received document to the path specified in admin_push_file_command.
    """
    
    try:
        # Log that handler was triggered
        logger.info("admin_push_file_document_handler: Handler triggered")
        
        # Check if message has document
        has_document = update.message and update.message.document is not None
        logger.debug(f"admin_push_file_document_handler: Message has document: {has_document}")
        if has_document:
            doc_name = update.message.document.file_name or "unknown"
            logger.debug(f"admin_push_file_document_handler: Document name: {doc_name}")
        
        # ----- CHECK IF WE ARE WAITING FOR FILE UPLOAD -----

        is_waiting = context.user_data.get("admin_push_file_waiting", False)
        logger.debug(f"admin_push_file_document_handler: Checking if waiting for file upload: {is_waiting}")
        logger.debug(f"admin_push_file_document_handler: Context user_data keys: {list(context.user_data.keys())}")
        
        if not is_waiting:
            logger.debug("admin_push_file_document_handler: Not waiting for file upload, ignoring document")
            return  # Not waiting for file upload, ignore this document
        
        logger.info("admin_push_file_document_handler: started. Waiting for file upload.")
        
        # ----- IDENTIFY USER -----

        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.debug(f"admin_push_file_document_handler: User identified. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----

        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            logger.debug(f"admin_push_file_document_handler: User {bot_user_id} is not admin, ignoring document")
            return  # Not admin, ignore

        # ----- GET FILE PATH FROM CONTEXT -----

        file_path_str = context.user_data.get("admin_push_file_path")
        if not file_path_str:
            logger.error("admin_push_file_document_handler: File path not found in context")
            await update.message.reply_text("❌ Error: File path not found. Please run /admin_push_file command again.")
            context.user_data.pop("admin_push_file_waiting", None)
            context.user_data.pop("admin_push_file_path", None)
            return

        file_path = Path(file_path_str)
        logger.debug(f"admin_push_file_document_handler: Target file path: {file_path}")

        # ----- GET DOCUMENT FROM MESSAGE -----

        if not update.message or not update.message.document:
            logger.warning("admin_push_file_document_handler: No document found in message")
            await update.message.reply_text("❌ Error: No document found in the message. Please send a file as a document.")
            return

        document = update.message.document
        file_name = document.file_name or file_path.name
        logger.info(f"admin_push_file_document_handler: Received document '{file_name}' (file_id: {document.file_id})")

        # ----- VALIDATE FILE EXTENSION -----

        valid_extensions = [".json", ".txt", ".mp4", ".log"]
        file_extension = Path(file_name).suffix.lower()
        logger.debug(f"admin_push_file_document_handler: File extension: {file_extension}")
        if file_extension not in valid_extensions:
            logger.warning(f"admin_push_file_document_handler: Invalid file extension '{file_extension}' for file '{file_name}'")
            await update.message.reply_text(
                f"❌ Invalid file extension: {file_extension}\nValid extensions: {', '.join(valid_extensions)}"
            )
            return

        # ----- DOWNLOAD FILE FROM TELEGRAM -----

        if not context.application or not context.application.bot:
            raise RuntimeError("Application or bot instance not available")

        logger.info(f"admin_push_file_document_handler: Downloading file '{file_name}' from Telegram")
        file = await context.application.bot.get_file(document.file_id)
        logger.debug(f"admin_push_file_document_handler: File object retrieved from Telegram. File size: {getattr(document, 'file_size', 'unknown')} bytes")
        
        # ----- SAVE FILE TO SPECIFIED LOCATION -----

        # Create directory if it doesn't exist
        logger.debug(f"admin_push_file_document_handler: Creating directory if needed: {file_path.parent}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"admin_push_file_document_handler: Directory ensured: {file_path.parent}")
        
        # Download and save file
        logger.info(f"admin_push_file_document_handler: Saving file to '{file_path}'")
        await file.download_to_drive(custom_path=str(file_path))
        logger.info(f"admin_push_file_document_handler: File '{file_name}' saved to '{file_path}' for user {bot_user_id}")

        # ----- CLEAN UP CONTEXT -----

        logger.debug("admin_push_file_document_handler: Cleaning up context data")
        context.user_data.pop("admin_push_file_waiting", None)
        context.user_data.pop("admin_push_file_path", None)

        # ----- CONFIRM SUCCESS TO ADMIN -----

        await update.message.reply_text(
            f"✅ File successfully uploaded!\nPath: `{file_path.relative_to(Path(os.getenv('USERS_DATA_DIR', './users_data')))}`",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"admin_push_file_document_handler: Success confirmation sent to user {bot_user_id}")

    except Exception as e:
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id")) if update else "unknown"
        logger.error(f"admin_push_file_document_handler: Failed to execute for user {bot_user_id}: {e}", exc_info=True)
        
        # Clean up context on error
        logger.debug("admin_push_file_document_handler: Cleaning up context data due to error")
        context.user_data.pop("admin_push_file_waiting", None)
        context.user_data.pop("admin_push_file_path", None)
        
        # Send error message to admin
        if update.message:
            logger.debug(f"admin_push_file_document_handler: Sending error message to user {bot_user_id}")
            await update.message.reply_text(f"❌ Error uploading file: {e}")
        
        # Send notification to admin about the error
        if context.application:
            logger.debug(f"admin_push_file_document_handler: Sending admin notification about error")
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_push_file_document_handler: {e}\nAdmin ID: {bot_user_id}"
            )


def _get_table_model(table_name: str):
    """Map table name to SQLAlchemy model class."""
    table_map = {
        "managers": Managers,
        "vacancies": Vacancies,
        "negotiations": Negotiations,
    }
    return table_map.get(table_name.lower())


def _convert_value_to_type(value_str: str, column_type) -> Any:
    """Convert string value to appropriate type based on column type."""
    from sqlalchemy import Boolean, BigInteger, Integer
    from sqlalchemy.dialects.postgresql import JSONB
    
    if isinstance(column_type, Boolean):
        # Handle boolean values
        if value_str.lower() in ('true', '1', 'yes', 'y', 'on'):
            return True
        elif value_str.lower() in ('false', '0', 'no', 'n', 'off'):
            return False
        else:
            raise ValueError(f"Cannot convert '{value_str}' to boolean. Use 'true'/'false', '1'/'0', 'yes'/'no'")
    
    elif isinstance(column_type, (BigInteger, Integer)):
        # Handle integer values
        try:
            return int(value_str)
        except ValueError:
            raise ValueError(f"Cannot convert '{value_str}' to integer")
    
    elif isinstance(column_type, JSONB):
        # Handle JSON values
        import ast
        try:
            # First try parsing as valid JSON (with double quotes)
            return json.loads(value_str)
        except json.JSONDecodeError:
            # If that fails, try parsing as Python dict syntax (with single quotes)
            # ast.literal_eval safely evaluates Python literals (dicts, lists, strings, etc.)
            try:
                return ast.literal_eval(value_str)
            except (ValueError, SyntaxError) as e:
                raise ValueError(f"Cannot parse '{value_str}' as JSON. Use valid JSON format with double quotes or Python dict format with single quotes. Error: {e}")
    
    else:
        # Default to string
        return value_str


async def admin_update_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #TAGS: [admin]
    """
    Admin command to update a database record.
    Usage: /admin_update_db <table_name> <record_id> <column_name> <new_value>
    
    Examples:
    /admin_update_db managers 7853115214 access_token "new_token_value"
    /admin_update_db managers 7853115214 privacy_policy_confirmed true
    /admin_update_db managers 7853115214 access_token_expires_at 1234567890
    /admin_update_db vacancies vacancy_123 name "New Vacancy Name"    
    Note: For JSON columns, you can use either Python dict syntax (single quotes) or JSON format (double quotes).
    """
    
    try:
        # ----- IDENTIFY USER and pull required data from records -----
        
        bot_user_id = str(get_tg_user_data_attribute_from_update_object(update=update, tg_user_attribute="id"))
        logger.info(f"admin_update_db_command: started. User_id: {bot_user_id}")
        
        #  ----- CHECK IF USER IS NOT AN ADMIN and STOP if it is -----
        
        admin_id = os.getenv("ADMIN_ID", "")
        if not admin_id or bot_user_id != admin_id:
            await send_message_to_user(update, context, text=FAIL_TO_IDENTIFY_USER_AS_ADMIN_TEXT)
            logger.error(f"Unauthorized for {bot_user_id}")
            return
        
        # ----- PARSE COMMAND ARGUMENTS -----
        
        if not context.args or len(context.args) < 4:
            await send_message_to_user(
                update, 
                context, 
                text="⚠️ Неверный формат команды.\n"
                     "Использование: /admin_update_db <table_name> <record_id> <column_name> <new_value>\n\n"
                     "Примеры:\n"
                     "/admin_update_db managers 7853115214 access_token \"new_token\"\n"
                     "/admin_update_db managers 7853115214 privacy_policy_confirmed true\n"
                     "/admin_update_db managers 7853115214 access_token_expires_at 1234567890"
            )
            return
        
        table_name = context.args[0].lower()
        record_id = context.args[1]
        column_name = context.args[2]
        new_value_str = " ".join(context.args[3:])  # Join remaining args in case value has spaces
        
        # ----- VALIDATE TABLE NAME -----
        
        db_model = _get_table_model(table_name)
        if not db_model:
            await send_message_to_user(
                update, 
                context, 
                text=f"❌ Неверное имя таблицы: {table_name}\n"
                     f"Доступные таблицы: managers, vacancies, negotiations"
            )
            return
        
        # ----- VALIDATE COLUMN EXISTS -----
        
        column = db_model.__table__.columns.get(column_name)
        if column is None:
            await send_message_to_user(
                update, 
                context, 
                text=f"❌ Колонка '{column_name}' не найдена в таблице '{table_name}'"
            )
            return
        
        # ----- CHECK IF RECORD EXISTS -----
        
        if not is_value_in_db(db_model=db_model, field_name="id", value=record_id):
            await send_message_to_user(
                update, 
                context, 
                text=f"❌ Запись с ID '{record_id}' не найдена в таблице '{table_name}'"
            )
            return
        
        # ----- GET CURRENT VALUE -----
        
        current_value = get_column_value_in_db(db_model=db_model, record_id=record_id, field_name=column_name)
        
        # ----- CONVERT VALUE TO APPROPRIATE TYPE -----
        
        try:
            new_value = _convert_value_to_type(new_value_str, column.type)
        except ValueError as e:
            await send_message_to_user(
                update, 
                context, 
                text=f"❌ Ошибка преобразования значения: {e}"
            )
            return
        
        # ----- UPDATE RECORD -----
        
        try:
            update_record_in_db(
                db_model=db_model,
                record_id=record_id,
                updates={column_name: new_value}
            )
            
            # Get updated value to confirm
            updated_value = get_column_value_in_db(db_model=db_model, record_id=record_id, field_name=column_name)
            
            await send_message_to_user(
                update, 
                context, 
                text=f"✅ Запись обновлена успешно!\n\n"
                     f"Таблица: {table_name}\n"
                     f"ID записи: {record_id}\n"
                     f"Колонка: {column_name}\n"
                     f"Старое значение: {current_value}\n"
                     f"Новое значение: {updated_value}"
            )
            logger.info(f"admin_update_db_command: Successfully updated {table_name}.{column_name} for record {record_id}")
            
        except Exception as e:
            logger.error(f"admin_update_db_command: Failed to update record: {e}", exc_info=True)
            await send_message_to_user(
                update, 
                context, 
                text=f"❌ Ошибка при обновлении записи: {e}"
            )
            raise
    
    except Exception as e:
        logger.error(f"admin_update_db_command: Failed to execute command: {e}", exc_info=True)
        # Send notification to admin about the error
        if context.application:
            await send_message_to_admin(
                application=context.application,
                text=f"⚠️ Error admin_update_db_command: {e}\nAdmin ID: {bot_user_id if 'bot_user_id' in locals() else 'unknown'}"
            )
