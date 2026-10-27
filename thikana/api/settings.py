"""Service configuration, read from environment variables.

No secrets exist in v1 (the service has no database, no API keys, no outbound
calls), and none should be added here: in Kubernetes these values come from a
ConfigMap, and anything secret would come from a Secret instead.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Deliberately NOT imported from thikana.training.train_all: serving must not
# import the training code (and with it pandas). A test checks the two agree.
DEFAULT_MODEL = "crf_all_district_memory"

# The instance name is sent back in a response header, so it must not be able to carry
# a newline or any other header-breaking character.
INSTANCE_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")


def _instance(env: Mapping[str, str]) -> str:
    """Which replica answered. Default: the hostname, which Docker sets to the container
    id and Kubernetes sets to the pod name, so replicas tell themselves apart with no
    configuration. THIKANA_INSTANCE overrides it (set it to something neutral to hide it)."""
    raw = env.get("THIKANA_INSTANCE")
    if raw:
        if not INSTANCE_OK.fullmatch(raw):
            raise ValueError("THIKANA_INSTANCE must be 1-63 characters from A-Z a-z 0-9 . _ - "
                             f"and start with a letter or digit, got {raw!r}")
        return raw
    host = socket.gethostname()
    return host if INSTANCE_OK.fullmatch(host) else "unknown"


def _integer(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    model_path: Path = ROOT / "models" / f"{DEFAULT_MODEL}.crfsuite"
    max_text_chars: int = 500        # one address is a line or two, never an essay
    max_batch: int = 100             # addresses per batch request
    max_body_bytes: int = 64 * 1024  # rejected on Content-Length, before parsing
    log_level: str = "INFO"
    cors_origins: tuple[str, ...] = ()  # empty = CORS off (the default is the safe one)
    git_sha: str = "unknown"            # stamped at image build time
    instance: str = "unknown"           # which replica answered (X-Thikana-Instance header)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        default = cls()
        origins = tuple(o.strip() for o in env.get("THIKANA_CORS_ORIGINS", "").split(",") if o.strip())
        level = env.get("THIKANA_LOG_LEVEL", default.log_level).upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"THIKANA_LOG_LEVEL must be DEBUG/INFO/WARNING/ERROR, got {level!r}")
        return cls(
            model_path=Path(env.get("THIKANA_MODEL_PATH") or default.model_path),
            max_text_chars=_integer(env, "THIKANA_MAX_TEXT_CHARS", default.max_text_chars, 1),
            max_batch=_integer(env, "THIKANA_MAX_BATCH", default.max_batch, 1),
            max_body_bytes=_integer(env, "THIKANA_MAX_BODY_BYTES", default.max_body_bytes, 1024),
            log_level=level,
            cors_origins=origins,
            git_sha=env.get("THIKANA_GIT_SHA", default.git_sha),
            instance=_instance(env),
        )
