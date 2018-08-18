import logging
import random
from enum import Enum
from typing import Dict, List, Optional

import telegram


MIN_PLAYERS, MAX_PLAYERS = 5, 10

# Party size per round for every possible player count
PARTY_SIZES = {
    5: [2, 3, 2, 3, 3],
    6: [2, 3, 4, 3, 4],
    7: [2, 3, 3, 4, 4],
    8: [3, 4, 4, 5, 5],
    9: [3, 4, 4, 5, 5],
    10: [3, 4, 4, 5, 5]
}

# Number of rounds the side needs to win to win the game
WIN_LIMIT = 3

# Maximum number of failed votes per round. When reached, spies win the round
VOTE_LIMIT = 5

# Minimum number of players that enables the rule which states that the spies must play
# at least 2 black cards in the 4th round to win it
MIN_2IN4TH = 7


logger = logging.getLogger(__name__)


class GameError(Exception):
    pass


class GameState(Enum):
    NOT_STARTED = 0
    PROPOSAL_PENDING = 1
    PARTY_VOTE_IN_PROGRESS = 2
    PARTY_VOTE_RESULTS = 3
    MISSION_VOTE_IN_PROGRESS = 4
    MISSION_VOTE_RESULTS = 5
    GAME_OVER = 6


class Vote:
    def __init__(self, party: List[telegram.User]):
        self.party = party
        self.ballots: Dict[telegram.User, bool] = {}

    @property
    def outcome(self):
        # Party is appointed if the majority of players voted affirmative
        values = list(self.ballots.values())
        return values.count(True) > values.count(False)


class Round:
    def __init__(self, winning_count: int):
        self.winning_count = winning_count
        self.votes: List[Vote] = []
        self.ballots: Dict[telegram.User, bool] = {}

    @property
    def last_vote(self):
        if self.votes:
            return self.votes[-1]
        return None

    @property
    def can_vote(self):
        return len(self.votes) < VOTE_LIMIT

    @property
    def outcome(self):
        # Spies win if vote limit is exceeded
        if not self.can_vote:
            return False

        # Spies win if they deal a needed number of black cards
        return list(self.ballots.values()).count(False) < self.winning_count


class GameInstance:
    def __init__(self, chat: telegram.Chat, creator: Optional[telegram.User] = None):
        self.chat = chat
        self.creator = creator
        self.state = GameState.NOT_STARTED
        self.players: List[telegram.User] = []
        self.spies: List[telegram.User] = []
        self.rounds: List[Round] = []
        self._leader_idx = -1

    def next_state(self):
        if self.state is GameState.NOT_STARTED:
            if not MIN_PLAYERS <= len(self.players) <= MAX_PLAYERS:
                raise GameError("The number of players must be between {0} and {1}!".format(MIN_PLAYERS, MAX_PLAYERS))
            self._assign_spies()
            self._next_round_or_gameover()

        elif self.state is GameState.PARTY_VOTE_RESULTS:
            if self.current_vote.outcome:
                self.state = GameState.MISSION_VOTE_IN_PROGRESS
            else:
                self._next_leader()
                if self.current_round.can_vote:
                    self.state = GameState.PROPOSAL_PENDING
                else:
                    self._next_round_or_gameover()

        elif self.state is GameState.MISSION_VOTE_RESULTS:
            self._next_leader()
            self._next_round_or_gameover()

        else:
            raise GameError("Current game state ({0}) is changed automatically.".format(self.state))

    def register_player(self, user: telegram.User):
        if self.state != GameState.NOT_STARTED:
            raise GameError("Can't register for an already started game!")

        # Should work fine as telegram.User compares user ids, not internal Python ids
        if user in self.players:
            raise GameError("Can't register twice!")

        self.players.append(user)
        self._log("Registered player %s", user.name)

    def propose_party(self, user: telegram.User, users: List[telegram.User]):
        self._assert_registered(user)

        if self.state != GameState.PROPOSAL_PENDING:
            raise GameError("Party proposal not pending!")
        if user != self.leader:
            raise GameError("Only leader can propose a party!")
        if len(users) != self.current_party_size:
            raise GameError("Party must have {0} members!".format(self.current_party_size))

        for user in users:
            if user not in self.players:
                raise GameError("Can't propose non-registered user {0}!".format(user.name))

        self.current_round.votes.append(Vote(users))
        self.state = GameState.PARTY_VOTE_IN_PROGRESS

    def vote_party(self, user: telegram.User, outcome: bool):
        self._assert_registered(user)

        if self.state != GameState.PARTY_VOTE_IN_PROGRESS:
            raise GameError("Party vote not in progress!")
        if user in self.current_vote.ballots:
            raise GameError("Can't vote twice!")

        self.current_vote.ballots[user] = outcome
        self._log("User %s votes %s", user.name, "affirmative" if outcome else "negative")

        # Proceed to the next state when all players voted
        if len(self.current_vote.ballots) >= len(self.players):
            self.state = GameState.PARTY_VOTE_RESULTS
            self._log("Vote over: party is %s", "appointed" if self.current_vote.outcome else "rejected")

    def vote_mission(self, user: telegram.User, outcome: bool):
        self._assert_registered(user)

        if self.state != GameState.MISSION_VOTE_IN_PROGRESS:
            raise GameError("Mission vote not in progress!")
        if user in self.current_round.ballots:
            raise GameError("Can't vote twice!")

        if user not in self.current_party:
            raise GameError("Only party members can vote!")
        if not outcome and user not in self.spies:
            raise GameError("Only spies can vote black!")

        self.current_round.ballots[user] = outcome
        self._log("User %s votes %s", user.name, "red" if outcome else "black")

        if len(self.current_round.ballots) >= self.current_party_size:
            self.state = GameState.MISSION_VOTE_RESULTS
            self._log("Round over: mission %s", "successful" if self.current_round.outcome else "failed")

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value: GameState):
        self._state = value
        self._log("State is now %s", value)

    @property
    def current_round(self):
        if self.state not in [GameState.NOT_STARTED, GameState.GAME_OVER]:
            return self.rounds[-1]
        return None

    @property
    def current_vote(self):
        if self.state in [GameState.PARTY_VOTE_IN_PROGRESS, GameState.PARTY_VOTE_RESULTS]:
            return self.current_round.last_vote
        return None

    @property
    def current_party(self):
        if self.state in [GameState.PARTY_VOTE_IN_PROGRESS, GameState.PARTY_VOTE_RESULTS,
                          GameState.MISSION_VOTE_IN_PROGRESS, GameState.MISSION_VOTE_RESULTS]:
            return self.current_round.last_vote.party
        return None

    @property
    def current_party_size(self):
        if self.state not in [GameState.NOT_STARTED, GameState.GAME_OVER]:
            round_idx = len(self.rounds) - 1
            return PARTY_SIZES[len(self.players)][round_idx]
        return None

    @property
    def current_winning_count(self):
        if self.state not in [GameState.NOT_STARTED, GameState.GAME_OVER]:
            return self.current_round.winning_count
        return None

    @property
    def leader(self):
        if self.state not in [GameState.NOT_STARTED, GameState.GAME_OVER]:
            return self.players[self._leader_idx]
        return None

    @property
    def outcome(self):
        outcomes = [x.outcome for x in self.rounds]
        resistance_wins = outcomes.count(True)
        spy_wins = outcomes.count(False)

        if resistance_wins >= WIN_LIMIT:
            return True
        elif spy_wins >= WIN_LIMIT:
            return False
        return None

    def _assert_registered(self, user: telegram.User):
        if user not in self.players:
            raise GameError("You are not registered!")

    def _assign_spies(self):
        # According to the official rules, one third of players (rounded up) are spies
        spy_count = (len(self.players) + 2) // 3

        self.spies = random.sample(self.players, spy_count)
        self._log("Spies appointed: %s", list(x.name for x in self.spies))

    def _next_leader(self):
        self._leader_idx = (self._leader_idx + 1) % len(self.players)

    def _next_round_or_gameover(self):
        if self.outcome is None:
            winning_count = 1
            if len(self.players) >= MIN_2IN4TH and len(self.rounds) == 3:
                winning_count = 2
            self.rounds.append(Round(winning_count))

            self.state = GameState.PROPOSAL_PENDING
            self._log("Round %s begins", len(self.rounds))

        else:
            self.state = GameState.GAME_OVER
            self._log("The game is over: %s", "resistance wins" if self.outcome else "spies win")

    def _log(self, message: str, *args):
        logger.info("[chat.id: {0}] {1}".format(self.chat.id, message), *args)
