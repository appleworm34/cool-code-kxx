from collections import defaultdict

def find_extra_channels(networks):
    results = []

    for net in networks:
        network_id = net["networkId"]
        edges = net["network"]

        # Build adjacency list (undirected)
        graph = defaultdict(list)
        input_edges = [(e["spy1"], e["spy2"]) for e in edges]
        edge_set = set(input_edges)

        for u, v in input_edges:
            graph[u].append(v)
            graph[v].append(u)

        visited = set()
        parent = {}
        cycle_edges = set()

        def dfs(node):
            visited.add(node)
            for neigh in graph[node]:
                # Skip the DFS tree parent edge (crucial fix)
                if neigh == parent.get(node):
                    continue

                if neigh in visited:
                    # back-edge to an ancestor → collect path node...neigh
                    x = node
                    while x != neigh and x in parent:
                        p = parent[x]
                        if (x, p) in edge_set:
                            cycle_edges.add((x, p))
                        elif (p, x) in edge_set:
                            cycle_edges.add((p, x))
                        x = p
                    # include the closing edge
                    if (node, neigh) in edge_set:
                        cycle_edges.add((node, neigh))
                    elif (neigh, node) in edge_set:
                        cycle_edges.add((neigh, node))
                else:
                    parent[neigh] = node
                    dfs(neigh)

        # Run DFS for all components
        for start in list(graph.keys()):
            if start not in visited:
                parent[start] = None  # set explicit parent for root
                dfs(start)

        # Preserve input order; keep only edges that are in cycles
        extra_channels = [
            {"spy1": u, "spy2": v}
            for (u, v) in input_edges
            if (u, v) in cycle_edges
        ]

        results.append({
            "networkId": network_id,
            "extraChannels": extra_channels
        })

    return {"networks": results}