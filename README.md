webtiles
========

This is a simple client library for the WebTiles server protocol for the game
[Dungeon Crawl: Stone Soup](http://crawl.develz.org/).

Dependencies
------------

* Python 3.3 or later
* asyncio module (3.4.3 tested)
* websockets module (3.0 tested)

Installation
------------

This package uses [setuptools](http://pythonhosted.org/setuptools) and can be
installed with `pip3`. For example, for a local install from the github repo:

    pip3 install --user git+https://github.com/gammafunk/webtiles.git

The library will be available on PyPI when it reaches a more feature-complete
state.

Documentation
-------------

See the pydoc for [connection.py](webtiles/connection.py) as well as the
working example in [updaterc.py](webtiles/updaterc.py), which is installed by
`pip3` as the script `update-dcss-rc`.

The library is currently extremely simple, with only enough functionality to
support the [beem](https://github.com/gammafunk/beem) and
[LomLobot](https://github.com/gammafunk/lomlobot) projects. It can handle the
basics of connecting, authentication, reading/sending messages, getting game
types, updating RC files, and reading lobby data through the
`WebTilesConnection` class, and watching games and reading/sending chat
messages through the `WebTilesGameConnection` class.
