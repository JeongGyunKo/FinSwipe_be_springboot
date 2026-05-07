package com.finswipe.domain.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "ticker_names")
@Getter
@NoArgsConstructor
public class TickerName {

    @Id
    private String ticker;

    @Column(nullable = false)
    private String corp;

    @Column(nullable = false)
    private String ko;
}
