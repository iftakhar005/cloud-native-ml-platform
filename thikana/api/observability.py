"""Logging and metrics.

PRIVACY RULE: the submitted address is personal data and is NEVER logged. A log
line carries the request id, route, status, latency, text LENGTH and entity
counts. A test fails if the text ever appears in a log record.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from thikana.schema import ENTITY_TYPES

REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LOGGER = logging.getLogger("thikana")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, ready for a log shipper."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            # The exception TYPE and where it happened, never its message: messages
            # are the one place user text could leak into a log by accident.
            last = traceback.extract_tb(record.exc_info[2])[-1]
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc_at"] = f"{Path(last.filename).name}:{last.lineno}"
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Idempotent: calling it twice does not duplicate handlers."""
    if not any(isinstance(h.formatter, JsonFormatter) for h in LOGGER.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        LOGGER.addHandler(handler)
    LOGGER.setLevel(level)


def log(event: str, level: int = logging.INFO, exc_info=None, **fields) -> None:
    LOGGER.log(level, event, extra={"fields": fields}, exc_info=exc_info)


class Metrics:
    """Prometheus instruments on a PER-APP registry, so building several apps (as
    the tests do) never trips the global registry's duplicate-name check."""

    def __init__(self) -> None:
        r = self.registry = CollectorRegistry()
        self.requests = Counter("thikana_http_requests_total", "HTTP requests",
                                ["method", "route", "status"], registry=r)
        self.latency = Histogram("thikana_http_request_duration_seconds", "Request latency",
                                 ["method", "route"], registry=r,
                                 buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5))
        # ML-specific: if the distribution of predicted labels, or the share of
        # addresses with nothing found, shifts, the INPUT has probably drifted -
        # something no infrastructure metric can show.
        self.parsed = Counter("thikana_addresses_parsed_total", "Addresses parsed", registry=r)
        self.entities = Counter("thikana_entities_total", "Entities predicted, by label",
                                ["label"], registry=r)
        self.empty = Counter("thikana_empty_parses_total",
                             "Addresses in which NO entity was found", registry=r)
        self.chars = Histogram("thikana_text_chars", "Length of submitted address text", registry=r,
                               buckets=(10, 25, 50, 100, 200, 350, 500, 1000))
        self.model_ready = Gauge("thikana_model_ready", "1 if a model is loaded", registry=r)
        self.model_info = Gauge("thikana_model_info", "Identity of the loaded model",
                                ["name", "version"], registry=r)
        for label in ENTITY_TYPES:  # make every series exist from the start, at 0
            self.entities.labels(label)
