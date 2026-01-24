# manager_bot package
# This file makes manager_bot a Python package

"""manager_bot package.

This file makes manager_bot a Python package and re-exports selected
functions so that other modules (e.g. shared_services.video_service)
can import them as `from manager_bot import ...`.
"""

# Import and re-export commonly used functions and variables
from .manager_bot import (
    create_manager_application,
    ai_task_queue,
    start_command,
    ask_confirm_sending_video_command,
    read_vacancy_description_command,
)

__all__ = [
    "create_manager_application",
    "ai_task_queue",
    "start_command",
    "ask_confirm_sending_video_command",
    "read_vacancy_description_command",
]
