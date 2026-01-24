import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from manager_bot import (
    create_manager_application, 
    ai_task_queue, 
    start_command,
)
from shared_services.admin import (
    admin_get_users_command,
    admin_update_negotiations_command,
    admin_get_fresh_resumes_command,
    admin_anazlyze_resumes_command,
    admin_anazlyze_sourcing_criterais_command,
    admin_send_sourcing_criterais_to_user_command,
    admin_update_resume_records_with_applicants_video_status_command,
    admin_recommend_resumes_command,
    admin_send_message_command,
    admin_pull_file_command,
    admin_push_file_command,
    admin_push_file_document_handler,
    admin_update_db_command,
)


from shared_services.constants import (
    BTN_MENU,
    BTN_FEEDBACK,
    WELCOME_TEXT_WHEN_STARTING_BOT,
)

from shared_services.data_service import (
    create_data_directories,
)

"""from services.logging_service import setup_logging"""
from shared_services.logging_service import setup_logging


# required for manager menu
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# Create logger at module level (will be configured later in setup_logging)
logger = logging.getLogger(__name__)

# ----------- SETUP OF MENU with buttons that constantly persistent for user -----------

# Use 'ReplyKeyboardMarkup' to show buttons all the time
BOTTOM_MENU_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(BTN_MENU), KeyboardButton(BTN_FEEDBACK)]
    ],
    resize_keyboard=True,
    is_persistent=True,
)

async def _show_bottom_menu_on_start(update, context: ContextTypes.DEFAULT_TYPE):
    """Handler to show manager menu when /start command executed"""
    if update.effective_message:

        # Show the bottom menu keyboard
        await update.effective_message.reply_text(WELCOME_TEXT_WHEN_STARTING_BOT, reply_markup=BOTTOM_MENU_KB)

        # Call the main start_command from manager_bot
        await start_command(update, context)


# ----------- LOADING OF ENVIRONMENT VARIABLES from .env file -----------

load_dotenv()

# set up global flag that helps to avoid multiple shutdown signals (which might screw up the shutdown sequence)
_shutting_down = False

async def run_manager_bot() -> None:
    """Starts
    1) the manager bot
    2) task queue worker for AI related tasks"""
    
    global _shutting_down

    # ------------- SETUP OF THE APPLICATION -------------

    manager_token = os.getenv("TELEGRAM_MANAGER_BOT_TOKEN")
    if not manager_token:
        raise RuntimeError("TELEGRAM_MANAGER_BOT_TOKEN not found in environment variables")
    application = create_manager_application(manager_token)
    application.add_handler(CommandHandler("start", _show_bottom_menu_on_start), group=-1)
    application.add_handler(CommandHandler("admin_get_managers", admin_get_users_command))
    application.add_handler(CommandHandler("admin_analyze_criterias", admin_anazlyze_sourcing_criterais_command))
    application.add_handler(CommandHandler("admin_send_criterias_to_user", admin_send_sourcing_criterais_to_user_command))  
    application.add_handler(CommandHandler("admin_update_negotiations", admin_update_negotiations_command))
    application.add_handler(CommandHandler("admin_get_fresh_resumes", admin_get_fresh_resumes_command))
    application.add_handler(CommandHandler("admin_analyze_resumes", admin_anazlyze_resumes_command))
    application.add_handler(CommandHandler("admin_update_video_for_all", admin_update_resume_records_with_applicants_video_status_command))
    application.add_handler(CommandHandler("admin_recommend", admin_recommend_resumes_command))
    application.add_handler(CommandHandler("admin_send_message", admin_send_message_command))
    application.add_handler(CommandHandler("admin_pull_file", admin_pull_file_command))
    application.add_handler(CommandHandler("admin_push_file", admin_push_file_command))
    application.add_handler(CommandHandler("admin_update_db", admin_update_db_command))
    # Add document handler with higher priority (group=-1 processes before group=0)
    # This ensures it's checked before other message handlers that might catch documents
    application.add_handler(MessageHandler(filters.Document.ALL, admin_push_file_document_handler), group=-1)
    
    # ------------- STARTING OF THE TASK QUEUE WORKER for AI related tasks-------------

    ai_task_queue.start_worker()
    logger.info("Task queue worker to process AI related tasks is started.")
    
    # ------------- INITIALIZATION AND STARTING OF THE APPLICATION -------------

    await application.initialize()
    await application.start()
 
    try:
        
        # ------------- START POLLING to get updates from  Telegram API -------------

        await application.updater.start_polling()
        logger.info("Bot is now polling for updates. Press Ctrl+C to stop.")
        # Polling until shutdown signal is received
        await asyncio.Event().wait()

    # ------------- SHUTDOWN OF THE APPLICATION -------------

    # Cancelling of polling by user (Ctrl+C)
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Set the flag to True to avoid multiple shutdown signals
        if not _shutting_down:
            _shutting_down = True
    finally:
        if _shutting_down:
            logger.info("\nApplication is shutting down gracefully...")

            # ------------- SHUTDOWN OF THE TASK QUEUE WORKER for AI related tasks -------------

            try:
                # Stop task queue worker that processes AI related tasks
                await ai_task_queue.stop_worker(wait=True)
                logger.info("Task queue worker that processes AI related tasks is stopped.")
            except Exception as e:
                logger.error(f"Error stopping task queue worker that processes AI related tasks: {e}")
            
            # ------------- SHUTDOWN OF THE APPLICATION in proper sequence -------------  
            
            try:
                # Stop getting updates from Telegram API
                await application.updater.stop()  # Stop the updater first!
            except Exception:
                pass  # Ignore errors during updater stop
            try:
                # Stop the application
                await application.stop()
            except Exception:
                pass  # Ignore errors during stop
            try:
                # Shutdown the application and clear all resources
                await application.shutdown()
            except Exception:
                pass  # Ignore errors during shutdown
            
            logger.info("Application graceful shut down is completed.")


def main():
    """Main entry point"""

    # ------------- SETUP LOGGING -------------

    # setup_logging() calls logging.basicConfig() that configures the root logger (the top-level logger in Python's hierarchy).
    setup_logging()
    logger.info("Telegram Bot for Managers is running")

    # ------------- SETUP OF THE DATA DIRECTORY and USER RECORDS FILE -------------

    create_data_directories() # will be skipped if exist

    # ------------- STARTING OF THE MANAGER BOT -------------

    try:
        #use "asyncio.run" to start the asynchronous function run_manager_bot() from synchronous main() function
        # this will create new event loop => process all asynchronous tasks in the background => close the event loop after completion
        asyncio.run(run_manager_bot())
    except KeyboardInterrupt:
        logger.info("\nTelegram Bot for Managers has been stopped by user.")


if __name__ == "__main__":
    main()
