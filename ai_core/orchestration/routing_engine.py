class RoutingEngine:
    def next_node_id(self, node: dict) -> str | None:
        next_node = node.get("next")
        if isinstance(next_node, list):
            return next_node[0] if next_node else None
        return next_node
