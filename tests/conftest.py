"""Shared test configuration.

Adds the daemon directory to sys.path so tests can import daemon modules
the same way the daemon itself does (flat absolute imports).
"""

import os
import sys

DAEMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "daemon")
sys.path.insert(0, DAEMON_DIR)
