from collections import deque

def bfs(snake, pie, grid_size):
    """Find shortest path from snake head to pie while avoiding collisions."""
    width, height = grid_size
    start = (tuple(snake), [])  # snake body tuple, moves taken
    queue = deque([start])
    seen = set([tuple(snake)])

    while queue:
        body, moves = queue.popleft()
        head = body[0]

        if head == tuple(pie):
            return moves

        for move, (dx, dy) in DIRECTIONS.items():
            new_head = (head[0] + dx, head[1] + dy)

            # Bounds check
            if not (0 <= new_head[0] < width and 0 <= new_head[1] < height):
                continue

            # Snake grows only if pie eaten
            new_body = [new_head] + list(body[:-1])
            if new_head == tuple(pie):
                new_body = [new_head] + list(body)  # grow

            # Collision check
            if len(new_body) != len(set(new_body)):
                continue

            t_body = tuple(new_body)
            if t_body in seen:
                continue

            seen.add(t_body)
            queue.append((new_body, moves + [move]))
    return []
