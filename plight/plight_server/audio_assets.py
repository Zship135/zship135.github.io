from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4


AUDIO_ASSET_DIR = Path(__file__).with_name("audio_assets")
MAX_AUDIO_ASSET_BYTES = 25 * 1024 * 1024


def is_mp3_audio(data: bytes) -> bool:
    if len(data) < 4:
        return False
    start = 0
    if data.startswith(b"ID3"):
        if len(data) < 10 or any(size & 0x80 for size in data[6:10]):
            return False
        tag_size = (
            (data[6] << 21)
            | (data[7] << 14)
            | (data[8] << 7)
            | data[9]
        )
        start = 10 + tag_size + (10 if data[5] & 0x10 else 0)
        if start > len(data) - 4:
            return False
    scan_limit = min(len(data) - 3, start + 4096)
    for offset in range(start, scan_limit):
        if data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
            continue
        header = int.from_bytes(data[offset : offset + 4], "big")
        version = (header >> 19) & 0b11
        layer = (header >> 17) & 0b11
        bitrate_index = (header >> 12) & 0b1111
        sample_rate_index = (header >> 10) & 0b11
        if version != 0b01 and layer != 0 and bitrate_index not in {0, 0b1111} and sample_rate_index != 0b11:
            return True
    return False


def save_mp3_audio(data: bytes) -> str:
    asset_id = uuid4()
    AUDIO_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    destination = AUDIO_ASSET_DIR / f"{asset_id}.mp3"
    temporary = AUDIO_ASSET_DIR / f".{asset_id}.tmp"
    temporary.write_bytes(data)
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(asset_id)


def mp3_audio_path(asset_id: UUID) -> Path:
    return AUDIO_ASSET_DIR / f"{asset_id}.mp3"
