from functools import lru_cache
import json
import sys

def smallest_pal_after_k_deletions(s: str, K: int) -> str:
    n = len(s)

    @lru_cache(maxsize=None)
    def solve(i: int, j: int, k: int) -> str | None:
        # Return the lexicographically smallest palindrome from s[i..j]
        # using at most k deletions; return None if impossible.
        if k < 0:
            return None
        if i > j:
            return ""  # empty string is a palindrome
        if i == j:
            # Either keep the single character, or delete it if we can ("" is lexicographically smaller)
            return "" if k >= 1 else s[i]

        candidates = []

        if s[i] == s[j]:
            inner = solve(i + 1, j - 1, k)
            if inner is not None:
                candidates.append(s[i] + inner + s[j])

        # Delete left
        if k >= 1:
            left = solve(i + 1, j, k - 1)
            if left is not None:
                candidates.append(left)

        # Delete right
        if k >= 1:
            right = solve(i, j - 1, k - 1)
            if right is not None:
                candidates.append(right)

        # Delete both ends (cost 2)
        if k >= 2:
            both = solve(i + 1, j - 1, k - 2)
            if both is not None:
                candidates.append(both)

        if not candidates:
            return None
        # Lexicographically smallest
        return min(candidates)

    ans = solve(0, n - 1, K)
    # If completely impossible (shouldn’t happen because we could delete all if K >= n),
    # normalize to "IMPOSSIBLE"
    return ans if ans is not None else "IMPOSSIBLE"


# --- Helpers for your judge ---

def solve_evaluate_payload(payload: dict) -> dict:
    """
    payload: { "testCases": [ { "id": "0001", "input": { "s": "madam", "k": 1 } }, ... ] }
    returns: { "solutions": [ { "id": "0001", "result": "maam" }, ... ] }
    """
    out = []
    for tc in payload.get("testCases", []):
        tid = tc["id"]
        s = tc["input"]["s"]
        k = tc["input"]["k"]
        result = smallest_pal_after_k_deletions(s, k)
        # Ensure the result is a palindrome and within budget; else mark IMPOSSIBLE.
        def is_pal(x): return x == x[::-1]
        if not is_pal(result):
            result = "IMPOSSIBLE"
        elif len(s) - len(result) > k:
            result = "IMPOSSIBLE"
        out.append({ "id": tid, "result": result })
    return { "solutions": out }


# If you want to run locally:
# - Pipe a JSON payload into stdin (matching the /evaluate schema)
# - Get the solutions JSON on stdout
# if __name__ == "__main__":
    
