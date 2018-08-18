import logging

from resistance_bot import ResistanceBot


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
TOKEN = 'TOKEN'


def main():
    logging.basicConfig(format=LOG_FORMAT, level=logging.DEBUG)
    bot = ResistanceBot(TOKEN)
    bot.run()


if __name__ == '__main__':
    main()
