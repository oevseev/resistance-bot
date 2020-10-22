import os
import logging

from resistance_bot import ResistanceBot


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def main():
    logging.basicConfig(format=LOG_FORMAT, level=logging.DEBUG)
    bot = ResistanceBot(os.environ.get('RESISTANCE_BOT_TOKEN'))
    bot.run()


if __name__ == '__main__':
    main()
