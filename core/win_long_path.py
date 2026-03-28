r"""
Windows Extended-Length Path Support
=====================================
Windows default MAX_PATH = 260 characters.
Using the \\?\ prefix unlocks 32,767 characters — enough for any real-world path.

Rules for \\?\ prefix:
  - Path MUST be absolute (no relative components)
  - No forward slashes — must be backslashes
  - No . or .. components
  - UNC paths (\\server\share) need \\?\UNC\ prefix

This module provides to_extended(path) and strip_extended(path).
Both are no-ops on macOS/Linux; on Windows they add/remove the \\?\ prefix.
"""

import os
import sys


def to_extended(path: str) -> str:
    """
    Convert a path to Windows extended-length format if on Windows.
    Safe to call on paths that already have the prefix.
    No-op on macOS/Linux.
    """
    if sys.platform != 'win32':
        return path

    # Already extended
    if path.startswith('\\\\?\\'):
        return path

    # Make absolute and normalise separators
    path = os.path.abspath(path)
    path = path.replace('/', '\\')

    # UNC path (\\server\share\...)
    if path.startswith('\\\\'):
        return '\\\\?\\UNC\\' + path[2:]

    # Regular drive path (C:\...)
    return '\\\\?\\' + path


def strip_extended(path: str) -> str:
    """Remove extended-length prefix for display purposes."""
    if path.startswith('\\\\?\\UNC\\'):
        return '\\\\' + path[8:]
    if path.startswith('\\\\?\\'):
        return path[4:]
    return path
