package com.finswipe.dto.response;

import com.finswipe.domain.entity.TickerName;
import lombok.Getter;

import java.time.LocalDate;
import java.util.List;

@Getter
public class TickerInfo {

    private final String ticker;
    private final String corp;
    private final String ko;
    private final List<String> aliases;
    private final LocalDate delistingDate;

    public TickerInfo(String ticker, String corp, String ko, List<String> aliases, LocalDate delistingDate) {
        this.ticker = ticker;
        this.corp = corp;
        this.ko = ko;
        this.aliases = aliases != null ? aliases : List.of();
        this.delistingDate = delistingDate;
    }

    public boolean isDelistingPending() { return delistingDate != null; }

    public static TickerInfo from(TickerName entity) {
        return new TickerInfo(entity.getTicker(), entity.getCorp(), entity.getKo(), List.of(), null);
    }
}
