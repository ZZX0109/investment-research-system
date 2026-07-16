#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PostgreSQL, MinIO, and optional idempotent legacy replay.")
    parser.add_argument("--owner-email")
    parser.add_argument("--legacy-db", type=Path)
    return parser.parse_args()


def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> int:
    args = parse_args()
    database_url = require("INVESTMENT_RESEARCH_DATABASE_URL")
    endpoint = require("INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT")
    bucket = require("INVESTMENT_RESEARCH_OBJECT_STORE_BUCKET")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("Validation requires a PostgreSQL URL")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    import boto3

    client = boto3.client("s3", endpoint_url=endpoint)
    existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)
    payload = f"investment-research-infra-validation:{uuid4()}".encode()
    key = f"validation/{hashlib.sha256(payload).hexdigest()}.txt"
    client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="text/plain")
    restored = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    if hashlib.sha256(restored).digest() != hashlib.sha256(payload).digest():
        raise SystemExit("MinIO round-trip hash mismatch")
    client.delete_object(Bucket=bucket, Key=key)

    replay_results = []
    if args.owner_email and args.legacy_db:
        for _ in range(2):
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts/replay_legacy_backend.py"), "--legacy-db", str(args.legacy_db), "--owner-email", args.owner_email],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            replay_results.append(json.loads(process.stdout.strip().splitlines()[-1]))

    print(json.dumps({"status": "passed", "database": "postgresql", "object_store": "minio", "object_hash_verified": True, "legacy_replay_runs": replay_results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
