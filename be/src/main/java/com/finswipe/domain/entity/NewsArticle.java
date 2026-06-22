package com.finswipe.domain.entity;

import com.finswipe.util.StringListType;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.annotations.Type;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Entity
@Table(name = "news_articles")
@Getter
@Setter
@NoArgsConstructor
public class NewsArticle {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(nullable = false)
    private String headline;

    @Column(name = "summary_3lines", columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private List<String> summary3lines;

    @Column(name = "source_url", unique = true, nullable = false)
    private String sourceUrl;

    @Column(columnDefinition = "text")
    private String content;

    @Column(name = "content_preview")
    private String contentPreview;

    @Column(name = "image_url")
    private String imageUrl;

    @Column(name = "published_at")
    private OffsetDateTime publishedAt;

    @Column(columnDefinition = "text[]")
    @Type(StringListType.class)
    private List<String> categories;

    @Column(columnDefinition = "text[]")
    @Type(StringListType.class)
    private List<String> countries;

    @Column(columnDefinition = "text[]")
    @Type(StringListType.class)
    private List<String> tickers;

    @Column(name = "is_paywalled", nullable = false)
    private boolean isPaywalled = false;

    @Column(name = "sentiment_label")
    private String sentimentLabel;

    @Column(name = "sentiment_score")
    private Double sentimentScore;

    @Column(name = "is_mixed")
    private Boolean isMixed;

    @Column(name = "headline_ko")
    private String headlineKo;

    @Column(name = "summary_3lines_ko", columnDefinition = "text[]")
    @Type(StringListType.class)
    private List<String> summary3linesKo;

    @Column(name = "sentiment_reason", columnDefinition = "text")
    private String sentimentReason;

    @Column(name = "event_category")
    private String eventCategory;

    @Column(name = "sentiment_divergence")
    private Boolean sentimentDivergence;

    @Column(name = "novelty_score")
    private Double noveltyScore;

    @Column(name = "price_at_collection")
    private Double priceAtCollection;

    @Column(name = "created_at", updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    @PrePersist
    void prePersist() {
        createdAt = OffsetDateTime.now();
        updatedAt = createdAt;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = OffsetDateTime.now();
    }
}
