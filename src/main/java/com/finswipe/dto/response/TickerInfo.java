package com.finswipe.dto.response;

import com.finswipe.domain.entity.TickerName;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class TickerInfo {

    private String ticker;
    private String corp;
    private String ko;

    public static TickerInfo from(TickerName entity) {
        return new TickerInfo(entity.getTicker(), entity.getCorp(), entity.getKo());
    }
}
