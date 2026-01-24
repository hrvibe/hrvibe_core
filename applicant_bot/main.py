import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from applicant_bot import (
    create_applicant_application, 
    start_command, 
    admin_get_list_of_applicants_command,
    admin_send_message_to_applicant_command,
)

from services.data_service import (
    create_applicant_bot_data_directory,
    create_applicant_bot_records_file,
)
from shared_services.constants import (
    BTN_MENU,
    BTN_FEEDBACK,
    WELCOME_TEXT_WHEN_STARTING_BOT_APPLICANT as WELCOME_TEXT_WHEN_STARTING_BOT,
)
"""from services.logging_service import setup_logging"""
from shared_services.auth_service import setup_logging

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

        # Call the main start_command from applicant_bot
        await start_command(update, context)


# ----------- LOADING OF ENVIRONMENT VARIABLES from .env file -----------

load_dotenv()

# set up global flag that helps to avoid multiple shutdown signals (which might screw up the shutdown sequence)
_shutting_down = False

async def run_applicant_bot() -> None:
    """Starts the applicant bot"""
    
    global _shutting_down

    # ------------- SETUP OF THE APPLICATION -------------

    applicant_token = os.getenv("TELEGRAM_APPLICANT_BOT_TOKEN")
    if not applicant_token:
        raise RuntimeError("TELEGRAM_APPLICANT_BOT_TOKEN not found in environment variables")
    application = create_applicant_application(applicant_token)
    application.add_handler(CommandHandler("start", _show_bottom_menu_on_start), group=-1)
    application.add_handler(CommandHandler("admin_get_list_of_applicants", admin_get_list_of_applicants_command))
    application.add_handler(CommandHandler("admin_send_message_to_applicant", admin_send_message_to_applicant_command))
    
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

    create_applicant_bot_data_directory() # will be skipped if exist
    create_applicant_bot_records_file() # will be skipped if exist

    # ------------- STARTING OF THE MANAGER BOT -------------

    try:
        #use "asyncio.run" to start the asynchronous function run_manager_bot() from synchronous main() function
        # this will create new event loop => process all asynchronous tasks in the background => close the event loop after completion
        asyncio.run(run_applicant_bot())
    except KeyboardInterrupt:
        logger.info("\nTelegram Bot for Managers has been stopped by user.")


if __name__ == "__main__":
    main()
