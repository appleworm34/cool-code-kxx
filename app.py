from flask import Flask, request, jsonify
from spy.spy import find_extra_channels
from dataclasses import dataclass

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello World!'

@app.route('/investigate', methods=['POST'])
def spy():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    # parse json input
    data = request.get_json()
    print("Data: ")
    print(data)
    
    
    # networks = data.get("networks")
    
    result = find_extra_channels(data)
    print("Result: ")
    print(result)
    
    return result, 200

# app.py
# Minimal micromouse controller server.
# Exposes POST /micromouse and returns {"instructions":[...], "end": false}
# Strategy: right-hand wall following, cruise at m=+1, cardinal moves only.
# ---- Maze/heading utilities ----


GOAL_CELLS = {(7,7),(7,8),(8,7),(8,8)}
VEC  = {'N':(0,1), 'E':(1,0), 'S':(0,-1), 'W':(-1,0)}
RIGHT = {'N':'E','E':'S','S':'W','W':'N'}
LEFT  = {'N':'W','W':'S','S':'E','E':'N'}
BACK  = {'N':'S','S':'N','E':'W','W':'E'}
SIDES = ['N','E','S','W']
SIDE_VEC = {'N':(0,1),'E':(1,0),'S':(0,-1),'W':(-1,0)}

def in_bounds(x,y): return 0 <= x < 16 and 0 <= y < 16
def is_goal_cell(c): return c in GOAL_CELLS

@dataclass
class MouseState:
    cell: tuple[int,int] = (0,0)
    heading: str = 'N'
    momentum: int = 0
    # walls: {(x,y,'N'|'E'|'S'|'W')} means a wall on that edge from cell (x,y)
    walls: set = None

    def __post_init__(self):
        if self.walls is None:
            self.walls = set()
# ---- Core controller ----

class MicroMouseController:
    def __init__(self):
        self.state = MouseState()

    # ---- sensing helpers (array [-90,-45,0,+45,+90], 1=wall) ----
    def _front_blocked(self, sd): return (sd[2] == 1)
    def _right_blocked(self, sd): return (sd[4] == 1)
    def _left_blocked (self, sd): return (sd[0] == 1)

    def _mark_wall(self, side):
        x,y = self.state.cell
        h = self.state.heading
        side_dir = {'F': h, 'R': RIGHT[h], 'L': LEFT[h]}[side]
        self.state.walls.add((x,y,side_dir))
        dx,dy = SIDE_VEC[side_dir]
        nx,ny = x+dx, y+dy
        if in_bounds(nx,ny):
            self.state.walls.add((nx,ny, BACK[side_dir]))

    # ---- map access: is there a wall between cell and neighbor dir? ----
    def _has_wall(self, cell, dirc):
        x,y = cell
        return (x,y,dirc) in self.state.walls

    # ---- flood-fill distances to goal using *known* walls; unknown edges are open ----
    def _compute_dist(self):
        INF = 10**9
        dist = [[INF]*16 for _ in range(16)]
        dq = deque()
        for gx,gy in GOAL_CELLS:
            dist[gx][gy] = 0
            dq.append((gx,gy))
        while dq:
            x,y = dq.popleft()
            d = dist[x][y]
            for dirc in SIDES:
                dx,dy = SIDE_VEC[dirc]
                nx,ny = x+dx, y+dy
                if not in_bounds(nx,ny): continue
                # movement allowed if NO wall on the edge between (x,y) and (nx,ny)
                # We must check both sides to be safe with partial knowledge.
                if self._has_wall((x,y), dirc): 
                    continue
                if self._has_wall((nx,ny), BACK[dirc]): 
                    continue
                if dist[nx][ny] > d + 1:
                    dist[nx][ny] = d+1
                    dq.append((nx,ny))
        return dist

    # ---- choose next neighbor cell that *reduces* flood value ----
    def _choose_next_dir(self, dist):
        x,y = self.state.cell
        best = None
        bestd = 10**9
        for dirc in SIDES:
            dx,dy = SIDE_VEC[dirc]
            nx,ny = x+dx, y+dy
            if not in_bounds(nx,ny): 
                continue
            # block if *known* wall in that direction
            if self._has_wall((x,y), dirc):
                continue
            if dist[nx][ny] < bestd:
                bestd = dist[nx][ny]
                best = dirc
        return best  # returns 'N'|'E'|'S'|'W' or None if boxed in (rare)

    # ---- low-level motion primitives (all tokens legal & simple) ----
    def _ensure_rest(self):
        # If cruising (m=1), brake one half-step to stop (F0).
        toks = []
        if self.state.momentum > 0:
            toks.append('F0')    # time-charged half-step; lands at next half-vertex
            self.state.momentum = 0
        return toks

    def _rotate_to(self, target_heading):
        # Rotate in-place at rest using 45° increments.
        # We only use multiples of 90° (two L or two R).
        seq = []
        h = self.state.heading
        # compute clockwise steps in 90° units
        def idx(d): return {'N':0,'E':1,'S':2,'W':3}[d]
        cur, tgt = idx(h), idx(target_heading)
        cw = (tgt - cur) % 4
        ccw = (cur - tgt) % 4
        if cw <= ccw:
            # cw times 90° right => two 'R' per 90°
            for _ in range(cw):
                seq += ['R','R']
            self.state.heading = target_heading
        else:
            for _ in range(ccw):
                seq += ['L','L']
            self.state.heading = target_heading
        return seq

    def _forward_one_cell(self):
        # Move exactly one cell forward, end with m=1.
        toks = ['F2','F1'] if self.state.momentum == 0 else ['F1','F1']
        # update pose
        dx,dy = VEC[self.state.heading]
        x,y = self.state.cell
        self.state.cell = (x+dx, y+dy)
        self.state.momentum = 1
        return toks

    def _finish_if_goal(self):
        # If we are in any goal cell and currently m=1, brake to 0 inside.
        if is_goal_cell(self.state.cell) and self.state.momentum == 1:
            self.state.momentum = 0
            return ['F0']
        return []

    # ---- main step: sense -> map -> flood -> act ----
    def step(self, payload: dict) -> list[str]:
        # sync momentum hint
        self.state.momentum = 1 if payload.get("momentum", 0) > 0 else 0

        sd = payload.get("sensor_data", [0,0,0,0,0]) or [0,0,0,0,0]
        # Update walls from sensors at current vertex
        if self._front_blocked(sd): self._mark_wall('F')
        if self._right_blocked(sd): self._mark_wall('R')
        if self._left_blocked (sd): self._mark_wall('L')

        # Compute flood distances from current known map
        dist = self._compute_dist()
        # Pick best neighbor direction (toward lower distance)
        desired = self._choose_next_dir(dist)

        tokens: list[str] = []

        # If boxed by walls (shouldn't happen often), do a safe U-turn at rest
        if desired is None:
            tokens += self._ensure_rest()
            tokens += self._rotate_to(BACK[self.state.heading])
            tokens += self._forward_one_cell()
            fin = self._finish_if_goal()
            return tokens + fin

        # If we need to turn, do it at rest to avoid moving-turn complexity
        if desired != self.state.heading:
            tokens += self._ensure_rest()
            tokens += self._rotate_to(desired)

        # Move forward. In straight hallways we’ll keep cruising and batch 2 cells.
        # Check simple hallway condition using known map: left & right walls present.
        # (Relative to desired heading after rotation)
        # Determine walls on sides from map
        h = self.state.heading  # now equals desired
        left_dir = LEFT[h]
        right_dir = RIGHT[h]
        x,y = self.state.cell
        left_wall  = self._has_wall((x,y), left_dir)
        right_wall = self._has_wall((x,y), right_dir)

        # stride = 2 cells in a straight corridor
        stride = 2 if (left_wall and right_wall and not self._has_wall((x,y), h)) else 1
        for _ in range(stride):
            tokens += self._forward_one_cell()
            fin = self._finish_if_goal()
            if fin:
                return tokens + fin

        # Always non-empty
        return tokens

# one controller per game_id (memory store; replace with redis if you need scaling)
CONTROLLERS: dict[str, MicroMouseController] = {}

@app.post("/micro-mouse")
def micromouse():
    payload = request.get_json(force=True) or {}

    gid = str(payload.get("game_id") or "default")
    ctrl = CONTROLLERS.get(gid)
    if ctrl is None:
        ctrl = MicroMouseController()
        CONTROLLERS[gid] = ctrl

    # If the platform signals a crash or total time exhaustion, you could clear state:
    # if payload.get("is_crashed") or (payload.get("total_time_ms", 0) >= 60000):
    #     CONTROLLERS.pop(gid, None)

    instr = ctrl.step(payload)
    return jsonify({"instructions": instr, "end": False})

if __name__ == '__main__':
    app.run()