package com.finswipe.util;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 한국어 금융 텍스트에서 강조할 구간(start, end)을 추출.
 * 숫자/퍼센트, 핵심 금융 키워드, 방향성 동사를 탐지한다.
 */
public final class HighlightUtil {

    private HighlightUtil() {}

    // 숫자 + 단위 패턴 (%, $, ₩, 억/조/만/B/M/K)
    private static final Pattern NUM_PATTERN = Pattern.compile(
            "\\$[\\d,.]+(억|조|만|[BMKbmk])?"
            + "|[\\d,.]+%"
            + "|[\\d,.]+(억|조|만)\\s*(원|달러)?"
            + "|[\\d,.]+배"
            + "|[\\d]+\\s*(분기|회계연도|년도|Q[1-4])"
    );

    // 핵심 금융 방향성·이벤트 키워드
    private static final Pattern KEYWORD_PATTERN = Pattern.compile(
            "상회|하회|상향|하향"
            + "|급등|급락|급증|급감"
            + "|사상\\s*(최고|최저|최대|최소)"
            + "|역대\\s*(최고|최저|최대|최소)"
            + "|흑자|적자|흑자전환|적자전환"
            + "|초과달성|미달|목표\\s*초과"
            + "|가이던스\\s*(상향|하향|유지|제시)"
            + "|매출\\s*(급증|급감|증가|감소|성장)"
            + "|영업이익\\s*(급증|급감|증가|감소|흑자|적자)"
            + "|시장\\s*예상치?\\s*(상회|하회|초과|미달)"
            + "|투자의견\\s*(상향|하향|유지)"
            + "|목표주가\\s*(상향|하향|제시)"
            + "|서프라이즈|쇼크|어닝스|가이던스"
    );

    /**
     * 텍스트에서 강조 구간 목록을 반환한다.
     * @return [[start, end], ...] 정렬·병합된 구간 목록 (end는 exclusive)
     */
    public static List<int[]> computeRanges(String text) {
        if (text == null || text.isBlank()) return List.of();

        List<int[]> raw = new ArrayList<>();
        collectMatches(NUM_PATTERN.matcher(text), raw);
        collectMatches(KEYWORD_PATTERN.matcher(text), raw);

        return merge(raw);
    }

    /**
     * 텍스트 리스트 각각에 대해 강조 구간을 반환한다.
     */
    public static List<List<int[]>> computeRangesForLines(List<String> lines) {
        if (lines == null) return List.of();
        return lines.stream().map(HighlightUtil::computeRanges).toList();
    }

    private static void collectMatches(Matcher m, List<int[]> out) {
        while (m.find()) {
            if (m.end() > m.start()) {
                out.add(new int[]{m.start(), m.end()});
            }
        }
    }

    private static List<int[]> merge(List<int[]> ranges) {
        if (ranges.isEmpty()) return List.of();
        ranges.sort(Comparator.comparingInt(r -> r[0]));
        List<int[]> merged = new ArrayList<>();
        int[] cur = ranges.get(0).clone();
        for (int i = 1; i < ranges.size(); i++) {
            int[] next = ranges.get(i);
            if (next[0] <= cur[1]) {
                cur[1] = Math.max(cur[1], next[1]);
            } else {
                merged.add(cur);
                cur = next.clone();
            }
        }
        merged.add(cur);
        return merged;
    }
}
