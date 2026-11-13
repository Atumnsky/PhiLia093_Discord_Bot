"""Central configuration: every switch lives here and comes from .env.

Nothing else in the code base reads os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)


def _raw(key: str) -> str:
    return (os.getenv(key) or "").strip()


def _str(key: str, default: str = "") -> str:
    return _raw(key) or default


def _bool(key: str, default: bool = False) -> bool:
    value = _raw(key).lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "y", "enabled"}


def _int(key: str, default: int = 0) -> int:
    try:
        return int(_raw(key))
    except (TypeError, ValueError):
        return default


def _ids(key: str) -> tuple[int, ...]:
    """Parse a comma/semicolon separated list of Discord IDs."""
    found: list[int] = []
    for chunk in _raw(key).replace(";", ",").split(","):
        chunk = chunk.strip().lstrip("#<>")
        if chunk.isdigit():
            found.append(int(chunk))
    return tuple(found)


@dataclass(frozen=True)
class Settings:
    # --- Discord ---
    discord_token: str
    chat_channels: tuple[int, ...]
    online_channel: int
    max_history: int
    timestamp_suffix: bool

    # --- Chat model (DeepSeek) ---
    deepseek_key: str
    deepseek_model: str
    deepseek_pro_model: str
    deepseek_base_url: str

    # --- Vision (OpenAI compatible, Qwen by default) ---
    vision_key: str
    vision_base_url: str
    vision_model: str

    # --- Image generation ---
    image_provider: str
    pollinations_model: str
    image_size: int
    aliyun_image_model: str
    aliyun_image_size: str
    aliyun_edit_model: str
    aliyun_key: str

    # --- Search ---
    tavily_key: str
    max_search_results: int

    # --- Paths ---
    data_dir: Path
    chroma_dir: Path
    stickers_dir: Path

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("DISCORD_TOKEN", self.discord_token),
                ("DEEPSEEK_API_KEY", self.deepseek_key),
            )
            if not value
        ]
        if missing:
            raise SystemExit(
                "Missing required environment variables: "
                + ", ".join(missing)
                + "\n请在 .env 中填写缺失的变量（可参考 .env.example）。"
            )


def load_settings() -> Settings:
    chat_channels = _ids("PHILIA093_CHAT_CHANNEL")
    online_channel = _int("ONLINE_CHANNEL_ID") or (
        chat_channels[0] if chat_channels else 0
    )

    data_dir = Path(_str("DATA_DIR", str(BASE_DIR / "data")))

    settings = Settings(
        discord_token=_raw("DISCORD_TOKEN"),
        chat_channels=chat_channels,
        online_channel=online_channel,
        max_history=max(2, _int("MAX_HISTORY", 30)),
        timestamp_suffix=_bool("TIMESTAMP_SUFFIX", True),
        deepseek_key=_raw("DEEPSEEK_API_KEY"),
        deepseek_model=_str("DEEPSEEK_MODEL", "deepseek-flash"),
        deepseek_pro_model=_str("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro"),
        deepseek_base_url=_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        vision_key=_str("VISION_API_KEY") or _raw("ALIYUN_API_KEY"),
        vision_base_url=_str(
            "VISION_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        vision_model=_str("VISION_MODEL", "qwen3-vl-plus"),
        image_provider=_str("IMAGE_PROVIDER", "pollinations").lower(),
        pollinations_model=_str("POLLINATIONS_MODEL", "flux"),
        image_size=max(256, min(1536, _int("IMAGE_SIZE", 1024))),
        aliyun_image_model=_str("ALIYUN_IMAGE_MODEL", "qwen-image-3.0-pro"),
        aliyun_image_size=_str("ALIYUN_IMAGE_SIZE", "1328*1328"),
        aliyun_edit_model=_str("ALIYUN_EDIT_MODEL", "qwen-image-2.0-pro"),
        aliyun_key=_raw("ALIYUN_API_KEY"),
        tavily_key=_raw("TAVILY_API_KEY"),
        max_search_results=max(1, min(10, _int("MAX_SEARCH_RESULTS", 5))),
        data_dir=data_dir,
        chroma_dir=Path(_str("CHROMA_PATH", str(BASE_DIR / "chroma_knowledge"))),
        stickers_dir=Path(_str("STICKERS_DIR", str(BASE_DIR / "stickers"))),
    )
    settings.validate()
    return settings


settings = load_settings()
