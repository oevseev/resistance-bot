import logging
from typing import Dict

import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

from .manager import GameManager
from .ui import UI


logger = logging.getLogger(__name__)


def display_start_message(bot, update):
    update.message.reply_text(
        "*Welcome to Resistance Game Bot!*\n"
        "Please _add this bot to a group_ and send /new\\_game to start a new game.",
        parse_mode='markdown')


class ResistanceBot:
    def __init__(self, token: str, request_kwargs=None):
        self.gm = GameManager(self)
        self.ui = UI(self)
        self.users: Dict[str, telegram.User] = {}
        self._updater = Updater(token, request_kwargs=request_kwargs)

        dispatcher = self._updater.dispatcher
        self.gm.register_handlers(dispatcher, group=1)
        self.ui.register_handlers(dispatcher, group=2)

        dispatcher.add_handler(MessageHandler(Filters.all, self._update_username), group=-1)
        dispatcher.add_handler(CommandHandler('start', self._handle_start))
        dispatcher.add_error_handler(self._handle_error)

    def run(self):
        self._updater.start_polling()
        self._updater.idle()

    def _update_username(self, bot: telegram.Bot, update: telegram.Update):
        if update.effective_user.username:
            self.users[update.effective_user.username] = update.effective_user

    def _handle_start(self, bot: telegram.Bot, update: telegram.Update):
        display_start_message(bot, update)

    def _handle_error(self, bot: telegram.Bot, update: telegram.Update, error: telegram.TelegramError):
        logger.warning('Update "%s" caused error "%s"', update, error)
