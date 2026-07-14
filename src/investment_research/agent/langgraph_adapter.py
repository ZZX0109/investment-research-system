from __future__ import annotations

from investment_research.agent.service import AGENT_NODES, AgentOrchestrator


class LangGraphAdapter:
    """Optional visualization adapter; execution remains in AgentOrchestrator."""

    def __init__(self, orchestrator: AgentOrchestrator) -> None:
        self.orchestrator = orchestrator

    def graph_description(self) -> dict[str, object]:
        return {
            "authority": "typed_internal_state_machine",
            "nodes": list(AGENT_NODES),
            "edges": [[left, right] for left, right in zip(AGENT_NODES, AGENT_NODES[1:])],
        }

    def compile(self):
        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is optional and not installed") from exc
        graph = StateGraph(dict)
        for node_name in AGENT_NODES:
            graph.add_node(node_name, lambda state, name=node_name: {**state, "visualized_node": name})
        graph.set_entry_point(AGENT_NODES[0])
        for left, right in zip(AGENT_NODES, AGENT_NODES[1:]):
            graph.add_edge(left, right)
        graph.add_edge(AGENT_NODES[-1], END)
        return graph.compile()
