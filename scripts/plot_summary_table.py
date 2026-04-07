import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timedelta

# Load data
df = pd.read_csv("repo_summary.csv")

# --- Adjust reference values here ---
# For each column, set the threshold value.
# A cell is GREEN if value >= threshold, RED otherwise.
# Set to None to skip coloring for that column.
THRESHOLDS = {
    "stars":               1000,
    "open_issues":         None,   # None = no coloring
    "forks":               100,
    "commits":             500,
    "contributors":        5,
    "open_pull_requests":  None,
    "total_ui_files":      10,
    "compose_files":       None,
    "android_views_files": None,
    "swiftui_files":       None,
    "uikit_files":         None,
    "mixed_files":         None,
    "compose_pct":         75.0,
    "android_views_pct":   75.0,
    "swiftui_pct":         75.0,
    "uikit_pct":           75.0,
    "last_push":           (datetime.today() - timedelta(days=365*2)).strftime("%Y-%m-%d"),
}

# Columns to display in the table
DISPLAY_COLS = [
    "repo", "stars", "forks", "open_issues",
    "commits", "contributors", "open_pull_requests",
    "total_ui_files", "compose_pct", "android_views_pct",
    "swiftui_pct", "uikit_pct", "last_push", "dominant_framework"
]

display_df = df[DISPLAY_COLS].copy()

# Build cell colors
def get_color(col, val):
    threshold = THRESHOLDS.get(col)
    if threshold is None:
        return "white"
    if col == "last_push":
        try:
            return "#90EE90" if str(val) >= threshold else "#FF9999"
        except (ValueError, TypeError):
            return "white"
    try:
        return "#90EE90" if float(val) >= threshold else "#FF9999"
    except (ValueError, TypeError):
        return "white"

cell_colors = []
for _, row in display_df.iterrows():
    row_colors = [get_color(col, row[col]) for col in DISPLAY_COLS]
    cell_colors.append(row_colors)

# Plot
fig, ax = plt.subplots(figsize=(18, max(4, len(display_df) * 0.5 + 1.5)))
ax.axis("off")

table = ax.table(
    cellText=display_df.values,
    colLabels=DISPLAY_COLS,
    cellColours=cell_colors,
    loc="center",
    cellLoc="center",
)
table.auto_set_font_size(False)
table.set_fontsize(8)
table.auto_set_column_width(col=list(range(len(DISPLAY_COLS))))

# Style header
for col_idx in range(len(DISPLAY_COLS)):
    table[0, col_idx].set_facecolor("#4472C4")
    table[0, col_idx].set_text_props(color="white", fontweight="bold")

green_patch = mpatches.Patch(color="#90EE90", label="Above threshold")
red_patch   = mpatches.Patch(color="#FF9999", label="Below threshold")
ax.legend(handles=[green_patch, red_patch], loc="upper right", fontsize=8)

plt.title("Repository Summary", fontsize=12, fontweight="bold", pad=10)
plt.tight_layout()
plt.savefig("repo_summary_table.png", dpi=150, bbox_inches="tight")
plt.show()
