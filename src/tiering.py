"""
Jenks natural breaks (Fisher's exact 1D optimal classification), with an
automatic class count chosen by capping how wide any single tier's point
spread is allowed to be -- rather than by a target Goodness-of-Variance-Fit
(GVF) threshold.

This module went through two designs before landing here (see git history
/ SESSION_NOTES.md for the full story) -- worth recording why, since both
looked reasonable until tested against the real 2026 projection data:

1. First replaced a simpler "flag statistically unusual gaps" approach
   (mean+stdev of every gap in the position) with Jenks partitioning + a
   GVF-based stopping rule (grow k until GVF clears a target, or until an
   extra class stops helping). That fixed the original problem's root
   cause (one huge late-list cliff no longer drowns out smaller real
   breaks near the top), but a single absolute GVF target behaves very
   differently across positions of very different size: for a large pool
   (QB, ~80 players) it still left an enormous, gradually-declining top
   tier (30 players spanning 218 points) because splitting that cluster
   further just wasn't where the *global* variance-reduction budget was
   best spent -- the algorithm is directly optimizing whole-position
   variance, not "does this look like too many players to call one tier."
   For a small pool (5-6 players, including this module's own tests) the
   same target forced near-total fragmentation, since GVF necessarily
   rushes toward 1.0 as k approaches n for small n.
2. Then tried a recursive/local variant (split into 2 wherever a subset's
   own local gaps contain a statistical outlier, recurse into each half).
   This fixed the small-n over-fragmentation problem but reintroduced the
   large-pool one from the opposite direction: a large, smoothly-declining
   cluster (no single standout gap, just a long gradual slope) has no
   local outlier gap to trigger a split at all, so it never gets broken up
   even though 30 players spanning 218 points is clearly "too wide" by any
   practical drafting standard.

Both failure modes share a root cause: neither approach ever asks the
actually-relevant question, "how wide is this tier allowed to get?" They
infer an answer indirectly from gap statistics. jenks_auto_labels() here
asks it directly: cap a tier's spread (top score minus bottom score) at
max_spread_fraction of that position's own total point range, then use
Jenks purely for what it's actually best at -- given a target class count,
find the placement of breaks that minimizes within-class variance -- while
increasing that class count only as far as needed to satisfy the spread
cap. This scales automatically per position (a QB pool spanning 750 points
gets wider absolute tiers than a Kicker pool spanning 140) without the
GVF-elbow's sensitivity to n or the local-outlier variant's blindness to
gradual-but-real cumulative drift.
"""

from __future__ import annotations

import numpy as np


def _jenks_fit(values: np.ndarray, max_classes: int):
    """Fisher's exact DP for 1D natural-breaks classification, computed
    once for every class count from 1..max_classes simultaneously (the
    classic O(n^2 * max_classes) algorithm naturally fills in every k as a
    byproduct of computing the largest one). values must be sorted
    ascending.

    Returns (mat1, mat2): mat2[l][j] is the minimum achievable sum of
    within-class squared deviations partitioning the first l values into j
    classes; mat1[l][j] is the (1-indexed) start position of the last
    class in that optimal partition, used to backtrace actual class
    boundaries for any j <= max_classes.
    """
    n = len(values)
    mat1 = [[0] * (max_classes + 1) for _ in range(n + 1)]
    mat2 = [[0.0] * (max_classes + 1) for _ in range(n + 1)]

    for j in range(1, max_classes + 1):
        mat1[1][j] = 1
        mat2[1][j] = 0.0
        for l in range(2, n + 1):
            mat2[l][j] = float("inf")

    v = 0.0
    for l in range(2, n + 1):
        s1 = s2 = w = 0.0
        for m in range(1, l + 1):
            i3 = l - m + 1
            val = values[i3 - 1]
            s2 += val * val
            s1 += val
            w += 1
            v = s2 - (s1 * s1) / w
            i4 = i3 - 1
            if i4 != 0:
                for j in range(2, max_classes + 1):
                    if mat2[l][j] >= (v + mat2[i4][j - 1]):
                        mat1[l][j] = i3
                        mat2[l][j] = v + mat2[i4][j - 1]
        mat1[l][1] = 1
        mat2[l][1] = v

    return mat1, mat2


def _labels_for_k(mat1, n: int, k: int) -> np.ndarray:
    """Backtrace mat1 to get a 0-indexed class label (0 = lowest values)
    for each of the n sorted values, for a specific class count k."""
    class_start = [0] * (k + 1)  # 1-indexed start position of each class
    pos = n
    count = k
    while count >= 2:
        start = mat1[pos][count]
        class_start[count] = start
        pos = start - 1
        count -= 1
    class_start[1] = 1

    labels = np.zeros(n, dtype=int)
    for c in range(1, k + 1):
        start0 = class_start[c] - 1
        end0 = (class_start[c + 1] - 1) if c < k else n
        labels[start0:end0] = c - 1
    return labels


def _widest_class_spread(sorted_vals: np.ndarray, labels: np.ndarray) -> float:
    widest = 0.0
    for lbl in np.unique(labels):
        class_vals = sorted_vals[labels == lbl]
        widest = max(widest, float(class_vals.max() - class_vals.min()))
    return widest


def jenks_auto_labels(
    values: np.ndarray,
    max_classes: int = 15,
    max_spread_fraction: float = 0.08,
) -> tuple[np.ndarray, int, float]:
    """Cluster `values` (any order) into Jenks natural-break classes, with
    the class count chosen automatically so no class spans more than
    max_spread_fraction of the full value range (e.g. 0.08 = no tier
    covers more than 8% of that position's top-to-bottom point spread).

    Returns (labels, k, widest_spread):
      - labels: same length/order as the input `values`, each an int class
        label where 0 = lowest-value class (callers wanting "tier 1 =
        best" should invert against whichever direction is "best" for
        their data).
      - k: the number of classes actually chosen.
      - widest_spread: the largest single class's point spread actually
        achieved at that k (<=  the spread cap, unless max_classes was
        reached first -- see below).

    Class count selection: try k = 1, 2, 3, ... up to max_classes (capped
    at the number of distinct values, since you can't have more classes
    than distinct points), and stop at the smallest k whose widest
    resulting class is within the spread cap. If max_classes is reached
    first without satisfying the cap (e.g. a genuinely huge pool with a
    very tight cap), returns that best-effort partition rather than
    growing without bound -- max_classes is a hard ceiling.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return np.zeros(0, dtype=int), 0, 0.0

    order = np.argsort(values, kind="mergesort")
    sorted_vals = values[order]

    n_distinct = len(np.unique(sorted_vals))
    max_k = max(1, min(max_classes, n_distinct))

    if max_k == 1 or n == 1:
        labels = np.zeros(n, dtype=int)
        return labels, 1, 0.0

    value_range = float(sorted_vals[-1] - sorted_vals[0])
    spread_cap = value_range * max_spread_fraction

    mat1, mat2 = _jenks_fit(sorted_vals, max_k)

    labels_sorted = None
    widest = 0.0
    chosen_k = max_k
    for k in range(1, max_k + 1):
        labels_sorted = _labels_for_k(mat1, n, k)
        widest = _widest_class_spread(sorted_vals, labels_sorted)
        if widest <= spread_cap:
            chosen_k = k
            break
    else:
        chosen_k = max_k  # for-loop's else fires only if we never broke out

    labels = np.empty(n, dtype=int)
    labels[order] = labels_sorted
    return labels, chosen_k, widest
