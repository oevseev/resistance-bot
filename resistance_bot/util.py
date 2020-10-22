import logging
from functools import wraps

import telegram
from telegram.ext import CallbackContext


logger = logging.getLogger(__name__)


def group_only(handler):
    @wraps(handler)
    def decorated_handler(self, update: telegram.Update, context: CallbackContext):
        if update.message.chat.type not in ['group', 'supergroup']:
            update.message.reply_text("Add this bot to a group to play!")
            return
        handler(self, update, context)

    return decorated_handler


def report_exceptions(*args):
    def decorator(handler):
        @wraps(handler)
        def decorated_handler(self, update: telegram.Update, context: CallbackContext):
            try:
                handler(self, update, context)
            except BaseException as e:
                if any(isinstance(e, x) for x in args):
                    if update.callback_query is not None:
                        update.callback_query.answer(str(e))
                    elif update.message is not None:
                        update.message.reply_text(str(e))
                    logger.debug('Exception redirected to sender: "%s"', e)
                else:
                    raise

        return decorated_handler

    return decorator
