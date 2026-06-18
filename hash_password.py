#!/usr/bin/env python3
"""Helper: generate a scrypt hash for METALLAMA_ADMIN_PASS_HASH."""
import getpass
import sys

sys.path.insert(0, ".")
from metallama.app.auth import hash_password

password = getpass.getpass("Enter admin password: ")
confirm = getpass.getpass("Confirm admin password: ")
if password != confirm:
    print("Passwords do not match")
    sys.exit(1)
hashed = hash_password(password)
print(f"\nAdd this to your .env file:\n")
print(f"METALLAMA_ADMIN_PASS_HASH={hashed}")
