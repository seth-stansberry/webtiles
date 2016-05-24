"""
A WebTiles library for python

"""

import asyncio
import json
import logging
import re
import sys
import time
import websockets
import zlib

_log = logging.getLogger("webtiles")

class WebTilesError(Exception):
    pass

class WebTilesConnection():
    """A base clase for a connection to a WebTiles server. Inherit from this and
    extend `handle_message()` to handle additional message types or process
    those that `WebTilesConnection` already handles. This class handles
    connecting, logging in, getting a list of games, lobby data, and setting rc
    files.

    The `websocket` property holds the websocket instance and `websocket_url`
    the url of the current connection. When logged in through either
    `connect()` or `send_login()`, the `logged_in` property will be true, and
    `username` will hold the current username. The game list is only received
    after login, and is a dict in the `games` property with each key a
    descriptive name and each value a game type id. The game id is used when
    playing and setting the rc file.

    For lobby data, `lobby_complete` will be True when the server indicates
    that it's sent a complete set of entries.. Lobby entries are available in
    `lobby_entries` and can be retrieved by game username and game id with
    `get_entry()`. Each entry is a dictionary with keys 'username', 'game_id',
    'id' (a unique game identifier used by the server), 'idle_time', and
    'spectator_count'. Additionally the key 'time_last_update' has the time of
    the last update to the entry.

    Some errors will raise `WebTilesError`, where the first exception argument
    will be an error message.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decomp = zlib.decompressobj(-zlib.MAX_WBITS)
        self.websocket = None
        self.logged_in = False
        self.websocket_url = None
        self.username = None
        self.password = None
        self.games = {}
        self.lobby_entries = []
        self.lobby_complete = False


    @asyncio.coroutine
    def connect(self, websocket_url, username=None, password=None, *args,
                **kwargs):
        """Connect to the given websocket URL with optional
        credentials. Additional arguments are passed to `webscokets.connect()`.

        """

        if username and not password:
            raise WebTilesError("Username given but no password given.")

        if self.connected():
            raise WebTilesError("Attempted to connect when already connected.")

        self.websocket = yield from websockets.connect(websocket_url, *args,
                                                       **kwargs)
        self.websocket_url = websocket_url
        if username:
            yield from self.send_login(username, password)
            self.username = username
            self.password = password

    @asyncio.coroutine
    def send_login(self, username, password):
        """Send the login message. This is usally called by `connect()`, but the
        `send_login()` method can be used to authenticate after connecting
        without credentials. The `logged_in` property will only be True after
        the server responds with a "login_complete" message when this is
        handled by `handle_message()`.

        """

        yield from self.send({"msg"      : "login",
                              "username" : username,
                              "password" : password})
        self.logged_in = False
        self.username = username
        self.password = password

    def connected(self):
        """Return true if the websocket is connected."""

        return self.websocket and self.websocket.open

    @asyncio.coroutine
    def disconnect(self):
        """Close the websocket if it's open and reset the connection state"""

        if self.websocket:
            yield from self.websocket.close()
        self.websocket = None
        self.logged_in = False
        self.games = {}
        self.lobby_entries = []
        self.lobby_complete = False

    @asyncio.coroutine
    def read(self):
        """Read a WebSocket message, returning a list of message
        dictionaries. Each dict will have a "msg" component with the type of
        message along with any other message-specific details. The message will
        have. Returns None if we can't parse the JSON, since some older game
        versions send bad messages we need to ignore.

        """

        comp_data = yield from self.websocket.recv()
        comp_data += bytes([0, 0, 255, 255])
        json_message = self.decomp.decompress(comp_data)
        json_message = json_message.decode("utf-8")

        try:
            message = json.loads(json_message)
        except ValueError as e:
            # Invalid JSON happens with data sent from older games (0.11 and
            # below), so don't spam the log with these. XXX can we ignore only
            # those messages and log other parsing errors?
            _log.debug("Ignoring unparseable JSON (error: %s): %s.", e.args[0],
                       json_message)
            return

        if "msgs" in message:
            messages = message["msgs"]
        elif "msg" in message:
            messages = [message]
        else:
            raise WebTilesError("JSON doesn't define either 'msg' or 'msgs'")

        return messages

    def get_lobby_entry(self, username, game_id):
        """Get the lobby entry of a game from `lobby_entries`. """

        for entry in self.lobby_entries:
            if entry["username"] == username and entry["game_id"] == game_id:
                return entry
        return

    @asyncio.coroutine
    def update_rc(self, game_id, rc_text):
        """Update the user's RC file on the server. If the connection isn't logged
        in, raise an exception.

        """

        if not self.logged_in:
            raise WebTilesError(
                "Attempted to send RC update when not logged in")

        yield from self.send({"msg"      : "set_rc",
                              "game_id"  : game_id,
                              "contents" : rc_text})

    @asyncio.coroutine
    def send(self, message):
        """Send a message dictionary to the server. The message should be a dict
        with a 'msg' key having a webtiles message type.

        """

        if "msg" not in message:
            raise WebTilesError("Message dict must contain a 'msg' key")

        yield from self.websocket.send(json.dumps(message))

    @asyncio.coroutine
    def handle_message(self, message):
        """Given a response message dictionary, handle the message. Returns True
        if the message is handled by this handler. This method can be extended
        in derived classes to handle other message types or to additional
        handling, but it must be called for the following message types in
        order to manage connect state properly: "login_success",
        "set_game_links", "lobby_entry", "lobby_remove", "lobby_clear",
        "lobby_complete".

        This method doesn't handle the 'login_fail' message type when
        authentication is rejected.

        """

        if message["msg"] == "ping":
            yield from self.send({"msg" : "pong"})
            return True

        if message["msg"] == "login_success":
            self.logged_in = True
            return True

        if message["msg"] == "set_game_links":
            game_pattern = r'<a href="#play-([^"]+)">([^>]+)</a>'
            self.games = {}
            for m in re.finditer(game_pattern, message["content"]):
                game_id = m.group(1)
                game_name = m.group(2)
                self.games[game_name] = game_id
            return True


        if message["msg"] == "lobby_entry":
            entry = self.get_lobby_entry(message["username"],
                                         message["game_id"])
            message["time_last_update"] = time.time()
            if entry:
                entry.update(message)
            else:
                self.lobby_entries.append(message)
            return True

        if message["msg"] == "lobby_remove":
            for entry in self.lobby_entries:
                if entry["id"] == message["id"]:
                    self.lobby_entries.remove(entry)
                    break
            return True

        if message["msg"] == "lobby_clear":
            self.lobby_entries = []
            self.lobby_complete = False
            return True

        if message["msg"] == "lobby_complete":
            self.lobby_complete = True
            return True

        return False

class WebTilesGameConnection(WebTilesConnection):
    """A game webtiles connection. Currently only watching games and basic chat
    functions are supported.

    The `watching` property that is true when watching a game, and
    `game_username` and `game_id` will also be set.

    The set `spectators` holds a set spectators, excluding the user of
    connection in `username`.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watching = False
        self.game_username = None
        self.game_id = None
        self.spectators = set()

    @asyncio.coroutine
    def disconnect(self):
        yield from super().disconnect()
        self.watching = False
        self.game_username = None
        self.game_id = None
        self.spectators = set()

    @asyncio.coroutine
    def send_chat(self, message):
        """Send a WebTiles chat message. Here `message` should be a simple
        string.

        """

        if not self.logged_in or not self.watching:
            raise WebTilesError(
                "Attempted to send chat message when not watching a game.")

        yield from self.send({"msg" : "chat_msg", "text" : message})

    @asyncio.coroutine
    def send_watch_game(self, username, game_id):
        """Attempt to watch the given game. After calling this method, the
        connection won't be in a 'watching' state until it receives a watch
        acknowledgement from the WebTiles server.

        """

        yield from self.send({"msg"      : "watch",
                              "username" : username})
        self.game_username = username
        self.game_id = game_id
        self.watching = False

    @asyncio.coroutine
    def send_stop_watching(self):
        """Send a message telling the server to stop watching this game, this
        preventing it from sending further messages related to the current
        game. This will work even if no game is currently being watched.

        """

        yield from self.send({"msg" : "go_lobby"})
        self.watching = False
        self.game_username = None
        self.game_id = None

    @asyncio.coroutine
    def handle_message(self, message):
        """In addition to the messages handled by `WebTilesConnection`, this
        method handles 'watching_started', used to indicate that we
        successfully watched a game, 'update_spectators', used to provide us
        with the list of current game spectators, and the 'go_lobby' and
        'game_ended' messages when watching stops.

        """

        handled = yield from super().handle_message(message)
        if handled:
            return True

        if message["msg"] == "watching_started":
            self.watching = True
            return True

        if message["msg"] == "update_spectators":
            # Strip of html tags from names
            names = re.sub(r'</?(a|span)[^>]*>', "", message["names"])
            # Ignore the Anons.
            names = re.sub(r'( and )?\d+ Anon', "", names, 1)
            self.spectators = set()
            # Exclude ourself from this list.
            for n in names.split(", "):
                if n != self.username:
                    self.spectators.add(n)
            return True

        # Messages here truly shouldn't happen until we've
        # gotten watching_started (and self.watching is hence True)
        if not self.watching:
            return False

        if message["msg"] == "game_ended" or message["msg"] == "go_lobby":
            self.watching = False
            self.game_username = None
            self.game_id = None
            return True

        return False
