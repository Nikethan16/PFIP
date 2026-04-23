"""Prompt for a password and print its bcrypt hash.

Usage:
    python scripts/make_password_hash.py

Paste the printed hash into ``.env`` as ``PFIP_USER_PASSWORD_HASH``.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt


def main() -> int:
    try:
        pw1 = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm:  ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 1
    if pw1 != pw2:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if len(pw1) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 3
    hashed = bcrypt.hashpw(pw1.encode("utf-8"), bcrypt.gensalt(rounds=12))
    print(hashed.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
