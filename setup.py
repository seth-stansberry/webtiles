from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

root = path.dirname(__file__)
with open(path.join(root, 'webtiles', 'version.py'), encoding='utf-8') as f:
    exec(f.read())
    
setup(
    name='webtiles',
    version=version,
    description='A client library for Dungeon Crawl: Stone Soup WebTiles',
    long_description=long_description,
    url='https://github.com/gammafunk/webtiles',
    author='gammafunk',
    author_email='gammafunk@gmail.com',
    packages=['webtiles'],
    extras_require={
        ':python_version=="3.3"': ['asyncio'],
    },
    entry_points={
        'console_scripts': [
            'update-dcss-rc=webtiles.updaterc:main',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Games/Entertainment :: Role-Playing",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",        
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
    ],
    platforms='all',    
    license='GPLv2',
)
