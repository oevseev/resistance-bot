import logging
from typing import Dict

import telegram
from telegram.ext import CommandHandler

from .game import GameError, GameInstance
from .util import group_only, report_exceptions


logger = logging.getLogger(__name__)


class ManagerError(Exception):
    pass


class GameManager:
    def __init__(self, bot):
        self.bot = bot
        self.games: Dict[telegram.Chat, GameInstance] = {}

    def register_handlers(self, dispatcher: telegram.ext.Dispatcher, group=0):
        dispatcher.add_handler(CommandHandler('new_game', self._handle_new_game), group)
        dispatcher.add_handler(CommandHandler('cancel_game', self._handle_cancel_game), group)
        dispatcher.add_handler(CommandHandler('register', self._handle_register), group)

    def get_game(self, chat: telegram.Chat):
        if chat not in self.games:
            raise ManagerError(_("There is no game for this chat."))
        return self.games[chat]

    def create_game(self, chat: telegram.Chat, creator: telegram.User):
        if chat in self.games:
            raise ManagerError(_("There already exists a game for this chat."))

        self.games[chat] = GameInstance(chat, creator)
        logger.info("User %s created a game for chat %s", creator.name, chat.id)

        return self.games[chat]

    def delete_game(self, chat: telegram.Chat):
        self.games.pop(chat, None)
        logger.info("Deleted game for chat %s", chat.id)

    def add_player(self, chat: telegram.Chat, user: telegram.User):
        self.get_game(chat).register_player(user)

    @group_only
    @report_exceptions(GameError, ManagerError)
    def _handle_new_game(self, bot: telegram.Bot, update: telegram.Update):
        self.create_game(update.effective_chat, creator=update.effective_user)
        update.message.reply_text("The game is created. Send /register to register.")

    @group_only
    @report_exceptions(GameError, ManagerError)
    def _handle_cancel_game(self, bot: telegram.Bot, update: telegram.Update):
        game = self.get_game(update.effective_chat)
        if game.creator == update.effective_user:
            self.delete_game(update.effective_chat)
            update.message.reply_text("The game is cancelled.")
        else:
            update.message.reply_text("Only creator can cancel the game.")

    @group_only
    @report_exceptions(GameError, ManagerError)
    def _handle_register(self, bot: telegram.Bot, update: telegram.Update):
        self.add_player(update.effective_chat, update.effective_user)
        update.message.reply_text("You are registered now.")
