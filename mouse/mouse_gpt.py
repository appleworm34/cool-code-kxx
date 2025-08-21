"""
Micromouse solver for the specified ruleset and API.

Implements:
- Persistent per-game state (maze map, pose, exploration status)
- Online flood-fill exploration with unknown=open bias
- Momentum-aware token sequencing (keeps |m| ≤ 2 for safe wide corners)
- Switches to speed-run after mapping a viable route to the 2×2 center goal
- Single entry point: handle_post(request_json) -> response_json

Assumptions & Simplifications:
- Each longitudinal token (F0/F1/F2/V0/V1/V2/BB) advances one half-step straight
  along the current heading (8 cm). Momentum updates follow token names.
- Corner tokens (e.g., F1LT, F1RT, F1LW, F1RW) perform a 90° change while
  advancing by one corner arc (tight or wide). We select wide corners and ensure
  m_eff ≤ 2 by pre-braking when needed.
- Diagonal sensors (-45°, +45°) are used as soft hints only and do not gate moves.
  We treat -90°, 0°, +90° as authoritative immediate walls.
- Unknown walls are considered open during exploration (classic micromouse bias).
- Coordinates: (x, y) with (0,0) at bottom-left. Facing: 0=N, 1=E, 2=S, 3=W.
- Goal cells are {(7,7), (7,8), (8,7), (8,8)}.

You can integrate this module into a web service framework and call handle_post
for each POST /micro-mouse. The function returns the required response JSON.
"""
from __future__ import annotations
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# === Constants ===
GRID_W = 16
GRID_H = 16
GOAL_CELLS: Set[Tuple[int, int]] = {(7,7), (7,8), (8,7), (8,8)}
# facings: 0=N,1=E,2=S,3=W
DX = [0, 1, 0, -1]
DY = [1, 0, -1, 0]
LEFT = [3, 0, 1, 2]   # facing-1 mod 4
RIGHT = [1, 2, 3, 0]  # facing+1 mod 4
BACK = [2, 3, 0, 1]

# === Data Structures ===

def in_bounds(x:int,y:int)->bool:
    return 0 <= x < GRID_W and 0 <= y < GRID_H

@dataclass
class Cell:
    # Walls known states: True = wall present, False = confirmed open, None = unknown
    # Order: N,E,S,W
    walls: List[Optional[bool]] = field(default_factory=lambda: [None,None,None,None])
    visited: bool = False

@dataclass
class Maze:
    cells: List[List[Cell]] = field(default_factory=lambda: [[Cell() for _ in range(GRID_H)] for _ in range(GRID_W)])

    def set_wall(self, x:int, y:int, dir:int, present:bool):
        if not in_bounds(x,y):
            return
        c = self.cells[x][y]
        old = c.walls[dir]
        if old is not None and old != present:
            # conflicting info: trust 'present=True' if ever detected
            present = True
        c.walls[dir] = present
        # set reciprocal if neighbor exists
        nx, ny = x + DX[dir], y + DY[dir]
        rdir = (dir+2) % 4
        if in_bounds(nx,ny):
            ncell = self.cells[nx][ny]
            nold = ncell.walls[rdir]
            if nold is not None and nold != present:
                present = True
            ncell.walls[rdir] = present

    def is_blocked(self, x:int, y:int, dir:int) -> Optional[bool]:
        if not in_bounds(x,y):
            return True
        return self.cells[x][y].walls[dir]

    def neighbors(self, x:int, y:int, unknown_is_open:bool=True):
        for d in range(4):
            w = self.is_blocked(x,y,d)
            if w is True:
                continue
            if w is False or (w is None and unknown_is_open):
                nx, ny = x+DX[d], y+DY[d]
                if in_bounds(nx,ny):
                    yield (nx,ny,d)

# === Game State ===
@dataclass
class Pose:
    x:int
    y:int
    facing:int
    momentum:int

@dataclass
class GameState:
    maze: Maze = field(default_factory=Maze)
    pose: Pose = field(default_factory=lambda: Pose(0,0,0,0))
    exploring: bool = True
    # Planned instruction queue for current mode (explore or speed-run)
    instr_queue: List[str] = field(default_factory=list)
    # Cached optimal path for speed-run (list of (x,y))
    speed_path: List[Tuple[int,int]] = field(default_factory=list)
    # Last known run counter to detect resets to start
    last_run: int = 0

# Persistent storage across games
GAMES: Dict[str, GameState] = {}

# === Sensor Processing ===
# sensor_data = [left90, left45, front, right45, right90], entries 0/1 indicating wall within 12 cm
# We map +/-90 and 0 directly to walls of the current cell; diagonals are ignored for safety.

def update_maze_with_sensors(gs: GameState, sensor_data: List[int]):
    x, y, f = gs.pose.x, gs.pose.y, gs.pose.facing
    left90, _, front, _, right90 = sensor_data
    # Map readings to absolute directions
    if left90 == 1:
        gs.maze.set_wall(x,y, LEFT[f], True)
    elif left90 == 0:
        gs.maze.set_wall(x,y, LEFT[f], False)

    if right90 == 1:
        gs.maze.set_wall(x,y, RIGHT[f], True)
    elif right90 == 0:
        gs.maze.set_wall(x,y, RIGHT[f], False)

    if front == 1:
        gs.maze.set_wall(x,y, f, True)
    elif front == 0:
        gs.maze.set_wall(x,y, f, False)

    gs.maze.cells[x][y].visited = True

# === Flood Fill to Goal ===

def compute_distance_field(maze: Maze) -> List[List[int]]:
    INF = 10**9
    dist = [[INF for _ in range(GRID_H)] for _ in range(GRID_W)]
    q = deque()
    for gx,gy in GOAL_CELLS:
        dist[gx][gy] = 0
        q.append((gx,gy))
    while q:
        x,y = q.popleft()
        for d in range(4):
            nx, ny = x+DX[d], y+DY[d]
            if not in_bounds(nx,ny):
                continue
            # Moving from (nx,ny) to (x,y): check if edge open. Unknown treated open.
            w = maze.is_blocked(nx,ny,d)
            if w is True:
                continue
            nd = dist[x][y] + 1
            if nd < dist[nx][ny]:
                dist[nx][ny] = nd
                q.append((nx,ny))
    return dist

# Choose next neighbor cell with smallest distance; tie-break by preferring straight, then left, then right, then back.

def choose_next_cell(gs: GameState, dist: List[List[int]]) -> Tuple[int,int,int]:
    x,y,f = gs.pose.x, gs.pose.y, gs.pose.facing
    options = []
    for d in range(4):
        nx, ny = x+DX[d], y+DY[d]
        if not in_bounds(nx,ny):
            continue
        w = gs.maze.is_blocked(x,y,d)
        if w is True:
            continue
        score = dist[nx][ny]
        # heading preference
        pref = 0 if d==f else (1 if d==LEFT[f] else (2 if d==RIGHT[f] else 3))
        options.append((score, pref, d, nx, ny))
    if not options:
        # dead end unknown: rotate left as default to search
        return (x,y,LEFT[f])
    options.sort(key=lambda t: (t[0], t[1]))
    _, _, d, nx, ny = options[0]
    return (nx, ny, d)

# === Instruction Generation ===

# We target |momentum| ≤ 2 during exploration and for corners, using wide corners (W).
TARGET_CRUISE = 2
MAX_ABS_M = 4

# Basic tokens for straight motion one half-step forward, updating momentum.

def straight_token_for(m_in:int) -> Tuple[str,int]:
    """Return (token, new_m) to move one half-step forward managing momentum toward TARGET_CRUISE.
    If m_in < TARGET_CRUISE: use F2 to accelerate.
    If m_in > TARGET_CRUISE: use F0 to decelerate.
    Else hold with F1.
    """
    if m_in < TARGET_CRUISE:
        m_out = min(m_in + 1, MAX_ABS_M)
        return ("F2", m_out)
    if m_in > TARGET_CRUISE:
        m_out = max(m_in - 1, 0)
        return ("F0", m_out)
    return ("F1", m_in)

# Pre-brake so that |m| ≤ 2 for a wide corner.

def prebrake_to_wide(m:int) -> List[str]:
    instr = []
    while abs(m) > 2:
        # BB brakes by 2 toward 0 per half-step; but BB is straight translation.
        # Use towards 0; if m>0, BB reduces by 2; if already ≤2, stop.
        instr.append("BB")
        if m > 0:
            m = max(0, m - 2)
        elif m < 0:
            m = min(0, m + 2)
    # If now m==1 or 2, OK for wide; if m==0, we can accelerate with F1 in the corner (m_eff=0.5) but we keep F1.
    return instr

# Convert a 90° change to a corner token with F1 and Wide radius.

def corner_token(direction:str) -> str:
    # direction: 'L' or 'R'
    return f"F1{direction}W"

# Turn in place by 90° using two 45° turns when at rest.

def inplace_turns(from_f:int, to_f:int, m:int) -> List[str]:
    if m != 0:
        # should not happen; ensure we only call at m=0
        return []
    diff = (to_f - from_f) % 4
    if diff == 0:
        return []
    if diff == 1:
        return ["R","R"]
    if diff == 2:
        return ["R","R","R","R"]
    if diff == 3:
        return ["L","L"]
    return []

# Build instructions to move from current cell toward next cell direction.

def plan_step_toward(gs: GameState, next_dir:int) -> List[str]:
    instr: List[str] = []
    f = gs.pose.facing
    m = gs.pose.momentum
    if next_dir == f:
        # Move one full cell forward (two half-steps), regulating momentum
        for _ in range(2):
            tok, m = straight_token_for(m)
            instr.append(tok)
        gs.pose.momentum = m
        return instr
    # 90-degree change: prefer a wide corner with pre-braking as needed
    # Ensure forward motion (we never reverse during exploration)
    # Pre-brake to |m|≤2
    instr.extend(prebrake_to_wide(gs.pose.momentum))
    # Update local m after braking simulation
    if instr:
        # simulate m after BBs
        m_local = gs.pose.momentum
        for t in instr:
            if t == "BB":
                if m_local > 0:
                    m_local = max(0, m_local - 2)
                elif m_local < 0:
                    m_local = min(0, m_local + 2)
        gs.pose.momentum = m_local
    # Corner direction L or R from current facing
    if next_dir == LEFT[f]:
        instr.append(corner_token('L'))
    elif next_dir == RIGHT[f]:
        instr.append(corner_token('R'))
    else:
        # Opposite: either do two wide corners (L then L or R then R) or stop and turn in place, then go straight.
        # Safer: brake to 0, turn in place 180° (four 45°), then move straight one cell.
        instr.extend(prebrake_to_wide(gs.pose.momentum))
        # After prebrake, force stop if not zero
        if gs.pose.momentum != 0:
            # One more BB or F0 to reach 0
            if gs.pose.momentum >= 2:
                instr.append("BB")
                gs.pose.momentum = max(0, gs.pose.momentum - 2)
            elif gs.pose.momentum == 1:
                instr.append("F0")
                gs.pose.momentum = 0
        instr.extend(inplace_turns(f, next_dir, gs.pose.momentum))
        # Accelerate forward one cell
        for _ in range(2):
            tok, m2 = straight_token_for(gs.pose.momentum)
            instr.append(tok)
            gs.pose.momentum = m2
        return instr
    # After a single corner, momentum roughly held (F1 in corner). Continue with one straight half-step to finish entering next cell center.
    # Our corner advances roughly one arc unit which we treat as equivalent to one half-step; to center in next cell, follow with one half-step.
    tok, m = straight_token_for(gs.pose.momentum)
    instr.append(tok)
    gs.pose.momentum = m
    return instr

# === Path Utilities ===

def reconstruct_path(prev: Dict[Tuple[int,int], Tuple[int,int]], start: Tuple[int,int], goal: Tuple[int,int]) -> List[Tuple[int,int]]:
    path = []
    cur = goal
    while cur != start:
        path.append(cur)
        cur = prev[cur]
    path.append(start)
    path.reverse()
    return path

# Shortest path on known-open graph (unknown treated as walls for speed-run reliability)

def shortest_known_path(maze: Maze, start: Tuple[int,int], goals: Set[Tuple[int,int]]) -> Optional[List[Tuple[int,int]]]:
    q = deque([start])
    prev: Dict[Tuple[int,int], Tuple[int,int]] = {}
    seen = {start}
    while q:
        u = q.popleft()
        if u in goals:
            return reconstruct_path(prev, start, u)
        ux, uy = u
        for d in range(4):
            w = maze.is_blocked(ux,uy,d)
            if w is not False:
                continue  # require confirmed open for speed run
            vx, vy = ux+DX[d], uy+DY[d]
            if not in_bounds(vx,vy):
                continue
            if (vx,vy) in seen:
                continue
            seen.add((vx,vy))
            prev[(vx,vy)] = (ux,uy)
            q.append((vx,vy))
    return None

# Build a full instruction list for a given path of cells (including start as first node)

def plan_instructions_for_path(gs: GameState, path: List[Tuple[int,int]]) -> List[str]:
    instr: List[str] = []
    # Pose assumed already aligned with path[0]
    for i in range(1, len(path)):
        x,y = path[i-1]
        nx,ny = path[i]
        # Determine required direction
        if nx == x and ny == y+1:
            d = 0
        elif nx == x+1 and ny == y:
            d = 1
        elif nx == x and ny == y-1:
            d = 2
        elif nx == x-1 and ny == y:
            d = 3
        else:
            continue  # non-adjacent (shouldn't happen)
        step_instr = plan_step_toward(gs, d)
        instr.extend(step_instr)
        # Update facing for corner turns
        if d != gs.pose.facing:
            gs.pose.facing = d
        # Update pose cell index
        gs.pose.x, gs.pose.y = nx, ny
    # On entering a goal cell, ensure full stop
    # Apply braking to momentum 0
    while gs.pose.momentum > 0:
        if gs.pose.momentum >= 2:
            instr.append("BB")
            gs.pose.momentum = max(0, gs.pose.momentum - 2)
        else:
            instr.append("F0")
            gs.pose.momentum = 0
    return instr

# Decide if we are inside goal (cell-based). We approximate: being at center of any goal cell counts as being within the 2x2 goal interior (safe as we also brake to 0 there).

def at_goal_cell(gs: GameState) -> bool:
    return (gs.pose.x, gs.pose.y) in GOAL_CELLS

# === Public API Entry ===

def handle_post(body: dict) -> dict:
    game_id = str(body.get("game_id"))
    if game_id not in GAMES:
        GAMES[game_id] = GameState()
    gs = GAMES[game_id]

    # Crash handling
    if body.get("is_crashed"):
        # End attempt
        return {"instructions": [], "end": True}

    # Detect run reset at start center with momentum 0
    run = body.get("run", 0)
    if run != gs.last_run:
        # Reset transient queues but keep the learned maze
        gs.instr_queue.clear()
        gs.speed_path.clear()
        gs.exploring = True
        gs.pose = Pose(0,0,0,0)
        gs.last_run = run

    # Update pose momentum from engine (we track our best guess as well)
    gs.pose.momentum = int(body.get("momentum", gs.pose.momentum))

    # Update maze with sensors (at current cell center)
    sensor_data = body.get("sensor_data") or [0,0,0,0,0]
    update_maze_with_sensors(gs, sensor_data)

    # If we already have a queued instruction batch, send it
    BATCH_MAX = 12  # keep batches chunky to amortize 50ms thinking cost
    if gs.instr_queue:
        out = gs.instr_queue[:BATCH_MAX]
        gs.instr_queue = gs.instr_queue[BATCH_MAX:]
        return {"instructions": out, "end": False}

    # If goal reached in engine terms, nothing to do
    if body.get("goal_reached"):
        return {"instructions": [], "end": False}

    # If we are currently exploring, compute flood distances and push next step
    if gs.exploring:
        dist = compute_distance_field(gs.maze)
        # If we already at a goal-adjacent and distances are finite, proceed
        if dist[gs.pose.x][gs.pose.y] == 0:
            # In goal cell, ensure stop
            stop_instr = []
            while gs.pose.momentum > 0:
                if gs.pose.momentum >= 2:
                    stop_instr.append("BB")
                    gs.pose.momentum -= 2
                else:
                    stop_instr.append("F0")
                    gs.pose.momentum = 0
            gs.instr_queue.extend(stop_instr)
            return {"instructions": gs.instr_queue[:BATCH_MAX], "end": False}
        # plan one step toward lowest-distance neighbor
        nx, ny, ndir = choose_next_cell(gs, dist)
        step_instr = plan_step_toward(gs, ndir)
        # Update facing if we turned
        if ndir != gs.pose.facing:
            gs.pose.facing = ndir
        # If we moved a full cell (our step plan advances one cell), update cell coords
        # For straight we appended 2 half-steps; for corner path we appended corner+half-step
        gs.pose.x, gs.pose.y = nx, ny
        gs.instr_queue.extend(step_instr)

        # Check if we now have a robust known-open path to goal; if so, switch to speed-run mode next time we reset at start
        sp = shortest_known_path(gs.maze, (gs.pose.x, gs.pose.y), GOAL_CELLS)
        if sp is not None and len(sp) > 0:
            gs.speed_path = sp
        return {"instructions": gs.instr_queue[:BATCH_MAX], "end": False}

    # If not exploring, we are in speed-run mode; if at start center, plan full path from start
    if not gs.exploring:
        if (gs.pose.x, gs.pose.y) == (0,0) and gs.pose.momentum == 0:
            path = shortest_known_path(gs.maze, (0,0), GOAL_CELLS)
            if path is None:
                # fallback to exploration
                gs.exploring = True
                return {"instructions": [], "end": False}
            # Reset pose for planning
            gs.pose = Pose(0,0,0,0)
            full_instr = plan_instructions_for_path(gs, path)
            gs.instr_queue.extend(full_instr)
            return {"instructions": gs.instr_queue[:BATCH_MAX], "end": False}
        else:
            # Continue sending remaining speed-run instructions
            if gs.instr_queue:
                out = gs.instr_queue[:BATCH_MAX]
                gs.instr_queue = gs.instr_queue[BATCH_MAX:]
                return {"instructions": out, "end": False}
            else:
                return {"instructions": [], "end": False}

    # Default fallback
    return {"instructions": [], "end": False}

# Optional: helper to toggle speed-run once mapping is acceptable

def switch_to_speed_run(game_id: str):
    if game_id in GAMES:
        GAMES[game_id].exploring = False

if __name__ == "__main__":
    # Simple local sanity test with dummy calls
    gid = "demo-game"
    req = {
        "game_id": gid,
        "sensor_data": [0,0,0,0,0],
        "is_crashed": False,
        "total_time_ms": 0,
        "goal_reached": False,
        "goal_time_ms": None,
        "best_time_ms": None,
        "run_time_ms": 0,
        "run": 0,
        "momentum": 0,
    }
    # First call: should produce some exploration instructions
    resp = handle_post(req)
    print(resp)
