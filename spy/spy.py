from collections import defaultdict

def find_extra_channels(networks):
    results = []

    for net in networks:
        network_id = net["networkId"]
        edges = net["network"]

        # Build adjacency list
        graph = defaultdict(list)
        # Store edges exactly as given in input order
        input_edges = [(e["spy1"], e["spy2"]) for e in edges]
        edge_set = set(input_edges)

        visited = set()
        parent = {}

        # Track which edges are in cycles
        cycle_edges = set()

        def dfs(node, prev):
            visited.add(node)
            for neigh in graph[node]:
                if neigh == prev:
                    continue
                if neigh in visited:
                    # Found a cycle → walk back from node to neigh
                    x = node
                    while x != neigh and x in parent:
                        p = parent[x]
                        # preserve original edge format
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
                    dfs(neigh, node)

        # Build graph
        for u, v in input_edges:
            graph[u].append(v)
            graph[v].append(u)

        # DFS over all components
        for node in graph:
            if node not in visited:
                dfs(node, None)

        # Keep edges only if they appear in cycles, preserving input order
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
