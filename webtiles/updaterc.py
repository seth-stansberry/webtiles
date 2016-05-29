#!/usr/bin/env python3

"""Update RC files on a WebTiles account for a set of games and servers.

"""

import argparse
import asyncio
import getpass
import logging
import os
import os.path
import re
import sys
from urllib.parse import urlparse
from webtiles import WebTilesConnection

_log = logging.getLogger()
_log.setLevel(logging.INFO)
_log.addHandler(logging.StreamHandler())

class RCUpdater(WebTilesConnection):

    def __init__(self, websocket_url, username, password, update_games,
                 rc_text):
        super().__init__()
        self.websocket_url = websocket_url
        self.username = username
        self.password = password
        self.update_games = update_games
        self.rc_text = rc_text

    @asyncio.coroutine
    def start(self):
        """Connect to the WebTiles server, then proceed to read and handle
        messages. When the game list is received, try to update the RC file.

        """

        yield from self.connect(self.websocket_url, self.username,
                                self.password)

        while True:
            messages = yield from self.read()

            if not messages:
                return

            for message in messages:
                yield from self.handle_message(message)

            # Do the updates only after the game data is received from the
            # server.
            if not self.games:
                continue

            matching_games = {}
            for game in self.update_games:
                matching_game = None
                for server_game in self.games:
                    game_pattern = r"DCSS.*{}".format(game)
                    match = re.search(game_pattern, server_game,
                                      flags=re.IGNORECASE)
                    if match:
                        matching_game = server_game
                        break

                if not matching_game:
                    yield from self.disconnect()
                    raise Exception("Game {} not found on server".format(game))

                matching_games[game] = server_game

            for game in self.update_games:
                yield from self.update_rc(self.games[matching_games[game]],
                                          self.rc_text)
            yield from self.disconnect()
            return

    def handle_message(self, message):
        yield from super().handle_message(message)

        if message["msg"] == "login_fail":
            yield from self.disconnect()
            raise Exception("Login failed.")


@asyncio.coroutine
def run_updates(server_urls, username, password, update_games, rc_text):
    """Handle the update to each server."""

    for url in server_urls:
        hostname = urlparse(url).hostname
        _log.info("Updating server %s", hostname)
        updater = RCUpdater(url, username, password, update_games, rc_text)

        try:
            yield from updater.start()
        except Exception as e:
            err_reason = type(e).__name__
            if e.args:
                err_reason = e.args[0]
            _log.error("Unable to update RC at %s: %s", url, err_reason)
            sys.exit(1)

    _log.info("Updates complete")


def main():
    known_servers = {
        "cao"  : "ws://crawl.akrasiac.org:8080/socket",
        "cbro" : "ws://crawl.berotato.org:8080/socket",
        "cjr"  : "wss://crawl.jorgrun.rocks:8081/socket",
        "cue"  : "ws://www.underhound.eu:8080/socket",
        "cwz"  : "ws://webzook.net:8080/socket",
        "cxc"  : "ws://crawl.xtahua.com:8080/socket",
        "lld"  : "ws://lazy-life.ddo.jp:8080/socket",
    }

    server_codes = ", ".join(sorted(known_servers.keys()))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("servers", nargs='+',
                        metavar="<server-code|websocket-url>",
                        help="Servers to update, each a websocket URL or one "
                        "of: {}".format(server_codes))
    parser.add_argument("-f", dest="rc_file", metavar="<rc-file>",
                        default=None, help="The rc file to use.")
    parser.add_argument("-u", dest="username", metavar="<username>",
                        help="The account username.", default=None)
    parser.add_argument("-p", dest="password", metavar="<password>",
                        help="The account password.", default=None)
    parser.add_argument("-g", dest="games", metavar="<game1>[,<game2>,...]",
                        help="Comma-seperated list of games to update "
                        "(default: %(default)s).", default="trunk")
    args = parser.parse_args()

    rc_file = args.rc_file
    if rc_file is None:
        if os.path.isfile(os.environ["HOME"] + "/.crawl/init.txt"):
            rc_file = os.environ["HOME"] + "/.crawl/init.txt"
        elif os.path.isfile(os.environ["HOME"] + "/.crawlrc"):
            rc_file = os.environ["HOME"] + "/.crawlrc"
        else:
            _log.error("No Crawl RC found and none given with -f")
            sys.exit(1)

    update_urls = []
    for server in args.servers:
        if re.match("wss?://", server, re.I):
            update_urls.append(server)
        elif server in known_servers:
            update_urls.append(known_servers[server])
        else:
            _log.error("Unrecognized server: %s", server)
            sys.exit(1)

    update_games = args.games.split(",")

    username = args.username
    if not username:
        while not username:
            try:
                username = input("Crawl username: ")
            except:
                sys.exit(1)

    password = args.password
    if not password:
        while not password:
            try:
                password = getpass.getpass("Crawl password: ")
            except:
                sys.exit(1)

    rc_fh = open(rc_file, "rU")
    rc_text = rc_fh.read()
    _log.info("Read %s bytes from file %s", len(rc_text), rc_file)

    _log.info("Updating RC of user %s for game(s): %s", username,
              ", ".join(update_games))
    ioloop = asyncio.get_event_loop()
    ioloop.run_until_complete(run_updates(update_urls, username, password,
                                          update_games, rc_text))
