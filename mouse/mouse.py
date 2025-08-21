# from flask import Flask, request, jsonify
from typing import List, Dict, Any


# ---- Helpers ---------------------------------------------------------------

def brake_to_zero_tokens(m: int, max_tokens: int = 3) -> List[str]:
    """
    Return up to max_tokens needed tokens to reduce forward momentum m>=0 to 0.
    Uses BB (brake by 2) then F0 (decel by 1) as needed.
    """
    if m <= 0:
        return []
    toks = []
    cur = m
    while cur > 0 and len(toks) < max_tokens:
        if cur >= 2:
            toks.append("BB")
            cur -= 2
        else:
            toks.append("F0")  # m -> m-1
            cur -= 1
    return toks

def accel_forward_tokens(m: int, target: int = 2, max_tokens: int = 3) -> List[str]:
    """
    From current forward momentum m>=0, add up to max_tokens to climb toward target.
    Caps at +4 per rules. Uses F2 (accelerate +1) and F1 (hold) to progress.
    We keep it conservative: at most 1 acceleration then hold.
    """
    toks = []
    cur = max(0, m)
    # accelerate at most once per batch to stay cautious
    if cur < target and len(toks) < max_tokens:
        toks.append("F2")
        cur = min(cur + 1, 4)
    # Optional: one hold to actually move with current momentum
    if len(toks) < max_tokens:
        toks.append("F1")
    return toks

def turn_in_place_tokens(direction: str, m: int, max_tokens: int = 3) -> List[str]:
    """
    Ensure momentum is zero, then turn 45° in place (L or R).
    Never turn while moving (avoids implicit coast legality checks).
    """
    toks = []
    toks += brake_to_zero_tokens(m, max_tokens=max_tokens)
    if len(toks) < max_tokens:
        toks.append("L" if direction == "L" else "R")
    return toks

def choose_instructions(body: Dict[str, Any]) -> List[str]:
    """
    Very conservative, legal instruction generator:
    - If goal reached or crashed, do nothing meaningful (but keep non-empty per spec).
    - If front blocked: stop and turn left (left-hand rule).
    - Else: go forward (accelerate a bit, then hold).
    """
    m = int(body.get("momentum", 0) or 0)
    sensors = body.get("sensor_data") or [0, 0, 0, 0, 0]
    is_crashed = bool(body.get("is_crashed", False))
    goal_reached = bool(body.get("goal_reached", False))

    # Always return a non-empty instruction list (spec: empty => invalid attempt)
    if is_crashed or goal_reached:
        # Harmless token at rest; if moving, brake once.
        toks = brake_to_zero_tokens(m, max_tokens=2)
        if not toks:
            toks = ["BB"]  # valid no-op at rest (200 ms cost, judge may ignore if it ends immediately)
        return toks

    # Interpret sensors as booleans: 1 = clear, 0 = blocked within 12 cm
    # indexes: 0:-90(L), 1:-45, 2:0(front), 3:+45, 4:+90(R)
    left_clear   = bool(sensors[0])
    front_clear  = bool(sensors[2])
    right_clear  = bool(sensors[4])

    # If front blocked, left-hand rule: prefer turning left; else right; else U-turn (two rights)
    if not front_clear:
        if left_clear:
            return turn_in_place_tokens("L", m, max_tokens=3)
        elif right_clear:
            return turn_in_place_tokens("R", m, max_tokens=3)
        else:
            # Dead-end: brake to zero and start a 90° turn (two 45° rights across batches).
            toks = turn_in_place_tokens("R", m, max_tokens=2)
            # Keep batch short to remain reactive; next request can do another 'R'.
            return toks

    # Front is clear: move forward conservatively
    return accel_forward_tokens(m, target=2, max_tokens=2)

# ---- Flask endpoint --------------------------------------------------------

# @app.route("/micro-mouse", methods=["POST"])
# def micro_mouse():
#     body = request.get_json(silent=True) or {}
#     instructions = choose_instructions(body)

#     # End the run if the judge already says goal or crash
#     end = bool(body.get("goal_reached")) or bool(body.get("is_crashed"))