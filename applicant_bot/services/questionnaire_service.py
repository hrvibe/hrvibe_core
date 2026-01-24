from typing import List, Tuple, Optional
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

from services.data_service import (
    add_persistent_keyboard_message,
    remove_persistent_keyboard_message,
    get_persistent_keyboard_messages,
    clear_all_persistent_keyboard_messages,
)


def _track_message_with_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    """Track a message with an inline keyboard for later removal (both session and persistent storage)."""
    # Track in session (context.user_data)
    if "messages_with_keyboards" not in context.user_data:
        context.user_data["messages_with_keyboards"] = []
    if (chat_id, message_id) not in context.user_data["messages_with_keyboards"]:
        context.user_data["messages_with_keyboards"].append((chat_id, message_id))
    
    # Track in persistent storage
    applicant_record_id = update.effective_user.id if update.effective_user else None
    if applicant_record_id:
        add_persistent_keyboard_message(
            applicant_record_id=str(applicant_record_id),
            chat_id=chat_id,
            message_id=message_id
        )


def _remove_message_from_keyboard_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    """Remove a message from keyboard tracking (both session and persistent storage)."""
    # Remove from session
    if "messages_with_keyboards" in context.user_data:
        messages = context.user_data["messages_with_keyboards"]
        context.user_data["messages_with_keyboards"] = [
            (c_id, m_id) for c_id, m_id in messages if not (c_id == chat_id and m_id == message_id)
        ]
    
    # Remove from persistent storage
    applicant_record_id = update.effective_user.id if update.effective_user else None
    if applicant_record_id:
        remove_persistent_keyboard_message(
            applicant_record_id=str(applicant_record_id),
            chat_id=chat_id,
            message_id=message_id
        )


async def clear_all_unprocessed_keyboards(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Clear all unprocessed inline keyboards for a user (both session and persistent storage).
    Args:
        update: Telegram Update object (needed to get applicant_record_id)
        context: Telegram Context object
        chat_id: Chat ID to clear keyboards for
    """
    applicant_record_id = update.effective_user.id if update.effective_user else None
    if not applicant_record_id:
        logger.debug("Cannot clear keyboards: no applicant_record_id found")
        return
    
    # Collect messages from both session and persistent storage
    messages_to_clear = set()
    
    # Get from session
    if "messages_with_keyboards" in context.user_data:
        for msg_chat_id, message_id in context.user_data["messages_with_keyboards"]:
            if msg_chat_id == chat_id:
                messages_to_clear.add((msg_chat_id, message_id))
    
    # Get from persistent storage
    persistent_messages = get_persistent_keyboard_messages(
        applicant_record_id=str(applicant_record_id)
    )
    for msg_chat_id, message_id in persistent_messages:
        if msg_chat_id == chat_id:
            messages_to_clear.add((msg_chat_id, message_id))
    
    # Clear all collected keyboards
    cleared_count = 0
    for msg_chat_id, message_id in messages_to_clear:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=msg_chat_id,
                message_id=message_id,
                reply_markup=None
            )
            cleared_count += 1
        except Exception as e:
            # Message might have been deleted or keyboard already removed
            logger.debug(f"Could not clear keyboard for message {message_id}: {e}")
            pass
    
    # Clear session tracking
    if "messages_with_keyboards" in context.user_data:
        context.user_data["messages_with_keyboards"] = []
    
    # Clear persistent storage
    clear_all_persistent_keyboard_messages(
        applicant_record_id=str(applicant_record_id)
    )
    
    if cleared_count > 0:
        logger.debug(f"Cleared {cleared_count} unprocessed keyboard(s) (session + persistent)")


async def send_message_to_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: Optional[ParseMode] = None,
    disable_web_page_preview: Optional[bool] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """
    Send a message to Telegram user handling all possible edge cases. This method safely handles:
    1. Callback queries (when user clicks a button) - uses callback_query.message
    2. Regular messages (when user sends text/command) - uses update.message
    3. Edge cases (when neither is available) - uses context.bot.send_message
    Args:
        update: Telegram Update object
        context: Telegram Context object
        text: The message text to send
        parse_mode: Optional parse mode (HTML, Markdown, etc.)
        disable_web_page_preview: Optional flag to disable web page preview
        reply_markup: Optional inline keyboard markup  
    Returns:
        The sent Message object, or None if message couldn't be sent

    """
    # Try to get message object from callback_query first (button clicks)
    if update.callback_query and update.callback_query.message:
        message = update.callback_query.message
        # Build kwargs for reply_text
        kwargs = {}
        if parse_mode is not None:
            kwargs['parse_mode'] = parse_mode
        if disable_web_page_preview is not None:
            kwargs['disable_web_page_preview'] = disable_web_page_preview
        if reply_markup is not None:
            kwargs['reply_markup'] = reply_markup
        
        sent_message = await message.reply_text(text, **kwargs)
        # Track message with keyboard if reply_markup is provided
        if reply_markup is not None and sent_message:
            _track_message_with_keyboard(update, context, sent_message.chat.id, sent_message.message_id)
        return sent_message
    
    # Try to get message object from regular message (text/command)
    elif update.message:
        message = update.message
        # Build kwargs for reply_text
        kwargs = {}
        if parse_mode is not None:
            kwargs['parse_mode'] = parse_mode
        if disable_web_page_preview is not None:
            kwargs['disable_web_page_preview'] = disable_web_page_preview
        if reply_markup is not None:
            kwargs['reply_markup'] = reply_markup
        
        sent_message = await message.reply_text(text, **kwargs)
        # Track message with keyboard if reply_markup is provided
        if reply_markup is not None and sent_message:
            _track_message_with_keyboard(update, context, sent_message.chat.id, sent_message.message_id)
        return sent_message
    
    # Fallback: send message directly using context.bot.send_message
    # This handles edge cases where neither callback_query nor message is available
    else:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id:
            # Build kwargs for send_message
            kwargs = {
                'chat_id': user_id,
                'text': text
            }
            if parse_mode is not None:
                kwargs['parse_mode'] = parse_mode
            if disable_web_page_preview is not None:
                kwargs['disable_web_page_preview'] = disable_web_page_preview
            if reply_markup is not None:
                kwargs['reply_markup'] = reply_markup
            
            sent_message = await context.bot.send_message(**kwargs)
            # Track message with keyboard if reply_markup is provided
            if reply_markup is not None and sent_message:
                _track_message_with_keyboard(update, context, sent_message.chat.id, sent_message.message_id)
            return sent_message
    
    # If we couldn't send the message (no user_id, etc.), return None
    logger.warning("send_message_to_user: No message object found, returning None")
    return None


async def ask_question_with_options(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question_text: str,
    answer_options: List[Tuple[str, str]],) -> None:
    """
    Ask a question with multiple choice options as vertical buttons.
    Args:
        update: Telegram Update object
        context: Telegram Context object
        question_text: The question text to display
        options: List of tuples where each tuple is (button_text, callback_data)
                Example: [("Option 1", "opt_1"), ("Option 2", "opt_2")]
    """
    
    # -------- BUILD KEYBOARD with vertical buttons (each button in its own row) --------
    
    keyboard = []
    # Buttons text will be the 1st itme in the tuple, callback_data will be the 2nd item in the tuple
    for button_text, callback_code in answer_options:
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_code)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # What happens when user clicks a button?
    # User clicked button => Telegram sends action "CallbackQuery" => "update" object has callback_query attribute
    # "update.callback_query" contains many attributes, but the most important are: (https://core.telegram.org/bots/api#callbackquery):
    #  - "update.callback_query.data" - this is wahat you called "callback_data" when created buttons above
    #  - "update.callback_query.message.text" - this is the text of the message that had the button
    #  IMPORTANT: "update.callback_query" DOES NOT contain "button_text" visible for user.
    
    # -------- ASK QUESTION using send_message_to_user which handles all edge cases --------
    
    # send_message_to_user handles:
    # 1. Callback queries (when user clicks a button) - uses callback_query.message
    # 2. Regular messages (when user sends text/command) - uses update.message
    # 3. Edge cases (when neither is available) - uses context.bot.send_message
    # Note: send_message_to_user will automatically track this message with keyboard
    await send_message_to_user(
        update=update,
        context=context,
        text=question_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, remove_keyboard: bool = True,) -> Optional[str]:
    """
    Handle the answer from a questionnaire question (button click).
    Args:
        update: Telegram Update object (must contain callback_query)
        context: Telegram Context object
        remove_keyboard: If True, removes the inline keyboard after selection
    Returns:
        The callback_data string from the selected button, or None if no callback_query
    """

    # What happens when user clicks a button?
    # User clicked button => Telegram sends action "CallbackQuery" => "update" object has callback_query attribute
    # "update.callback_query" contains many attributes, but the most important are: (https://core.telegram.org/bots/api#callbackquery):
    #  - "update.callback_query.data" - this is wahat you called "callback_data" when created buttons above
    #  - "update.callback_query.message.text" - this is the text of the message that had the button
    #  IMPORTANT: "update.callback_query" DOES NOT contain "button_text" visible for user.
    
    
    # -------- UNDERSTAND WHAT BUTTON was clicked --------

    # store "update.callback_query" object in "query" variable
    query = update.callback_query
    # from "update.callback_queert" (stoed in "query" variable) get "data" attribute, this is wahat you called "callback_data" when created buttons above
    callback_data = query.data
    
    # -------- STOP SHOWING spinner (loading icon) on the button --------

    # Answer the callback query (required by Telegram API) to confirm that click was received
    # This will stop showing the loading spinner on the button.
    await query.answer()
    
    # -------- REMOVE KEYBOARD (buttons) --------

    #"remove_keyboard" argument was defined as "True"
    if remove_keyboard:
        try:
            # Remove the keyboard (buttons) from the message
            await query.edit_message_reply_markup(reply_markup=None)
            # Remove from tracking since keyboard is now removed
            _remove_message_from_keyboard_tracking(update, context, query.message.chat.id, query.message.message_id)
        except Exception:
            # If edit fails (keyboard already removed, etc.), continue
            pass

    # -------- RETURN callback_data --------
    
    return callback_data

    