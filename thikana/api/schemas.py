"""Request and response contracts. FastAPI turns these into the OpenAPI docs at /docs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo like "adress" is an error, not silence
    text: str = Field(description="One address, free text, Bangla and/or English.",
                      examples=["House 12, Road 5, Mirpur-10, Dhaka-1216"])


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texts: list[str] = Field(description="Several addresses; the limit is set by the server.")


class Entity(BaseModel):
    label: str = Field(examples=["AREA"])
    text: str
    start: int = Field(description="Character offset into YOUR original text, inclusive.")
    end: int = Field(description="Character offset into YOUR original text, exclusive.")


class ParseResult(BaseModel):
    entities: list[Entity]
    fields: dict[str, list[str]] = Field(
        description="The same entities grouped by lower-case label. Postcodes are "
                    "returned with ASCII digits (১২১৬ becomes 1216).")


class ParseResponse(ParseResult):
    model_version: str


class BatchResponse(BaseModel):
    results: list[ParseResult]
    model_version: str


class ModelInfo(BaseModel):
    name: str
    version: str = Field(description="First 12 hex digits of the SHA-256 of the model file "
                                     "and its sidecar: a verifiable identity, not a label.")
    size_bytes: int
    uses_district_memory: bool
    vocabulary: list[str]
    labels: list[str]
    git_sha: str
    limitations: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
