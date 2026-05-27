package com.finswipe.util;

import org.hibernate.engine.spi.SharedSessionContractImplementor;
import org.hibernate.usertype.UserType;

import java.io.Serializable;
import java.sql.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * PostgreSQL text[] ↔ List<String> 매핑.
 * ArrayJdbcType(PgArray) 대신 rs.getString()으로 읽어 Supabase 풀러 호환성 확보.
 */
public class StringListType implements UserType<List<String>> {

    public static final String NAME = "string-list";

    @Override
    public int getSqlType() {
        return Types.OTHER;
    }

    @Override
    public Class<List<String>> returnedClass() {
        //noinspection unchecked
        return (Class<List<String>>) (Class<?>) List.class;
    }

    @Override
    public List<String> nullSafeGet(ResultSet rs, int position,
                                    SharedSessionContractImplementor session,
                                    Object owner) throws SQLException {
        String raw = rs.getString(position);
        if (rs.wasNull() || raw == null) return null;
        return parseArrayLiteral(raw);
    }

    @Override
    public void nullSafeSet(PreparedStatement st, List<String> value, int index,
                            SharedSessionContractImplementor session) throws SQLException {
        if (value == null) {
            st.setNull(index, Types.OTHER);
        } else {
            st.setObject(index, toArrayLiteral(value), Types.OTHER);
        }
    }

    @Override
    public List<String> deepCopy(List<String> value) {
        return value == null ? null : new ArrayList<>(value);
    }

    @Override
    public boolean isMutable() { return true; }

    @Override
    public Serializable disassemble(List<String> value) {
        return value == null ? null : new ArrayList<>(value);
    }

    @Override
    @SuppressWarnings("unchecked")
    public List<String> assemble(Serializable cached, Object owner) {
        return (List<String>) cached;
    }

    @Override
    public boolean equals(List<String> x, List<String> y) {
        return Objects.equals(x, y);
    }

    @Override
    public int hashCode(List<String> x) {
        return Objects.hashCode(x);
    }

    // "{AAPL,MSFT,\"has,comma\"}" → ["AAPL", "MSFT", "has,comma"]
    private List<String> parseArrayLiteral(String raw) {
        if (raw.equals("{}")) return List.of();
        String inner = raw.substring(1, raw.length() - 1);
        List<String> result = new ArrayList<>();
        boolean inQuotes = false;
        StringBuilder current = new StringBuilder();
        for (int i = 0; i < inner.length(); i++) {
            char c = inner.charAt(i);
            if (c == '"') {
                inQuotes = !inQuotes;
            } else if (c == ',' && !inQuotes) {
                result.add(current.toString());
                current.setLength(0);
            } else if (c == '\\' && inQuotes && i + 1 < inner.length()) {
                current.append(inner.charAt(++i));
            } else {
                current.append(c);
            }
        }
        result.add(current.toString());
        return result;
    }

    // ["AAPL", "has,comma"] → "{AAPL,\"has,comma\"}"
    private String toArrayLiteral(List<String> list) {
        StringBuilder sb = new StringBuilder("{");
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) sb.append(',');
            String s = list.get(i);
            if (s.contains(",") || s.contains("\"") || s.contains("{") || s.contains("\\")) {
                sb.append('"').append(s.replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
            } else {
                sb.append(s);
            }
        }
        return sb.append('}').toString();
    }
}
