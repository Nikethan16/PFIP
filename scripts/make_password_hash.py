#!/usr/bin/env python3
"""Generate a bcrypt hash for the PFIP single-user login.

The resulting hash goes into `.env` as `PFIP_USER_PASSWORD_HASH=...` — the
backend verifies it against the plaintext submitted via the NextAuth
credentials provider.

Usage:
    python scripts/make_password_hash.py                  # interactive prompt
    python scripts/make_password_hash.py 'myPassword!'    # explicit (NOT recommended;
                                                          # shell history keeps it)
    echo 'myPassword!' | python scripts/make_password_hash.py --stdin

Dependencies:
    pip install bcrypt

The hash is printed to stdout so it can be piped into a .env update tool.
"""

from __future__ import annotations

import argparse
import getpass
import sys


def _import_bcrypt():
    try:
        import bcrypt  # type: ignore
    except ImportError:
        print(
            "ERROR: bcrypt not installed. Run: pip install bcrypt",
            file=sys.stderr,
        )
        sys.exit(2)
    return bcrypt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a bcrypt hash for PFIP_USER_PASSWORD_HASH."
    )
    parser.add_argument(
        "password",
        nargs="?",
        help="Password plaintext. If omitted, prompts interactively (recommended).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read password from stdin (one line, no trailing newline).",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=12,
        help="bcrypt cost factor (default 12; 12-14 is sensible for interactive use).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the hash (no explanatory text).",
    )
    args = parser.parse_args()

    bcrypt = _import_bcrypt()

    if args.stdin:
        pwd = sys.stdin.readline().rstrip("\n")
    elif args.password is not None:
        pwd = args.password
    else:
        pwd = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm:  ")
        if pwd != confirm:
            print("ERROR: passwords do not match.", file=sys.stderr)
            return 3

    if not pwd:
        print("ERROR: empty password.", file=sys.stderr)
        return 4
    if len(pwd) < 12:
        print("WARN: password < 12 chars — consider stronger.", file=sys.stderr)

    salt = bcrypt.gensalt(rounds=args.rounds)
    hashed = bcrypt.hashpw(pwd.encode("utf-8"), salt).decode("utf-8")

    if args.quiet:
        print(hashed)
    else:
        print()
        print("PFIP_USER_PASSWORD_HASH=" + hashed)
        print()
        print("Paste the line above into your .env file.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
