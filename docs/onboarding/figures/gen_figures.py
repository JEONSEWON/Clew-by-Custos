"""Generate onboarding figures (fig1-fig4). Run from project root."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent
MONO = "DejaVu Sans Mono"
plt.rcParams.update({
    "font.family": MONO,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "figure.dpi": 150,
})

# ---------------------------------------------------------------------------
# fig1 — Cascade 2-stage concept diagram
# ---------------------------------------------------------------------------
def make_fig1():
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    def box(x, y, w, h, label, sublabel="", style="solid"):
        lw = 1.5 if style == "solid" else 1.0
        ls = "-" if style == "solid" else "--"
        rect = mpatches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.1",
            linewidth=lw, linestyle=ls,
            edgecolor="black", facecolor="white"
        )
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2 + (0.25 if sublabel else 0),
                label, ha="center", va="center", fontsize=10, fontweight="bold")
        if sublabel:
            ax.text(x + w / 2, y + h / 2 - 0.35,
                    sublabel, ha="center", va="center", fontsize=8)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="->", color="black", lw=1.5))

    # Input
    box(3.5, 8.5, 3, 0.9, "Input: Trace (OTel JSON)")
    arrow(5, 8.5, 5, 7.65)

    # Stage 1
    ax.text(5, 7.5, "STAGE 1 — Structural", ha="center", va="center",
            fontsize=9, fontstyle="italic")
    ax.add_patch(mpatches.FancyBboxPatch(
        (1.2, 5.8), 7.6, 1.5,
        boxstyle="round,pad=0.1", linewidth=1.5,
        edgecolor="black", facecolor="0.93"
    ))
    ax.text(5, 6.85, "find_candidates(N=2)", ha="center", va="center",
            fontsize=9, fontweight="bold")
    ax.text(2.2, 6.35, "repeat_node\n(same agent >= N calls)", ha="center",
            va="center", fontsize=8)
    ax.text(5, 6.35, "pingpong_aba\n(A->B->A->B alternation)", ha="center",
            va="center", fontsize=8)
    ax.text(7.8, 6.35, "requery_known\n(tool: identical input gate)", ha="center",
            va="center", fontsize=8)
    arrow(5, 5.8, 5, 5.1)
    ax.text(5.2, 5.45, "candidates", ha="left", va="center", fontsize=8)

    # Stage 2
    ax.text(5, 5.0, "STAGE 2 — Semantic", ha="center", va="center",
            fontsize=9, fontstyle="italic")
    box(2.5, 3.8, 5, 1.0,
        "is_semantic_duplicate(phi=0.514345)",
        "cosine(embed(origin), embed(candidate)) >= phi")
    arrow(5, 3.8, 5, 3.05)

    # Split: waste / not waste
    ax.text(5.2, 3.4, "cosine >= phi", ha="left", va="center", fontsize=8)
    ax.annotate("", xy=(3.0, 2.5), xytext=(5, 3.05),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.2))
    ax.text(2.5, 3.4, "cosine < phi", ha="right", va="center", fontsize=8)

    box(0.3, 1.5, 2.8, 0.85, "Waste span", "-> sum tokens & cost")
    box(6.2, 1.5, 3.5, 0.85, "Not waste", "-> discard candidate")

    # Output
    box(3.5, 0.2, 3, 0.9, "CascadeResult")
    arrow(1.7, 1.5, 3.8, 1.1)
    arrow(7.8, 1.5, 6.2, 1.1)

    ax.set_title("Fig 1 — Cascade Detector: 2-Stage Architecture", pad=10)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_cascade_stages.png", bbox_inches="tight")
    plt.close(fig)
    print("fig1 saved")


# ---------------------------------------------------------------------------
# fig2 — Confusion matrix (TP=30, FP=0, TN=40, FN=10)
# Source: validation/EVAL_RUNS.md (seed=42, 2026-06-11)
# ---------------------------------------------------------------------------
def make_fig2():
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.axis("off")

    cells = [
        # (col, row, label, count, rate, shade)
        (0, 1, "TP", 30, "30/40\n(75.0%)", "0.75"),
        (1, 1, "FN", 10, "10/40\n(25.0%)", "0.92"),
        (0, 0, "FP", 0,  " 0/40\n( 0.0%)", "0.92"),
        (1, 0, "TN", 40, "40/40\n(100.0%)", "0.75"),
    ]

    for col, row, label, count, rate, shade in cells:
        shade_f = float(shade)
        rect = plt.Rectangle((col, row), 1, 1,
                              facecolor=str(shade_f), edgecolor="black", lw=1.5)
        ax.add_patch(rect)
        ax.text(col + 0.5, row + 0.65, label,
                ha="center", va="center", fontsize=16, fontweight="bold")
        ax.text(col + 0.5, row + 0.3, rate,
                ha="center", va="center", fontsize=10)

    # Axis labels
    ax.text(1.0, 2.12, "Predicted", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(0.5, 2.06, "Positive", ha="center", va="bottom", fontsize=10)
    ax.text(1.5, 2.06, "Negative", ha="center", va="bottom", fontsize=10)
    ax.text(-0.14, 1.0, "Actual", ha="center", va="center",
            fontsize=11, fontweight="bold", rotation=90)
    ax.text(-0.07, 1.5, "Pos", ha="center", va="center", fontsize=10, rotation=90)
    ax.text(-0.07, 0.5, "Neg", ha="center", va="center", fontsize=10, rotation=90)

    # Metrics below
    ax.text(1.0, -0.15,
            "F1 = 0.8571   FPR = 0.0000   (source: validation/EVAL_RUNS.md, seed=42, 2026-06-11)",
            ha="center", va="top", fontsize=7.5)
    ax.text(1.0, -0.32,
            "FN=10: all regen_handoff (v1 out-of-scope, still counted in F1)",
            ha="center", va="top", fontsize=7.5, fontstyle="italic")

    ax.set_title("Fig 2 — Stage 2 Confusion Matrix (Eval Set, N=80 traces)", pad=14)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_confusion_matrix.png", bbox_inches="tight")
    plt.close(fig)
    print("fig2 saved")


# ---------------------------------------------------------------------------
# fig3 — Per-pattern detection rate
# Source: validation/EVAL_RUNS.md (derived: TP per pattern, FN=10 regen_handoff)
# ---------------------------------------------------------------------------
def make_fig3():
    patterns = ["repeat_node", "pingpong_aba", "requery_known", "regen_handoff"]
    rates    = [1.00,          1.00,           1.00,            0.00]
    oos      = [False,         False,          False,           True]   # out-of-scope flag

    fig, ax = plt.subplots(figsize=(7, 3.8))
    y = np.arange(len(patterns))

    bars = ax.barh(y, rates, height=0.55, color="white", edgecolor="black", linewidth=1.5)
    for bar, is_oos in zip(bars, oos):
        if is_oos:
            bar.set_hatch("////")
            bar.set_edgecolor("black")

    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.25, 0.50, 0.75, 1.00])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_yticks(y)
    ax.set_yticklabels(patterns)
    ax.set_xlabel("True Positive Rate (Recall)")
    ax.set_title("Fig 3 — Per-Pattern Detection Rate (v1 Eval, N=80 traces)")

    for i, (rate, is_oos) in enumerate(zip(rates, oos)):
        label = f"{rate:.0%}"
        if is_oos:
            label += "  [v1 out-of-scope]"
        ax.text(rate + 0.02, i, label, va="center", fontsize=9,
                fontstyle="italic" if is_oos else "normal")

    ax.text(0.01, -0.7,
            "Source: validation/EVAL_RUNS.md  |  10 pairs per pattern  |  regen_handoff: structural candidates=0",
            fontsize=7.5, transform=ax.transData, va="top", fontstyle="italic")

    fig.tight_layout()
    fig.savefig(OUT / "fig3_pattern_recall.png", bbox_inches="tight")
    plt.close(fig)
    print("fig3 saved")


# ---------------------------------------------------------------------------
# fig4 — Cosine distribution: synthetic calibration vs real-probe observations
# Synthetic source: validation/CALIBRATION_LOG.md (P10/median/P90, seed=7)
# Real-probe source: field_test/REAL_PROBE_LOG.md (all non-waste span pairs)
# ---------------------------------------------------------------------------
def make_fig4():
    # --- Synthetic calibration percentiles (validation/CALIBRATION_LOG.md) ---
    # dup (duplicate): count=50
    dup_p10, dup_med, dup_p90 = 0.624768, 0.833652, 1.0
    # prog (progress/non-waste): count=40
    prog_p10, prog_med, prog_p90 = 0.338028, 0.362569, 0.403921

    # --- Real probe non-waste cosine pairs (field_test/REAL_PROBE_LOG.md) ---
    real_cosines = np.array([
        # clean (N=6)
        0.8259, 0.6497, 0.6497, 0.7350, 0.7350, 1.0000,
        # repeat_node (N=6)
        0.8643, 0.7129, 1.0000, 0.7408, 0.8643, 0.7129,
        # requery_known (N=10)
        1.0000, 0.8722, 0.6320, 0.6320, 0.8722, 0.6320, 0.6320, 0.6957, 0.6957, 1.0000,
        # requery_clean (N=15)
        0.9606, 0.9606, 0.8100, 0.5899, 0.5899, 1.0000,
        0.8643, 0.6238, 0.6238, 0.8643, 0.6238, 0.6238, 0.6810, 0.6810, 1.0000,
        # pingpong (N=3)
        0.6592, 0.6986, 0.9470,
    ])
    # N = 40 total real-probe non-waste pairs

    PHI = 0.514345

    fig, ax = plt.subplots(figsize=(8.5, 4.5))

    # --- Row y-positions (strip chart style) ---
    Y_DUP  = 2.5
    Y_PROG = 1.5
    Y_REAL = 0.5

    # Synthetic dup: P10-P90 range bar + median tick
    ax.hlines(Y_DUP, dup_p10, dup_p90, linewidth=6, color="0.3", label="Synthetic: duplicate (dup, N=50)")
    ax.plot(dup_med, Y_DUP, marker="|", color="white", markersize=12, markeredgewidth=2.5)
    ax.plot(dup_p10, Y_DUP, marker="|", color="0.3", markersize=10, markeredgewidth=1.5)
    ax.plot(dup_p90, Y_DUP, marker="|", color="0.3", markersize=10, markeredgewidth=1.5)

    # Synthetic prog: P10-P90 range bar + median tick
    ax.hlines(Y_PROG, prog_p10, prog_p90, linewidth=6, color="0.6",
              linestyle="--", label="Synthetic: progress (prog, N=40)")
    ax.plot(prog_med, Y_PROG, marker="|", color="white", markersize=12, markeredgewidth=2.5)
    ax.plot(prog_p10, Y_PROG, marker="|", color="0.6", markersize=10, markeredgewidth=1.5)
    ax.plot(prog_p90, Y_PROG, marker="|", color="0.6", markersize=10, markeredgewidth=1.5)

    # Real probe: individual jitter scatter
    rng = np.random.default_rng(42)
    jitter = rng.uniform(-0.12, 0.12, size=len(real_cosines))
    ax.scatter(real_cosines, Y_REAL + jitter,
               marker="x", color="black", s=40, linewidths=1.2, zorder=5,
               label=f"Real probe: non-waste pairs (N={len(real_cosines)})")

    # phi vertical line
    ax.axvline(PHI, color="black", linestyle=":", linewidth=1.8, zorder=6)
    ax.text(PHI + 0.012, 3.05, f"phi = {PHI}", fontsize=8.5, va="center")

    # Axis styling
    ax.set_xlim(0.25, 1.08)
    ax.set_ylim(0, 3.3)
    ax.set_yticks([Y_REAL, Y_PROG, Y_DUP])
    ax.set_yticklabels([
        f"Real probe\nnon-waste (N={len(real_cosines)})",
        "Synthetic\nprog (N=40)",
        "Synthetic\ndup (N=50)",
    ], fontsize=8.5)
    ax.set_xlabel("Cosine Similarity")
    ax.set_title(
        "Fig 4 — Cosine Distribution: Synthetic Calibration vs Real-Probe Observations\n"
        "(Synthetic: P10-P90 range, median=white tick | Real: individual pairs | E3 finding: phi-transfer gap)"
    )

    # Annotation: P10/median/P90 labels for synthetic
    ax.annotate("P10", xy=(dup_p10, Y_DUP + 0.18), ha="center", fontsize=7)
    ax.annotate("med", xy=(dup_med, Y_DUP + 0.18), ha="center", fontsize=7)
    ax.annotate("P90", xy=(dup_p90, Y_DUP + 0.18), ha="center", fontsize=7)
    ax.annotate("P10", xy=(prog_p10, Y_PROG + 0.18), ha="center", fontsize=7)
    ax.annotate("med", xy=(prog_med, Y_PROG + 0.18), ha="center", fontsize=7)
    ax.annotate("P90", xy=(prog_p90, Y_PROG + 0.18), ha="center", fontsize=7)

    # Sources footnote
    ax.text(0.25, -0.45,
            "Synthetic source: validation/CALIBRATION_LOG.md (dev set seed=7)  |"
            "  Real-probe source: field_test/REAL_PROBE_LOG.md",
            fontsize=7, transform=ax.transData, va="top", fontstyle="italic")

    fig.tight_layout()
    fig.savefig(OUT / "fig4_cosine_distribution.png", bbox_inches="tight")
    plt.close(fig)
    print("fig4 saved")


if __name__ == "__main__":
    make_fig1()
    make_fig2()
    make_fig3()
    make_fig4()
    print("All figures saved to", OUT)
