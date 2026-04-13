import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timedelta

# --- Adjust reference values here ---
# A cell is GREEN if value >= threshold, RED otherwise. None = no coloring.
THRESHOLDS = {
    "stars":               100,
    "open_issues":         None,
    "forks":               100,
    "commits":             100,
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

# Columns to display
DISPLAY_COLS = [
    "repo", "stars", "forks", "open_issues",
    "commits", "contributors", "open_pull_requests",
    "total_ui_files", "compose_pct", "android_views_pct",
    "swiftui_pct", "uikit_pct", "last_push", "dominant_framework"
]

# --- Pairs for Android table ---
ANDROID_PAIRS = [
    {"repos": ["SimpleMobileTools/Simple-Gallery", "IacobIonut01/Gallery"],           "color": "#FFE4B5"},
    {"repos": ["wikimedia/apps-android-wikipedia",              "android/nowinandroid"],           "color": "#B0E0E6"},
    {"repos": ["SimpleMobileTools/Simple-Music-Player", "android/compose-samples"],   "color": "#DDA0DD"},
    {"repos": ["android/sunflower@views",           "android/sunflower"],              "color": "#ADDFAD"},
    {"repos": ["android/architecture-samples@views","android/architecture-samples"],   "color": "#F08080"},
    {"repos": ["skydoves/pokedex",                  "skydoves/pokedex-compose"],       "color": "#FAFAD2"},
    {"repos": ["Stypox/dicio-android@1075d6966930c299ab6095825a2adbb3c1eeed8e", "Stypox/dicio-android"], "color": "#E6E6FA"},
    {"repos": ["nameisjayant/News-feed-app-android-kotlin"],                           "color": "#FFDAB9"},
    {"repos": ["trakt/showly",                      "chrisbanes/tivi"],                "color": "#98FB98"},
]

# --- Pairs for iOS table ---
IOS_PAIRS = [
    {"repos": ["soramitsu/fearless-iOS",         "gemwalletcom/gem-ios"],        "color": "#FFE4B5"},
    {"repos": ["OnionBrowser/OnionBrowser",       "Dimillian/ACHNBrowserUI"],     "color": "#B0E0E6"},
    {"repos": ["aslanyanhaik/youtube-iOS",        "Dimillian/MovieSwiftUI"],      "color": "#DDA0DD"},
    {"repos": ["abdorizak/Expense-Tracker-App",  "rafsoh/DimeApp"],              "color": "#ADDFAD"},
    {"repos": ["nicklockwood/Chess",             "jaredcassoutt/chess_swiftui"],  "color": "#F08080"},
    {"repos": ["ronanociosoig/Tuist-Pokedex",    "brillcp/PokedexUI"],           "color": "#FAFAD2"},
    {"repos": ["ddddxxx/LyricsX",               "aviwad/LyricFever"],            "color": "#E6E6FA"},
]


def get_pair_color(repo_label: str, pairs: list) -> str:
    for pair in pairs:
        if any(repo_label == r or repo_label.startswith(r) or r.startswith(repo_label) for r in pair["repos"]):
            return pair["color"]
    return None


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


def build_table(df, pairs):
    # Only keep columns that exist in this CSV
    cols = [c for c in DISPLAY_COLS if c in df.columns]
    display_df = df[cols].copy()

    cell_colors = []
    for _, row in display_df.iterrows():
        pair_color = get_pair_color(str(row["repo"]), pairs)
        row_colors = []
        for col in cols:
            if col == "repo":
                row_colors.append(pair_color if pair_color else "white")
            else:
                row_colors.append(get_color(col, row[col]))
        cell_colors.append(row_colors)

    return display_df, cell_colors, cols


def plot_table(df, pairs, title, output_png):
    display_df, cell_colors, cols = build_table(df, pairs)

    fig, ax = plt.subplots(figsize=(18, max(4, len(display_df) * 0.5 + 1.5)))
    ax.axis("off")

    table = ax.table(
        cellText=display_df.values,
        colLabels=cols,
        cellColours=cell_colors,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.auto_set_column_width(col=list(range(len(cols))))

    for col_idx in range(len(cols)):
        table[0, col_idx].set_facecolor("#4472C4")
        table[0, col_idx].set_text_props(color="white", fontweight="bold")

    green_patch = mpatches.Patch(color="#90EE90", label="Above threshold")
    red_patch   = mpatches.Patch(color="#FF9999", label="Below threshold")
    ax.legend(handles=[green_patch, red_patch], loc="upper right", fontsize=8)

    plt.title(title, fontsize=12, fontweight="bold", pad=10)
    plt.tight_layout()
    plt.savefig(output_png, dpi=150, bbox_inches="tight")
    print(f"Saved: {output_png}")
    plt.show()


# --- Generate Android table ---
android_df = pd.read_csv("repo_summary.csv")
plot_table(android_df, ANDROID_PAIRS, "Android Repository Summary", "repo_summary_table_android.png")

# --- Generate iOS table ---
ios_df = pd.read_csv("repo_summary_ios.csv")
plot_table(ios_df, IOS_PAIRS, "iOS Repository Summary", "repo_summary_table_ios.png")
