import random
from functools import wraps

import telegram.ext
from emoji import emojize
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, CallbackQueryHandler

from .manager import ManagerError
from .game import GameError, GameInstance, GameState
from .util import group_only, report_exceptions


# TODO: Replace with gettext (also wrap other strings)
def _(s):
    return emojize(s, use_aliases=True)


class UI:
    def __init__(self, bot):
        self.bot = bot

    def register_handlers(self, dispatcher: telegram.ext.Dispatcher, group=0):
        dispatcher.add_handler(CommandHandler('start_game', self._handle_start_game), group)
        dispatcher.add_handler(CommandHandler('select', self._handle_select), group)
        dispatcher.add_handler(CallbackQueryHandler(self._handle_callbacks), group)

    def start_game(self, bot: telegram.Bot, update: telegram.Update, game: GameInstance):
        if update.message.from_user != game.creator:
            raise GameError("Only creator can start the game.")
        if game.state is not GameState.NOT_STARTED:
            raise GameError("Game is already in progress.")

        game.next_state()

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Tap here", callback_data='get_role')]
        ])
        update.message.reply_text(
            _("_The game has started!_ :scream:\n\n"
              "There are *{0}* spies. Tap the button below to find out your role.")
            .format(len(game.spies)),
            parse_mode='markdown',
            reply_markup=reply_markup)

        self._show_round_info(bot, game)
        self._show_proposal_prompt(bot, game)

    def select(self, bot: telegram.Bot, update: telegram.Update, game: GameInstance):
        raw_args = [x.strip() for x in update.message.text.split()[1:]]

        party = []
        for arg in raw_args:
            if not arg:
                continue
            if arg.startswith('@'):
                username = arg[1:]
                try:
                    party.append(self.bot.users[username])
                except KeyError:
                    raise GameError("Can't propose non-registered user @{0}!".format(username))
            elif arg.isdigit():
                idx = int(arg)
                if not 1 <= idx <= len(game.players):
                    raise GameError("There is no player with index {0}.".format(idx))
                party.append(game.players[idx - 1])
            else:
                raise GameError("Invalid argument: {0}".format(arg))

        game.propose_party(update.effective_user, party)

        if game.state is GameState.PARTY_VOTE_IN_PROGRESS:
            self._show_party_vote_prompt(bot, game)

    def get_role(self, bot: telegram.Bot, update: telegram.Update, game: GameInstance):
        if game.state is GameState.NOT_STARTED:
            raise GameError("Game is not started yet!")

        response = _(":red_circle: Resistance member")
        if update.effective_user in game.spies:
            response = _(":black_circle: Spy")
            if len(game.spies) > 1:
                spy_list = ", ".join(spy.name for spy in game.spies if spy != update.effective_user)
                response += " /w {0}".format(spy_list)

        update.callback_query.answer(response)

    def party_vote(self, bot: telegram.Bot, update: telegram.Update, game: GameInstance):
        query = update.callback_query
        affirmative = query.data == 'party_vote_affirmative'
        game.vote_party(update.effective_user, affirmative)

        if affirmative:
            query.answer(_("Voted :thumbs_up:"))
        else:
            query.answer(_("Voted :thumbs_down:"))
        query.message.edit_text(UI._get_party_vote_message(game), parse_mode='markdown')

        if game.state is GameState.PARTY_VOTE_RESULTS:
            self._report_party_vote_outcome(bot, game)
            prev_round_no = len(game.rounds)
            game.next_state()

            if len(game.rounds) != prev_round_no:
                bot.send_message(
                    game.chat.id,
                    "*{0}*".format("Maximum number of failed votes reached. Spies win the round."),
                    parse_mode='markdown')
                self._show_round_info(bot, game)

            if game.state is GameState.PROPOSAL_PENDING:
                self._show_proposal_prompt(bot, game)
            elif game.state is GameState.MISSION_VOTE_IN_PROGRESS:
                self._show_mission_vote_prompt(bot, game)
            elif game.state is GameState.GAME_OVER:
                self._report_game_outcome(bot, game)
                self.bot.gm.delete_game(game.chat)

    def mission_vote(self, bot: telegram.Bot, update: telegram.Update, game: GameInstance):
        query = update.callback_query
        red = query.data == 'mission_vote_red'
        game.vote_mission(update.effective_user, red)

        if red:
            query.answer(_("Voted :red_circle:"))
        else:
            query.answer(_("Voted :black_circle:"))
        query.message.edit_text(UI._get_mission_vote_message(game), parse_mode='markdown')

        if game.state is GameState.MISSION_VOTE_RESULTS:
            self._report_mission_vote_outcome(bot, game)
            game.next_state()
            if game.state is GameState.PROPOSAL_PENDING:
                self._show_round_info(bot, game)
                self._show_proposal_prompt(bot, game)
            elif game.state is GameState.GAME_OVER:
                self._report_game_outcome(bot, game)
                self.bot.gm.delete_game(game.chat)

    def _show_round_info(self, bot: telegram.Bot, game: GameInstance):
        bot.send_message(
            game.chat.id,
            _(":black_small_square: *ROUND #{0}* :black_small_square:\n"
              "• The party must consist of *{1}* player(s).\n"
              "• Spies need to play *at least {2}* black card(s) to win.")
            .format(len(game.rounds), game.current_party_size, game.current_winning_count),
            parse_mode='markdown')

    def _show_proposal_prompt(self, bot: telegram.Bot, game: GameInstance):
        player_list = "\n".join("{0}. {1}".format(i, x.name) for i, x in enumerate(game.players, 1))
        bot.send_message(
            game.chat.id,
            _("{0}, you are the leader now.\n"
              "Please select *{1}* player(s) from the list:\n\n{2}\n\n"
              "To select a party, send /select followed by space-separated indices (or usernames) of players.")
            .format(game.leader.name, game.current_party_size, player_list),
            parse_mode='markdown'
        )

    def _show_party_vote_prompt(self, bot: telegram.Bot, game: GameInstance):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(_(":thumbs_up:"), callback_data='party_vote_affirmative'),
             InlineKeyboardButton(_(":thumbs_down:"), callback_data='party_vote_negative')]
        ])

        bot.send_message(
            game.chat.id,
            UI._get_party_vote_message(game),
            parse_mode='markdown',
            reply_markup=markup)

    def _show_mission_vote_prompt(self, bot: telegram.Bot, game: GameInstance):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(_(":red_circle:"), callback_data='mission_vote_red'),
             InlineKeyboardButton(_(":black_circle:"), callback_data='mission_vote_black')]
        ])

        bot.send_message(
            game.chat.id,
            UI._get_mission_vote_message(game),
            parse_mode='markdown',
            reply_markup=markup)

    def _report_party_vote_outcome(self, bot: telegram.Bot, game: GameInstance):
        caption = "Vote succeeded!" if game.current_vote.outcome else "Vote failed."

        vote_list = "\n".join(
            "{0}: {1}".format(
                player.name,
                _(":thumbs_up:") if ballot else _(":thumbs_down:"))
            for player, ballot in game.current_vote.ballots.items())

        bot.send_message(game.chat.id, "*{0}*\n{1}".format(caption, vote_list), parse_mode='markdown')

    def _report_mission_vote_outcome(self, bot: telegram.Bot, game: GameInstance):
        caption = "{0} won the round.".format("Resistance" if game.current_round.outcome else "Spies")

        votes = list(game.current_round.ballots.values())
        random.shuffle(votes)
        vote_list = "".join(_(":red_circle:") if x else _(":black_circle:") for x in votes)

        bot.send_message(game.chat.id, "*{0}*\n{1}".format(caption, vote_list), parse_mode='markdown')

    def _report_game_outcome(self, bot: telegram.Bot, game: GameInstance):
        message = "Spies won the game!"
        if game.outcome:
            message = "Resistance won the game!"
        bot.send_message(game.chat.id, "*{0}*".format(message), parse_mode='markdown')

    @group_only
    @report_exceptions(GameError, ManagerError)
    def _handle_start_game(self, bot: telegram.Bot, update: telegram.Update):
        self._ingame(self.start_game)(bot, update)

    @group_only
    @report_exceptions(GameError, ManagerError)
    def _handle_select(self, bot: telegram.Bot, update: telegram.Update):
        self._ingame(self.select)(bot, update)

    @report_exceptions(GameError, ManagerError)
    def _handle_callbacks(self, bot: telegram.Bot, update: telegram.Update):
        if update.callback_query.data == 'get_role':
            self._ingame(self.get_role)(bot, update)
        elif update.callback_query.data.startswith('party_vote'):
            self._ingame(self.party_vote)(bot, update)
        elif update.callback_query.data.startswith('mission_vote'):
            self._ingame(self.mission_vote)(bot, update)

    def _ingame(self, handler):
        @wraps(handler)
        def wrapped_handler(bot: telegram.Bot, update: telegram.Update):
            game = self.bot.gm.get_game(update.effective_chat)
            if update.effective_user not in game.players:
                raise GameError("You are not registered!")
            handler(bot, update, game)
        return wrapped_handler

    @staticmethod
    def _get_party_vote_message(game: GameInstance):
        return _(
            ":black_small_square: *VOTING* :black_small_square:\n"
            "Please vote for party proposal: {0}\n\n"
            "*{1}* out of *{2}* player(s) voted."
        ).format(
            ", ".join(x.name for x in game.current_party),
            len(game.current_vote.ballots),
            len(game.players)
        )

    @staticmethod
    def _get_mission_vote_message(game: GameInstance):
        return _(
            ":black_small_square: *MISSION* :black_small_square:\n"
            "Party members, please vote.\n"
            "Spies can play both colors, resistance members can only play red.\n\n"
            "*{0}* out of *{1}* player(s) voted."
        ).format(
            len(game.current_round.ballots),
            game.current_party_size
        )
