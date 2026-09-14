"""Immutable content-addressed raw-payload storage."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

from boe.evidence import RawPayloadRecord


class FileRawPayloadStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        content: bytes,
        *,
        source_url: str,
        retrieved_at: datetime,
        available_at: datetime,
        media_type: str | None,
    ) -> RawPayloadRecord:
        digest = hashlib.sha256(content).hexdigest()
        relative = Path(digest[:2]) / digest
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if destination.read_bytes() != content:
                raise RuntimeError("content-address collision or corrupted raw payload") from None
        return RawPayloadRecord(
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
            source_url=source_url,
            retrieved_at=retrieved_at,
            available_at=available_at,
            relative_path=relative.as_posix(),
        )

    def read(self, sha256: str) -> bytes:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("invalid SHA-256 digest")
        content = (self.root / sha256[:2] / sha256).read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise RuntimeError("stored raw payload failed its SHA-256 integrity check")
        return content
