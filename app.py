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
DIRS = ['N','E','S','W']
VEC  = {'N':(0,1), 'E':(1,0), 'S':(0,-1), 'W':(-1,0)}
RIGHT = {'N':'E','E':'S','S':'W','W':'N'}
LEFT  = {'N':'W','W':'S','S':'E','E':'N'}
BACK  = {'N':'S','S':'N','E':'W','W':'E'}

def in_bounds(x,y): return 0 <= x < 16 and 0 <= y < 16
def is_goal_cell(c): return c in GOAL_CELLS

# ---- Controller state ----

@dataclass
class MouseState:
    cell: tuple[int,int] = (0,0)  # cell coords (0..15, 0..15), start at bottom-left
    heading: str = 'N'
    momentum: int = 0             # our intended policy: 0 or +1
    walls: set = None             # {(x,y,'N'|'E'|'S'|'W')}

    def __post_init__(self):
        if self.walls is None:
            self.walls = set()

# ---- Core controller ----

class MicroMouseController:
    def __init__(self):
        self.state = MouseState()

    # --- sensors (array: [-90, -45, 0, +45, +90], 1=wall within 12cm) ---
    def _front_blocked(self, sd): return (sd[2] == 1)
    def _right_blocked(self, sd): return (sd[4] == 1)
    def _left_blocked (self, sd): return (sd[0] == 1)

    def _mark_wall(self, side):
        # Optional map-building (not required for base solve)
        x,y = self.state.cell
        h = self.state.heading
        side_dir = {'F': h, 'R': RIGHT[h], 'L': LEFT[h]}[side]
        self.state.walls.add((x,y,side_dir))
        dx,dy = VEC[side_dir]
        nx,ny = x+dx, y+dy
        if in_bounds(nx,ny):
            self.state.walls.add((nx,ny, BACK[side_dir]))

    def _front_open(self, sd):
        x,y = self.state.cell
        dx,dy = VEC[self.state.heading]
        nx,ny = x+dx, y+dy
        return (not self._front_blocked(sd)) and in_bounds(nx,ny)

    def _right_open(self, sd):
        rh = RIGHT[self.state.heading]
        dx,dy = VEC[rh]
        nx,ny = self.state.cell[0]+dx, self.state.cell[1]+dy
        return (not self._right_blocked(sd)) and in_bounds(nx,ny)

    def _left_open(self, sd):
        lh = LEFT[self.state.heading]
        dx,dy = VEC[lh]
        nx,ny = self.state.cell[0]+dx, self.state.cell[1]+dy
        return (not self._left_blocked(sd)) and in_bounds(nx,ny)

    # --- state updates after committing to a 1-cell move ---
    def _advance_cell(self, heading):
        x,y = self.state.cell
        dx,dy = VEC[heading]
        self.state.cell = (x+dx, y+dy)

    # --- motion templates (each performs exactly 1 cell and ends with m=+1) ---
    def _move_forward_one_cell(self):
        toks = ['F2','F1'] if self.state.momentum == 0 else ['F1','F1']
        self._advance_cell(self.state.heading)
        self.state.momentum = 1
        return toks

    def _turn_right_and_advance_one_cell(self):
        # moving 90° turn via two 45° rights; ensure we're moving first
        toks = ['F2','R','R','F1']
        self.state.heading = RIGHT[self.state.heading]
        self._advance_cell(self.state.heading)
        self.state.momentum = 1
        return toks

    def _turn_left_and_advance_one_cell(self):
        toks = ['F2','L','L','F1']
        self.state.heading = LEFT[self.state.heading]
        self._advance_cell(self.state.heading)
        self.state.momentum = 1
        return toks

    def _u_turn_and_advance_one_cell(self):
        toks = ['F2','R','R','R','R','F1']  # 180° right
        self.state.heading = BACK[self.state.heading]
        self._advance_cell(self.state.heading)
        self.state.momentum = 1
        return toks

    # --- finishing logic (brake inside goal) ---
    def _finish_if_goal(self):
        if is_goal_cell(self.state.cell) and self.state.momentum == 1:
            self.state.momentum = 0
            return ['F0']  # one timed half-step, momentum -> 0 inside goal
        return []

    # --- main step ---
    def step(self, payload: dict) -> list[str]:
        # Sync momentum hint from platform, if provided
        self.state.momentum = 1 if payload.get("momentum", 0) > 0 else 0

        sd = payload.get("sensor_data", [0,0,0,0,0]) or [0,0,0,0,0]
        # annotate optional walls
        if self._front_blocked(sd): self._mark_wall('F')
        if self._right_blocked(sd): self._mark_wall('R')
        if self._left_blocked (sd): self._mark_wall('L')

        right_open = self._right_open(sd)
        front_open = self._front_open(sd)
        left_open  = self._left_open(sd)

        tokens: list[str] = []

        # Hallway batching: walls both sides & front open → stride 2 cells
        if (not right_open) and (not left_open) and front_open:
            for _ in range(2):  # conservative; increase to 3–4 if safe
                tokens += self._move_forward_one_cell()
                fin = self._finish_if_goal()
                if fin:
                    return tokens + fin
        else:
            # Right-hand rule priority
            if right_open:
                tokens += self._turn_right_and_advance_one_cell()
            elif front_open:
                tokens += self._move_forward_one_cell()
            elif left_open:
                tokens += self._turn_left_and_advance_one_cell()
            else:
                tokens += self._u_turn_and_advance_one_cell()

            fin = self._finish_if_goal()
            if fin:
                return tokens + fin

        # Always return at least something (spec: empty instructions invalidates attempt)
        if not tokens:
            tokens = ['L','L']  # in-place 90° (useful for re-sensing)

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