from collections import defaultdict

def find_extra_channels(networks):
    results = []

    for net in networks:
        network_id = net["networkId"]
        edges = net["network"]

        # Build adjacency list
        graph = defaultdict(list)
        for e in edges:
            u, v = e["spy1"], e["spy2"]
            graph[u].append(v)
            graph[v].append(u)

        # DFS to find cycles
        visited = set()
        parent = {}
        cycles = []

        def dfs(node, prev):
            visited.add(node)
            for neigh in graph[node]:
                if neigh == prev:
                    continue
                if neigh in visited:
                    # Found a cycle → reconstruct path
                    cycle = set()
                    x = node
                    while x != neigh and x in parent:
                        cycle.add((min(x, parent[x]), max(x, parent[x])))
                        x = parent[x]
                    cycle.add((min(node, neigh), max(node, neigh)))
                    cycles.append(cycle)
                else:
                    parent[neigh] = node
                    dfs(neigh, node)

        for node in graph:
            if node not in visited:
                dfs(node, None)

        # Collect all edges in cycles
        extra = set()
        for cycle in cycles:
            extra.update(cycle)

        # Convert back to required format
        extra_channels = [
            {"spy1": u, "spy2": v} for u, v in extra
        ]

        results.append({
            "networkId": network_id,
            "extraChannels": extra_channels
        })

    return {"networks": results}


# --- Example Usage ---
input_data = {
  "networks": [
    {
      "networkId": "network1",
      "network": [
        { "spy1": "Karina", "spy2": "Giselle" },
        { "spy1": "Karina", "spy2": "Winter" },
        { "spy1": "Karina", "spy2": "Ningning" },
        { "spy1": "Giselle", "spy2": "Winter" }
      ]
    }
  ]
}

output = find_extra_channels(input_data["networks"])
print(output)
