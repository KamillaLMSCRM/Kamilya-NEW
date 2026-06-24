#!/usr/bin/env python
"""
Create the Supabase Storage bucket for certificate PDFs.

Idempotent: if the bucket already exists, prints a notice and exits 0.
Exits non-zero on auth/network errors with a clear message.

Usage (run from apps/api/ with venv active):
    SUPABASE_URL=https://xxx.supabase.co \\
    SUPABASE_KEY=eyJ...service-role... \\
    SUPABASE_BUCKET=certificates \\
    python ../../scripts/setup_storage_bucket.py

Or with --bucket override:
    python ../../scripts/setup_storage_bucket.py --bucket my-certs
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create Supabase Storage bucket for certificate PDFs."
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("SUPABASE_BUCKET", "certificates"),
        help="Bucket name (default: $SUPABASE_BUCKET or 'certificates')",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Make the bucket publicly readable (NOT recommended for certs — use signed URLs)",
    )
    args = parser.parse_args(argv if argv is not None else [])

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        print(
            "ERROR: SUPABASE_URL and SUPABASE_KEY must be set.\n"
            "  export SUPABASE_URL=https://xxx.supabase.co\n"
            "  export SUPABASE_KEY=eyJ...service-role-key... (NOT the anon key)",
            file=sys.stderr,
        )
        return 1

    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase package not installed. Run: pip install -r apps/api/requirements.txt", file=sys.stderr)
        return 1

    print(f"Connecting to {url} ...")
    client = create_client(url, key)

    # List existing buckets to check idempotency
    print(f"Listing existing buckets ...")
    try:
        existing = client.storage.list_buckets()
    except Exception as e:
        print(f"ERROR: Could not list buckets: {e}", file=sys.stderr)
        return 1

    existing_names = {b.get("name") for b in (existing or [])}
    if args.bucket in existing_names:
        print(f"OK: bucket '{args.bucket}' already exists. Nothing to do.")
        return 0

    # Create the bucket
    print(f"Creating bucket '{args.bucket}' (public={args.public}) ...")
    try:
        client.storage.create_bucket(
            name=args.bucket,
            options={"public": args.public},
        )
    except Exception as e:
        msg = str(e)
        # supabase-py sometimes returns a wrapped error for duplicate names
        if "already exists" in msg.lower() or "duplicate" in msg.lower():
            print(f"OK: bucket '{args.bucket}' already exists (race-safe).")
            return 0
        print(f"ERROR: Failed to create bucket: {e}", file=sys.stderr)
        return 1

    # Verify it was actually created
    try:
        post = client.storage.list_buckets()
        post_names = {b.get("name") for b in (post or [])}
        if args.bucket in post_names:
            print(f"OK: bucket '{args.bucket}' created successfully.")
            print(
                "\nNext steps:\n"
                f"  1. Confirm in Supabase Dashboard -> Storage -> {args.bucket}\n"
                "  2. On Render, set STORAGE_BACKEND=supabase (or keep 'local' for dev)\n"
                "  3. Restart the API service.\n"
            )
            return 0
        print(f"ERROR: create returned OK but bucket not found in list_buckets()", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"WARNING: bucket created but verification failed: {e}", file=sys.stderr)
        print(f"(Check the Supabase Dashboard manually.)")
        return 0  # treat as success — bucket was created, just couldn't verify


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
