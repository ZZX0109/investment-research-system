"""Object storage abstraction with local and S3-compatible implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from investment_research.config import AppEnvironment, get_app_settings


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        ...

    def get(self, key: str) -> bytes:
        ...

    def delete(self, key: str) -> None:
        ...


class LocalObjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd() / "var" / "object-store"
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        del content_type
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"file-object://{key}"

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


class S3CompatibleObjectStore:
    def __init__(self, *, endpoint_url: str, bucket: str) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3-compatible object storage") from exc
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{self.bucket}/{key}"

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def build_object_store() -> ObjectStore:
    settings = get_app_settings()
    if settings.object_store_endpoint:
        return S3CompatibleObjectStore(
            endpoint_url=settings.object_store_endpoint,
            bucket=settings.object_store_bucket,
        )
    if settings.environment == AppEnvironment.PRODUCTION:
        raise RuntimeError("Production requires S3-compatible object storage")
    return LocalObjectStore()
