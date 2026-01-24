"""
Модуль для периодических задач (scheduled tasks).
Содержит универсальные функции для запуска периодических задач.
"""

import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional, Dict, Any
from telegram.ext import Application
"""
from shared_services.data_service import get_users_records_file_path
from services.status_validation_service import (
    is_vacancy_selected,
    is_vacancy_description_recieved,
    is_vacancy_sourcing_criterias_recieved,
    is_user_authorized,
    is_vacany_data_enough_for_resume_analysis,
)
"""

from shared_services.data_service import (
    is_vacany_data_enough_for_resume_analysis,
)   

logger = logging.getLogger(__name__)


async def run_periodic_task_for_all_users(
    application: Application,
    task_function: Callable,
    interval_seconds: int,
    shutdown_flag: Optional[Callable[[], bool]] = None,
    task_name: str = "periodic_task",
    requires_bot: bool = False
) -> None:
    """
    Универсальная функция для периодического запуска задачи для всех пользователей.
    
    Args:
        application: Telegram Application instance
        task_function: Асинхронная функция для выполнения задачи.
                       Если requires_bot=True: (bot_user_id, bot) -> None
                       Если requires_bot=False: (bot_user_id) -> None
        interval_seconds: Интервал между запусками в секундах
        shutdown_flag: Опциональная функция для проверки флага завершения () -> bool
        task_name: Имя задачи для логирования
        requires_bot: Если True, получает bot из application и передает в task_function
    """
    while True:
        try:

            # ---- CHECK SHUTDOWN FLAG BEFORE WAITING ----

            if shutdown_flag and shutdown_flag():
                logger.info(f"{task_name}: Shutdown flag detected, stopping task")
                break
            
            await asyncio.sleep(interval_seconds)
            
            # ---- CHECK SHUTDOWN FLAG AFTER WAITING ----

            if shutdown_flag and shutdown_flag():
                logger.info(f"{task_name}: Shutdown flag detected, stopping task")
                break
            
            logger.info(f"{task_name}: Starting periodic task for all active users...")
            
            # ---- GET ALL USERS FROM RECORDS ----

            users_records_file_path = get_users_records_file_path()
            try:
                with open(users_records_file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                
                # Get bot only if it is required for task_function
                # For example, if task_function sending messages to users
                bot = application.bot if requires_bot else None
                
                # ---- PROCESS EACH USER ----

                processed_count = 0
                skipped_count = 0
                
                for bot_user_id, user_data in records.items():

                    # ---- CHECK SHUTDOWN FLAG IN LOOP for each user ----

                    if shutdown_flag and shutdown_flag():
                        logger.info(f"{task_name}: Shutdown flag detected during processing")
                        break
                    
                    try:
                        # ---- CHECK IF CONDITIONS ARE MET ----

                        if is_vacany_data_enough_for_resume_analysis(user_id=bot_user_id):
                            logger.info(f"{task_name}: Processing user {bot_user_id}")

                            # ---- EXECUTE TASK FUNCTION ----
                            if requires_bot:
                                # If bot is required, pass it to task_function
                                await task_function(bot_user_id, bot)
                            else:
                                # If bot is not required, pass only user_id to task_function
                                await task_function(bot_user_id)
                            processed_count += 1
                        else:
                            skipped_count += 1
                            logger.debug(f"{task_name}: Skipping user {bot_user_id} - filter condition are not met")
                            continue

                    except Exception as e:
                        logger.error(f"{task_name}: Error processing user {bot_user_id}: {e}", exc_info=True)
                
                logger.info(
                    f"{task_name}: Completed. Processed: {processed_count}, Skipped: {skipped_count}"
                )
                
            except Exception as e:
                logger.error(f"{task_name}: Error reading users records: {e}", exc_info=True)
                
        except asyncio.CancelledError:
            logger.info(f"{task_name}: Task cancelled")
            break
        except Exception as e:
            logger.error(f"{task_name}: Error in periodic task: {e}", exc_info=True)
            # Продолжаем выполнение даже при ошибке
            continue



