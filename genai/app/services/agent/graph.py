from __future__ import annotations

from langgraph.graph import StateGraph, END

from app.services.agent.state import AnalysisState
from app.services.agent.nodes import (
    fetch_price_data,
    calculate_technicals,
    generate_personalized_analysis,
)


def _should_calculate(state: AnalysisState) -> str:
    return "calculate_technicals" if state.get("price_data") else "generate_analysis"


def build_analysis_graph():
    graph = StateGraph(AnalysisState)

    graph.add_node("fetch_price", fetch_price_data)
    graph.add_node("calculate_technicals", calculate_technicals)
    graph.add_node("generate_analysis", generate_personalized_analysis)

    graph.set_entry_point("fetch_price")
    graph.add_conditional_edges("fetch_price", _should_calculate)
    graph.add_edge("calculate_technicals", "generate_analysis")
    graph.add_edge("generate_analysis", END)

    return graph.compile()


# 싱글턴 — 모듈 임포트 시 한 번만 컴파일
analysis_graph = build_analysis_graph()
