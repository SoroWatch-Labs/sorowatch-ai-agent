"""
Real LangGraph pipeline: gather_data -> score_risk -> decide_action.

This replaces the placeholder that earlier iterations of this project left
as a stub. It's still deliberately simple — heuristic scoring rather than
an LLM call — but it's a genuine end-to-end graph, not a fixed return
value.
"""
from typing import TypedDict

from langgraph.graph import StateGraph, END

from app.horizon_client import HorizonClient
from app.scoring import combine_breakdown, compute_score_breakdown


class PipelineState(TypedDict):
    address: str
    threshold: int
    operations: list[dict]
    score: int
    breakdown: dict[str, int]
    flagged: bool


async def gather_data(state: PipelineState) -> PipelineState:
    client = HorizonClient()
    operations = await client.get_recent_operations(state["address"])
    return {**state, "operations": operations}


async def score_risk(state: PipelineState) -> PipelineState:
    breakdown = compute_score_breakdown(state["operations"])
    score = combine_breakdown(breakdown)
    return {**state, "score": score, "breakdown": breakdown}


async def decide_action(state: PipelineState) -> PipelineState:
    flagged = state["score"] >= state["threshold"]
    return {**state, "flagged": flagged}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("gather_data", gather_data)
    graph.add_node("score_risk", score_risk)
    graph.add_node("decide_action", decide_action)

    graph.set_entry_point("gather_data")
    graph.add_edge("gather_data", "score_risk")
    graph.add_edge("score_risk", "decide_action")
    graph.add_edge("decide_action", END)

    return graph.compile()


async def run_pipeline(address: str, threshold: int = 50) -> PipelineState:
    graph = build_graph()
    initial_state: PipelineState = {
        "address": address,
        "threshold": threshold,
        "operations": [],
        "score": 0,
        "breakdown": {},
        "flagged": False,
    }
    result = await graph.ainvoke(initial_state)
    return result
