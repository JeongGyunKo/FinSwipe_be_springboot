from __future__ import annotations

from enum import Enum

from pydantic import Field, HttpUrl

from app.schemas.enrichment import SchemaModel


class ArticleFetchStatus(str, Enum):
    SUCCESS = "success"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"


class ArticleFetchFailureCategory(str, Enum):
    INVALID_URL = "invalid_url"
    ACCESS_BLOCKED = "access_blocked"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    SSL_ERROR = "ssl_error"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    PARSE_ERROR = "parse_error"
    EMPTY_EXTRACT = "empty_extract"
    UNEXPECTED_ERROR = "unexpected_error"


class ArticleTextSource(str, Enum):
    PROVIDED_ARTICLE_TEXT = "provided_article_text"
    PROVIDED_SUMMARY_TEXT = "provided_summary_text"
    JSON_LD = "json_ld"
    GENERIC_JSON = "generic_json"
    PARAGRAPH_BLOCKS = "paragraph_blocks"
    CONTAINER_BLOCK = "container_block"
    META_DESCRIPTION = "meta_description"
    BEST_CANDIDATE = "best_candidate"


class ArticleFetchResult(SchemaModel):
    link: HttpUrl = Field(..., description="Requested article URL.")
    publisher_domain: str = Field(
        default="",
        description="Publisher domain derived from the requested article URL.",
    )
    final_url: str | None = Field(
        default=None,
        description="Final resolved URL after redirects, when available.",
    )
    http_status_code: int | None = Field(
        default=None,
        ge=100,
        le=599,
        description="HTTP status code associated with the fetch failure, when available.",
    )
    content_type: str | None = Field(
        default=None,
        description="Response content type observed during fetch, when available.",
    )
    extraction_source: ArticleTextSource | None = Field(
        default=None,
        description="Which parser path produced the extracted article text, when available.",
    )
    attempt_count: int = Field(
        default=1,
        ge=1,
        description="Number of fetch attempts made before returning the result.",
    )
    raw_text: str = Field(
        default="",
        description="Text extracted directly from the fetched article HTML.",
    )
    cleaned_text: str = Field(
        default="",
        description="Parser-cleaned article text for downstream Gen AI processing.",
    )
    fetch_status: ArticleFetchStatus = Field(
        ...,
        description="Final status of the article fetch and parse flow.",
    )
    retryable: bool = Field(
        default=False,
        description="Whether the fetch failure appears transient and worth retrying later.",
    )
    failure_category: ArticleFetchFailureCategory | None = Field(
        default=None,
        description="Normalized failure category for analytics and retry policy decisions.",
    )
    error_message: str | None = Field(
        default=None,
        description="Failure reason when fetching or parsing did not succeed.",
    )