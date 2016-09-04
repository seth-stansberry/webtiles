"""
A WebTiles library for python

"""

import asyncio
import html
import json
import logging
import re
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
    files. It has preliminary support for the second-version protocol used by
    the webtiles-changes branch, but not all functionality is implemented.

    The `websocket` property holds the websocket instance of the current
    connection. When logged in through either `connect()` or `send_login()`,
    the `logged_in` property will be true, and `login_username` will hold the
    current username. The game list is only received after login, and is a dict
    in the `games` property with each key a descriptive name and each value a
    game type id. The game id is used when playing and setting the rc file.

    For lobby data, lobby entries are available in `lobby_entries` and can be
    retrieved by game username and game id with `get_entry()`. Each entry is a
    dictionary with keys 'username', 'game_id', 'id' (a unique game identifier
    used by the server), 'idle_time', and 'spectator_count'. Additionally we
    add the key 'time_last_update' with the time of the last update to the
    entry.

    Under the v1 protocol, `lobby_complete` will be True when the server
    indicates that it's sent a complete set of entries. Under v2 of the
    protocol, lobbies are sent in batches as necessary, so `lobby_complete` not
    needed and always None.

    Some errors will raise `WebTilesError`, where the first exception argument
    will be an error message.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decomp = zlib.decompressobj(-zlib.MAX_WBITS)
        self.websocket = None
        self.logged_in = False
        self.login_username = None
        self.games = {}
        self.lobby_entries = []
        self.lobby_complete = None
        self.protocol_version = None

    @asyncio.coroutine
    def connect(self, websocket_url, username=None, password=None,
                protocol_version=1, *args, **kwargs):
        """Connect to the given websocket URL with optional credentials. Use a
        value of 2 for `protocol_version` on servers running the
        webtiles-changes branch. Additional arguments are passed to
        `webscokets.connect()`.

        """

        if username and not password:
            raise WebTilesError("Username given but no password given.")

        if self.connected():
            raise WebTilesError("Attempted to connect when already connected.")

        self.websocket = yield from websockets.connect(websocket_url, *args,
                                                       **kwargs)
        self.protocol_version = protocol_version
        if username:
            yield from self.send_login(username, password)
            self.login_username = username

    @asyncio.coroutine
    def send_login(self, username, password):
        """Send the login message. This is usally called by `connect()`, but the
        `send_login()` method can be used to authenticate after connecting
        without credentials. The `logged_in` property will only be True after
        the server responds with a "login_complete" message when this is
        handled by `handle_message()`.

        """

        msg = {"msg" : "login",
               "username" : username,
               "password" : password}
        # XXX We don't yet support cookie login in any protocol. This isn't
        # useful for any project using the library right now, but may be in the
        # future.
        if self.protocol_version >= 2:
            msg["rememberme"] = False
        yield from self.send(msg)
        self.logged_in = False
        self.login_username = username

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
        self.lobby_complete = None
        self.protocol_version = None

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

        yield from self.send({"msg" : "set_rc",
                              "game_id" : game_id,
                              "contents" : rc_text})

    @asyncio.coroutine
    def get_rc(self, game_id):
        """Get the user's RC file for the given game on the server. If the
        connection isn't logged in, raise an exception.

        Any client using this method will need to respond to "rcfile_contents"
        messages from the WebTiles server, which will have the RC contents in
        the "contents" key of the message dict.

        """

        if not self.logged_in:
            raise WebTilesError("Attempted to get RC when not logged in")

        yield from self.send({"msg" : "get_rc", "game_id" : game_id})


    @asyncio.coroutine
    def send(self, message):
        """Send a message dictionary to the server. The message should be a dict
        with a 'msg' key having a webtiles message type.

        """

        if "msg" not in message:
            raise WebTilesError("Message dict must contain a 'msg' key")

        yield from self.websocket.send(json.dumps(message))

    def remove_lobby_entry(self, process_id):
        """Remove a lobby entry with the given process id. This id is included in
        a "lobby_remove" message (v1 protocol) or as the "remove" key value of
        a "lobby" message (v2 protocol).

        """

        for entry in self.lobby_entries:
            if entry["id"] == process_id:
                self.lobby_entries.remove(entry)
                break
        _log.debug("Unknown lobby id %s", process_id)

    def update_lobby_entries(self, entries):
        current_time = time.time()
        for entry in entries:
            entry["time_last_update"] = current_time
            cur_entry = self.get_lobby_entry(entry["username"],
                                             entry["game_id"])
            if cur_entry:
                cur_entry.update(entry)
            else:
                self.lobby_entries.append(entry)

    @asyncio.coroutine
    def handle_message(self, message):
        """Given a response message dictionary, handle the message. Returns True
        if the message is handled by this handler. This method can be extended
        in derived classes to handle other message types or to additional
        handling. This base method must be called for the following message
        types in order to manage connect state properly: "login_success",
        "set_game_links", "lobby_entry", "lobby_remove", "lobby_clear",
        "lobby_complete".

        This method doesn't handle the "login_fail" message type when
        authentication is rejected.

        """

        if message["msg"] == "ping":
            yield from self.send({"msg" : "pong"})
            return True

        if message["msg"] == "login_success":
            self.logged_in = True
            return True

        if self.protocol_version <= 1:
            if message["msg"] == "lobby_entry":
                self.update_lobby_entries([message])

            if message["msg"] == "lobby_remove":
                self.remove_lobby_entry(message["id"])
                return True

            if message["msg"] == "lobby_complete":
                self.lobby_complete = True
                return True

            if message["msg"] == "set_game_links":
                game_pattern = r'<a href="#play-([^"]+)">([^>]+)</a>'
                self.games = {}
                for m in re.finditer(game_pattern, message["content"]):
                    game_id = m.group(1)
                    game_name = m.group(2)
                    self.games[game_name] = game_id
                return True

        elif self.protocol_version >= 2:
            if message["msg"] == "lobby":
                if "entries" in message:
                    self.update_lobby_entries(message["entries"])
                if "remove" in message:
                    self.remove_lobby_entry(message["remove"])
                return True

            if message["msg"] == "game_info":
                for game in message["games"]:
                    self.games[game["name"]] = game["id"]

                return True

        if message["msg"] == "lobby_clear":
            self.lobby_entries = []
            self.lobby_complete = False
            return True

        return False

class WebTilesGameConnection(WebTilesConnection):
    """A game webtiles connection. Currently only watching games and basic chat
    functions are supported.

    Call `send_watch_game()` to watch a user's game and check for the
    `watching` property to be true after we receive confirmation from the
    server that watching has started. The `watch_username` and `game_id`
    properties will be set to the username and game id of the current watched
    game. Note that we can't guarantee that the game id is correct, since
    WebTiles currently doesn't support specifying which game type to watch if a
    user has multiple active games.

    Call `send_stop_watching()` to cease watching a game, or call
    `send_watch_game()` again.

    The set `spectators` holds a set spectators, excluding the username of
    `login_username`.

    Call `send_chat()` can be used to send messages to WebTiles chat.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watching = False
        self.watch_username = None
        self.game_id = None
        self.spectators = set()

    @asyncio.coroutine
    def disconnect(self):
        yield from super().disconnect()
        self.watching = False
        self.watch_username = None
        self.game_id = None
        self.spectators = set()

    def parse_chat_message(self, message):
        """Parse a game chat message, returning a tuple with the sender's
        username and the chat text. HTML entities in the text are
        decoded.

        """

        if self.protocol_version <= 1:
            # Remove html formatting
            msg_pattern = r'<span[^>]+>([^<]+)</span>: <span[^>]+>([^<]+)</span>'
            match = re.match(msg_pattern, message["content"])
            if not match:
                raise WebTilesError("Unable to parse chat message: %s",
                                    message["content"])

            sender = match.group(1)
            chat_text = match.group(2)
        else:
            sender = message["sender"]
            chat_text = message["text"]

        return (sender, html.unescape(chat_text))

    @asyncio.coroutine
    def send_chat(self, chat_text):
        """Send a WebTiles chat message. Here `chat_text` should be a simple
        string.

        """

        if not self.watching:
            raise WebTilesError(
                "Attempted to send chat message when not watching a game.")

        elif not self.logged_in:
            raise WebTilesError(
                "Attempted to send chat message when not logged in.")

        yield from self.send({"msg" : "chat_msg", "text" : chat_text})

    @asyncio.coroutine
    def send_watch_game(self, username, game_id):
        """Attempt to watch the given game. After calling this method, the
        connection won't be in a 'watching' state until it receives a watch
        acknowledgement from the WebTiles server.

        """

        yield from self.send({"msg"      : "watch",
                              "username" : username})
        self.watch_username = username
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
        self.watch_username = None
        self.game_id = None

    def parse_v1_spectator_message(self, message):
        # Strip of html tags from names
        names = re.sub(r'</?(a|span)[^>]*>', "", message["names"])
        # Ignore the Anons.
        names = re.sub(r'( and )?\d+ Anon', "", names, 1)
        self.spectators = set()
        # Exclude ourself from this list.
        for n in names.split(", "):
            if n != self.login_username:
                self.spectators.add(n)

    def parse_v2_spectator_message(self, message):
        self.spectators = set()
        for entry in message["spectators"]:
            if entry["name"] != self.login_username:
                self.spectators.add(entry["name"])

    @asyncio.coroutine
    def handle_message(self, message):
        """

        In addition to the messages handled by `WebTilesConnection`, this method
        handles "watching_started", used to indicate that we successfully
        watched a game, "update_spectators", used to provide us with the list
        of current game spectators, and the "go_lobby" (or "go" in v2 of the
        protocol) and "game_ended" messages when watching stops.

        Chat messages have a message type of "chat" and are not handled by this
        method, but `parse_chat_message()` is available in this class to parse
        these.

        """

        handled = yield from super().handle_message(message)
        if handled:
            return True

        if message["msg"] == "watching_started":
            self.watching = True
            return True

        if message["msg"] == "update_spectators":
            if self.protocol_version <= 1:
                self.parse_v1_spectator_message(message)
            else:
                self.parse_v2_spectator_message(message)
            return True

        # Messages here truly shouldn't happen until we've
        # gotten watching_started (and self.watching is hence True)
        if not self.watching:
            return False

        if (message["msg"] == "game_ended"
            # v1 of the protocol
            or message["msg"] == "go_lobby"
            # v2 protocol
            or message["msg"] == "go" and message["path"] == "/"):
            self.watching = False
            self.watch_username = None
            self.game_id = None
            return True

        return False
