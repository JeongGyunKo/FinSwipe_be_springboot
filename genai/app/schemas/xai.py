from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from app.schemas.enrichment import SchemaModel
from app.schemas.sentiment import FinBERTSentimentLabel


class XAIContributionDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class XAIUnit(str, Enum):
    SENTENCE = "sentence"


class XAIKeywordSpan(SchemaModel):
    text_snippet: str = Field(
        ...,
        min_length=1,
        description="Keyword or short phrase extracted within the highlighted sentence.",
    )
    start_char: int = Field(
        ...,
        ge=0,
        description="0-based start offset of the keyword span in the analyzed text.",
    )
    end_char: int = Field(
        ...,
        ge=0,
        description="0-based exclusive end offset of the keyword span in the analyzed text.",
    )
    importance_score: float = Field(
        ...,
        ge=0.0,
        description="Relative importance score for the keyword span within the sentence highlight.",
    )

    @model_validator(mode="after")
    def validate_offsets(self) -> XAIKeywordSpan:
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        return self


class XAIHighlight(SchemaModel):
    text_snippet: str = Field(..., min_length=1, description="Sentence used in the explanation.")
    weight: float = Field(
        ...,
        description="Relative model salience score for the explained sentence highlight.",
    )
    importance_score: float = Field(
        ...,
        ge=0.0,
        description="Absolute magnitude of the contribution weight.",
    )
    contribution_direction: XAIContributionDirection = Field(
        ...,
        description="Whether the snippet supports or opposes the explained label.",
    )
    sentence_index: int = Field(..., ge=0, description="0-based sentence index in the explained subset.")
    start_char: int | None = Field(
        default=None,
        ge=0,
        description="0-based start offset of the highlighted sentence in the analyzed text.",
    )
    end_char: int | None = Field(
        default=None,
        ge=0,
        description="0-based exclusive end offset of the highlighted sentence in the analyzed text.",
    )
    keyword_spans: list[XAIKeywordSpan] = Field(
        default_factory=list,
        description="Keyword- or phrase-level spans derived within the highlighted sentence.",
    )

    @model_validator(mode="after")
    def validate_offsets(self) -> XAIHighlight:
        if self.start_char is not None and self.end_char is not None:
            if self.end_char < self.start_char:
                raise ValueError("end_char must be greater than or equal to start_char")
        return self


class XAIResult(SchemaModel):
    target_label: FinBERTSentimentLabel = Field(
        ...,
        description="Sentiment label being explained.",
    )
    explanation_method: str = Field(
        default="attention_sentence",
        description="Backend explanation method identifier.",
    )
    explained_unit: XAIUnit = Field(
        default=XAIUnit.SENTENCE,
        description="Granularity used for highlights.",
    )
    highlights: list[XAIHighlight] = Field(
        default_factory=list,
        description="Ordered sentence-level explanation highlights.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known interpretation limits for the explanation output.",
    )
    sentence_count: int = Field(
        default=0,
        ge=0,
        description="Number of sentences included in the explanation scope.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether the article was truncated or subsetted for explanation.",
    )