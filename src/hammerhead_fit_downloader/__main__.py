"""Lets `python -m hammerhead_fit_downloader` work directly.

Without this file, `python -m hammerhead_fit_downloader` fails with
"No module named hammerhead_fit_downloader.__main__; 'hammerhead_fit_downloader'
is a package and cannot be directly executed" -- Python's -m flag looks for
this exact file when you point it at a package rather than a module.
"""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
