#!/usr/bin/env python3
"""
Analyze complexity metrics for projects in a target folder.

Runs per project:
  - Halstead metrics (all .swift / .kt files)
  - SonarQube (bugs, smells, complexity, cognitive complexity, …)
  - SwiftComplexityCLI (cyclomatic + cognitive per function, Swift only)

Results are written to results/<app_name>.json

Usage:
    python3 scripts/analyze.py                               # analyzes all projects in test/
    python3 scripts/analyze.py path/to/folder                # analyzes all projects in given folder
    python3 scripts/analyze.py --single path/to/repo         # analyzes a single project directly
    python3 scripts/analyze.py --local --single path/to/repo # use local SonarQube on localhost:9000

UI-file filtering (uses output from repo_mining.py):
    python3 scripts/analyze.py --single path/to/repo \\
        --ui-csv repo_data.csv --repo-label owner/repo[@ref]
    Add --dominant-only to further restrict to files belonging to the dominant
    framework only (e.g. if a repo is 75% Compose / 25% Views, only the Compose
    files are analysed).

Note: SonarQube project-level metrics (ncloc, complexity, …) are always
computed over the full project because SonarQube cannot be restricted to a
subset of files at scan time. Per-file SonarQube data is filtered normally.
"""
import contextlib
import csv
import io
import json
import math
import os
import re
import subprocess
import sys

# Allow importing sibling scripts and ast analyzers
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
AST_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "ast")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, AST_DIR)
from halstead import analyze_file as halstead_analyze_file
from sonar_utils import analyze_with_sonar
from maintainability_index import calculate_maintainability_index

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWIFT_CLI = os.path.normpath(os.path.join(
    REPO_ROOT, "..", "swift-complexity",
    ".build", "arm64-apple-macosx", "release", "SwiftComplexityCLI",
))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
SONAR_ORG = "complexity-metrics"

# Maps local folder name → CSV repo label (from repo_mining.py output).
# Used in batch mode so --repo-label doesn't need to be supplied per project.
FOLDER_TO_LABEL: dict[str, str] = {
    # Android
    "Gallery":                      "IacobIonut01/Gallery",
    "Simple-Gallery":               "SimpleMobileTools/Simple-Gallery",
    "Simple-Music-Player":          "SimpleMobileTools/Simple-Music-Player",
    "apps-android-wikipedia":       "wikimedia/apps-android-wikipedia",
    "nowinandroid":                 "android/nowinandroid",
    "Jetcaster":                    ("android/compose-samples", "Jetcaster/"),  # subfolder of compose-samples
    "sunflower":                    "android/sunflower",
    "sunflower_views":              "android/sunflower@views",
    "architecture-samples-compose": "android/architecture-samples",
    "architecture-samples-views":   "android/architecture-samples@views",
    "Pokedex":                      "skydoves/pokedex",
    "pokedex-compose":              "skydoves/pokedex-compose",
    "dicio-android":                "Stypox/dicio-android",
    "dicio-android-views":          "Stypox/dicio-android@1075d6966930c299ab6095825a2adbb3c1eeed8e",
    "showly":                       "trakt/showly",
    "tivi":                         "chrisbanes/tivi",
    # iOS
    "fearless-iOS":     "soramitsu/fearless-iOS",
    "gem-ios":          "gemwalletcom/gem-ios",
    "OnionBrowser":     "OnionBrowser/OnionBrowser",
    "ACHNBrowserUI":    "Dimillian/ACHNBrowserUI",
    "youtube-iOS":      "aslanyanhaik/youtube-iOS",
    "MovieSwiftUI":     "Dimillian/MovieSwiftUI",
    "Expense-Tracker-App": "abdorizak/Expense-Tracker-App",
    "DimeApp":          "rafsoh/DimeApp",
    "Chess":            "nicklockwood/Chess",
    "chess_swiftui":    "jaredcassoutt/chess_swiftui",
    "Tuist-Pokedex":    "ronanociosoig/Tuist-Pokedex",
    "PokedexUI":        "brillcp/PokedexUI",
    "LyricsX":          "ddddxxx/LyricsX",
    "LyricFever":       "aviwad/LyricFever",
}

# Directories to skip when walking source trees
SKIP_DIRS = {
    ".build", ".gradle", "build", "DerivedData", "Pods",
    "__pycache__", ".git", "xcuserdata", ".swiftpm",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_env() -> dict:
    env_path = os.path.join(REPO_ROOT, ".env")
    env: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip()
    return env


def find_files(root: str, extensions: tuple) -> list[str]:
    """Walk root, skipping build/hidden dirs, returning files with given extensions."""
    results = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            if f.endswith(extensions):
                results.append(os.path.join(dirpath, f))
    return sorted(results)


# ---------------------------------------------------------------------------
# UI-file filter (from repo_mining.py output)
# ---------------------------------------------------------------------------
def load_ui_file_filter(csv_path: str, repo_label: str, dominant_only: bool,
                        strip_prefix: str = "") -> set[str]:
    """
    Read a repo_data CSV produced by repo_mining.py and return the set of
    relative file paths that should be analysed.

    csv_path      – path to repo_data.csv or repo_data_ios.csv
    repo_label    – the 'repo' value in the CSV, e.g. 'android/nowinandroid'
                    or 'Stypox/dicio-android@1075d6...'
    dominant_only – if True, keep only files whose 'framework' matches the
                    dominant framework. Mixed files whose name contains the
                    dominant framework are also kept (e.g. a file classified as
                    'Mixed (Compose + Android Views)' is kept when dominant is
                    'Jetpack Compose').
    strip_prefix  – if set, strip this prefix from CSV file paths before
                    returning them. Used when the project is a subfolder of the
                    mined repo (e.g. Jetcaster inside compose-samples).
    """
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["repo"] == repo_label:
                rows.append(row)

    if not rows:
        raise ValueError(
            f"No rows found for repo label '{repo_label}' in {csv_path}.\n"
            "Make sure the label exactly matches the 'repo' column "
            "(e.g. 'android/nowinandroid' or 'owner/repo@commitish')."
        )

    # Strip subfolder prefix from paths (e.g. "Jetcaster/" for compose-samples)
    if strip_prefix:
        rows = [r for r in rows if r["file_path"].startswith(strip_prefix)]
        for r in rows:
            r = r.copy()  # don't mutate original
        rows = [{**r, "file_path": r["file_path"][len(strip_prefix):]} for r in rows]

    if dominant_only:
        counts: dict[str, int] = {}
        for row in rows:
            fw = row["framework"]
            if "Mixed" not in fw:  # count only pure-framework files for dominance
                counts[fw] = counts.get(fw, 0) + 1
        dominant_fw = max(counts, key=counts.get)
        # Keep dominant-framework files AND mixed files that mention any word
        # from the dominant framework name (e.g. "Compose" from "Jetpack Compose")
        dominant_words = set(dominant_fw.split())
        rows = [r for r in rows
                if r["framework"] == dominant_fw
                or (r["framework"].startswith("Mixed")
                    and any(w in r["framework"] for w in dominant_words))]
        print(f"  [ui-filter] dominant framework: '{dominant_fw}' "
              f"({len(rows)} files kept, including mixed)")
    else:
        print(f"  [ui-filter] {len(rows)} UI files loaded from {csv_path}")

    return {row["file_path"] for row in rows}


# ---------------------------------------------------------------------------
# Project detection
# ---------------------------------------------------------------------------
def detect_project(project_path: str) -> tuple[str, str, str]:
    """
    Detect (language, framework, app_name) from a project folder.

    iOS:     language=swift,  framework=swiftui|uikit
    Android: language=kotlin, framework=compose|views
    """
    entries = os.listdir(project_path)

    # iOS: look for .xcodeproj
    xcodeprojs = [e for e in entries if e.endswith(".xcodeproj")]
    if xcodeprojs:
        app_name = xcodeprojs[0].removesuffix(".xcodeproj")
        swift_files = find_files(project_path, (".swift",))
        for sf in swift_files:
            try:
                with open(sf, encoding="utf-8", errors="ignore") as f:
                    if "import SwiftUI" in f.read():
                        return "swift", "swiftui", app_name
            except OSError:
                pass
        return "swift", "uikit", app_name

    # Android: look for build.gradle / build.gradle.kts anywhere inside
    # Always use the folder name as app_name — applicationId extraction produced
    # confusing names like "main" or "niacatalog" for architecture-samples and nowinandroid.
    app_name = os.path.basename(project_path)
    gradle_files = find_files(project_path, ("build.gradle.kts", "build.gradle"))
    if gradle_files:
        kotlin_files = find_files(project_path, (".kt",))
        for kf in kotlin_files:
            try:
                with open(kf, encoding="utf-8", errors="ignore") as f:
                    if "@Composable" in f.read():
                        return "kotlin", "compose", app_name
            except OSError:
                pass
        return "kotlin", "views", app_name

    return "unknown", "unknown", app_name


# ---------------------------------------------------------------------------
# Halstead
# ---------------------------------------------------------------------------
def run_halstead(project_path: str, language: str, allowed_files: set | None = None) -> dict:
    """
    Run Halstead analysis on every source file in project_path.
    Returns {relative_path: metrics_dict}.
    If allowed_files is given, only files whose repo-relative path is in that
    set are analysed (used for UI-only mode).
    """
    ext = (".swift",) if language == "swift" else (".kt",)
    files = find_files(project_path, ext)
    if allowed_files is not None:
        files = [f for f in files if os.path.relpath(f, project_path) in allowed_files]
    results: dict[str, dict] = {}

    for filepath in files:
        rel = os.path.relpath(filepath, project_path)
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                loc = sum(1 for line in f if line.strip())
            # halstead.py prints debug output; suppress it
            with contextlib.redirect_stdout(io.StringIO()):
                metrics = halstead_analyze_file(filepath)
            results[rel] = {
                "loc":                 loc,
                "n1_unique_operators": metrics.n1,
                "n2_unique_operands":  metrics.n2,
                "N1_total_operators":  metrics.N1,
                "N2_total_operands":   metrics.N2,
                "vocabulary":          metrics.n,
                "length":              metrics.N,
                "calculated_length":   round(metrics.N_hat, 2),
                "volume":              round(metrics.V, 2),
                "difficulty":          round(metrics.D, 2),
                "effort":              round(metrics.E, 2),
                "time_seconds":        round(metrics.T, 2),
                "bugs_delivered":      round(metrics.B, 3),
            }
        except Exception as e:
            print(f"    [halstead] Error on {rel}: {e}")

    return results


# ---------------------------------------------------------------------------
# Swift complexity
# ---------------------------------------------------------------------------
def run_swift_complexity(project_path: str, allowed_files: set | None = None) -> dict:
    """
    Run SwiftComplexityCLI --recursive on project_path.
    Returns {relative_path: {functions, avg_cyclomatic, avg_cognitive}}.
    If allowed_files is given, only entries whose path is in that set are kept.
    """
    if not os.path.isfile(SWIFT_CLI):
        print(f"    [swift-complexity] CLI not found at {SWIFT_CLI}")
        return {}

    result = subprocess.run(
        [SWIFT_CLI, project_path, "--recursive"],
        capture_output=True,
        text=True,
    )
    parsed = _parse_swift_complexity(result.stdout, project_path)
    if allowed_files is not None:
        parsed = {rel: v for rel, v in parsed.items() if rel in allowed_files}
    return parsed


def _parse_swift_complexity(output: str, project_root: str) -> dict:
    results: dict[str, dict] = {}
    current_file: str | None = None
    functions: list[dict] = []

    for line in output.splitlines():
        if line.startswith("File: "):
            if current_file is not None:
                results[current_file] = _summarize_functions(functions)
            current_file = os.path.relpath(line.removeprefix("File: ").strip(), project_root)
            functions = []
        elif line.startswith("|") and "Function" not in line and "---" not in line:
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) == 3:
                name, cyc, cog = parts
                try:
                    functions.append({
                        "function":   name,
                        "cyclomatic": int(cyc),
                        "cognitive":  int(cog),
                    })
                except ValueError:
                    pass

    if current_file is not None:
        results[current_file] = _summarize_functions(functions)

    return results


def _summarize_functions(functions: list[dict]) -> dict:
    if not functions:
        return {"functions": [], "avg_cyclomatic": 0.0, "avg_cognitive": 0.0}
    avg_cyc = sum(f["cyclomatic"] for f in functions) / len(functions)
    avg_cog = sum(f["cognitive"]  for f in functions) / len(functions)
    return {
        "functions":      functions,
        "avg_cyclomatic": round(avg_cyc, 2),
        "avg_cognitive":  round(avg_cog, 2),
    }


# ---------------------------------------------------------------------------
# State metrics (AST analyzers)
# ---------------------------------------------------------------------------
def run_state_metrics(project_path: str, language: str, allowed_files: set | None = None) -> dict:
    """
    Run swift_analyzer or kotlin_analyzer on every source file.
    Returns {relative_path: state_metrics_dict}.
    If allowed_files is given, only files whose repo-relative path is in that
    set are analysed.
    """
    if language == "swift":
        from swift_analyzer import analyze_file as state_analyze_file
        ext = (".swift",)
    else:
        from kotlin_analyzer import analyze_file as state_analyze_file
        ext = (".kt",)

    files = find_files(project_path, ext)
    if allowed_files is not None:
        files = [f for f in files if os.path.relpath(f, project_path) in allowed_files]
    results: dict[str, dict] = {}

    for filepath in files:
        rel = os.path.relpath(filepath, project_path)
        try:
            m = state_analyze_file(filepath)
            results[rel] = {
                "mutable_vars":          m.mutable_vars,
                "immutable_vars":        m.immutable_vars,
                "observable_state_vars": m.observable_state_vars,
                "state_updates":         m.state_updates,
            }
        except Exception as e:
            print(f"    [state] Error on {rel}: {e}")

    return results


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------
def compute_derived_metrics(result: dict) -> dict:
    """
    Adds a 'derived' section with per-file:
      - mutable_variable_ratio  (mutable / total vars, null if no vars)
      - maintainability_index   (MI per Microsoft formula; null if inputs missing)

    Cyclomatic complexity source:
      Swift  → SwiftComplexityCLI (sum of per-function values)
      Kotlin → SonarQube per-file 'complexity' metric
    """
    language = result["language"]
    halstead = result.get("halstead", {})
    state = result.get("state_metrics", {})
    sonar_files = result.get("sonarqube", {}).get("files", {})

    # Build per-file cyclomatic lookup
    cyc_per_file: dict[str, int] = {}
    if language == "swift":
        for rel, fd in result.get("swift_complexity", {}).items():
            cyc_per_file[rel] = sum(f["cyclomatic"] for f in fd.get("functions", []))
    else:
        # Kotlin: use SonarQube per-file complexity.
        # SonarQube paths are relative to the project root, same as our keys.
        for sonar_path, measures in sonar_files.items():
            cyc = measures.get("complexity")
            if cyc is not None:
                cyc_per_file[sonar_path] = int(cyc)

    derived: dict[str, dict] = {}
    for rel in set(halstead) | set(state):
        sm = state.get(rel, {})
        mutable = sm.get("mutable_vars", 0)
        total_vars = mutable + sm.get("immutable_vars", 0)
        mvr = (mutable / total_vars) if total_vars > 0 else float("nan")

        h = halstead.get(rel, {})
        cyc = cyc_per_file.get(rel, 0)
        mi = calculate_maintainability_index(h.get("volume", 0.0), cyc, h.get("loc", 0))

        derived[rel] = {
            "mutable_variable_ratio": None if math.isnan(mvr) else round(mvr, 4),
            "maintainability_index":  None if math.isnan(mi) else round(mi, 2),
        }

    result["derived"] = derived
    return result


# ---------------------------------------------------------------------------
# Per-file merge
# ---------------------------------------------------------------------------
def merge_into_files(result: dict) -> dict:
    """
    Build a 'files' dict keyed by relative path, where every file has all its
    metrics in one place:

        "path/to/Foo.kt": {
            "halstead":        {...},
            "state_metrics":   {...},
            "derived":         {...},
            "sonarqube":       {...},   # if SonarQube reported this file
            "swift_complexity": {...},  # Swift only
        }

    The original per-metric-type dicts are removed to avoid duplication.
    Project-level SonarQube data stays under result["sonarqube_project"].

    If result["ui_files_filter"] is set (a set of allowed paths), only those
    paths are included — SonarQube per-file data is also restricted to this set.
    """
    allowed = result.get("ui_files_filter")  # set[str] | None

    sonar_file_paths = set(result.get("sonarqube", {}).get("files", {}))
    if allowed is not None:
        sonar_file_paths = sonar_file_paths & allowed

    all_paths = (
        set(result.get("halstead", {}))
        | set(result.get("state_metrics", {}))
        | set(result.get("derived", {}))
        | set(result.get("swift_complexity", {}))
        | sonar_file_paths
    )

    files: dict[str, dict] = {}
    for path in sorted(all_paths):
        entry: dict = {}
        if path in result.get("halstead", {}):
            entry["halstead"] = result["halstead"][path]
        if path in result.get("state_metrics", {}):
            entry["state_metrics"] = result["state_metrics"][path]
        if path in result.get("derived", {}):
            entry["derived"] = result["derived"][path]
        if path in result.get("swift_complexity", {}):
            entry["swift_complexity"] = result["swift_complexity"][path]
        sonar_files = result.get("sonarqube", {}).get("files", {})
        if path in sonar_files:
            entry["sonarqube"] = sonar_files[path]
        files[path] = entry

    # Promote sonar project-level summary, then drop the redundant dicts
    result["sonarqube_project"] = result.get("sonarqube", {}).get("project", {})
    result["files"] = files
    for key in ("halstead", "state_metrics", "derived", "swift_complexity", "sonarqube"):
        result.pop(key, None)

    return result


# ---------------------------------------------------------------------------
# Project analysis orchestrator
# ---------------------------------------------------------------------------
def analyze_project(
    project_path: str,
    sonar_token: str,
    local: bool = False,
    allowed_files: set | None = None,
) -> dict:
    language, framework, app_name = detect_project(project_path)
    project_key = f"thesis-{framework}-{app_name}".lower()

    print(f"\n=== {app_name}  [{framework} / {language}]  key: {project_key} ===")
    if allowed_files is not None:
        print(f"  UI-file filter active: {len(allowed_files)} allowed file(s)")

    result: dict = {
        "project":          app_name,
        "framework":        framework,
        "language":         language,
        "sonar_project_key": project_key,
        "project_path":     project_path,
        "ui_files_filter":  allowed_files,   # kept so merge_into_files can use it
        "halstead":         {},
        "sonarqube":        {},
    }

    # Halstead
    print("  Running Halstead...")
    result["halstead"] = run_halstead(project_path, language, allowed_files)
    print(f"  Halstead: {len(result['halstead'])} file(s) analysed")

    # SonarQube — always scans the full project; per-file data is filtered later
    print("  Running SonarQube...")
    result["sonarqube"] = analyze_with_sonar(
        project_path, project_key, sonar_token, SONAR_ORG, local=local
    )
    n_files = len(result["sonarqube"].get("files", {}))
    print(f"  SonarQube: project-level + {n_files} file(s) (project-level metrics cover full project)")

    # Swift complexity (Swift projects only)
    if language == "swift":
        print("  Running SwiftComplexityCLI...")
        swift_results = run_swift_complexity(project_path, allowed_files)
        result["swift_complexity"] = swift_results
        print(f"  SwiftComplexityCLI: {len(swift_results)} file(s) analysed")

    # State metrics
    print("  Running state metrics...")
    result["state_metrics"] = run_state_metrics(project_path, language, allowed_files)
    print(f"  State metrics: {len(result['state_metrics'])} file(s) analysed")

    # Derived metrics (mutable_variable_ratio, maintainability_index)
    print("  Computing derived metrics...")
    compute_derived_metrics(result)

    # Merge all per-file metrics into a single "files" dict
    merge_into_files(result)

    # Don't serialise the filter set (it's a set of strings, fine as a list)
    if result.get("ui_files_filter") is not None:
        result["ui_files_filter"] = sorted(result["ui_files_filter"])
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Analyze complexity metrics for mobile projects.")
    parser.add_argument("target", nargs="?", help="Folder of projects, or single project path with --single")
    parser.add_argument("--single", action="store_true", help="Treat target as a single project directory")
    parser.add_argument("--local", action="store_true", help="Use local SonarQube (localhost:9000)")
    parser.add_argument("--ui-csv", metavar="PATH", help="Path to repo_data.csv from repo_mining.py")
    parser.add_argument("--repo-label", metavar="OWNER/REPO[@REF]",
                        help="Repo label as it appears in the 'repo' column of --ui-csv")
    parser.add_argument("--dominant-only", action="store_true",
                        help="With --ui-csv: keep only files from the dominant framework")
    args = parser.parse_args()

    env = load_env()

    if args.local:
        sonar_token = env.get("SONAR_LOCAL_TOKEN") or os.environ.get("SONAR_LOCAL_TOKEN", "")
        if not sonar_token:
            print("ERROR: SONAR_LOCAL_TOKEN not set in .env")
            sys.exit(1)
    else:
        sonar_token = env.get("SONAR_TOKEN") or os.environ.get("SONAR_TOKEN", "")
        if not sonar_token:
            print("ERROR: SONAR_TOKEN not set in .env")
            sys.exit(1)

    # UI-file filter (optional)
    allowed_files: set | None = None
    if args.ui_csv and args.single:
        if not args.repo_label:
            print("ERROR: --ui-csv with --single requires --repo-label")
            sys.exit(1)
        allowed_files = load_ui_file_filter(args.ui_csv, args.repo_label, args.dominant_only)

    target = os.path.abspath(args.target if args.target else os.path.join(REPO_ROOT, "test"))
    if not os.path.isdir(target):
        print(f"ERROR: target folder not found: {target}")
        sys.exit(1)

    if args.single:
        project_dirs = [target]
        print(f"Analyzing single project: {target}")
    else:
        project_dirs = sorted(
            os.path.join(target, d)
            for d in os.listdir(target)
            if os.path.isdir(os.path.join(target, d)) and not d.startswith(".")
        )
        print(f"Found {len(project_dirs)} project(s) in {target}")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    for project_path in project_dirs:
        # In batch mode with --ui-csv, derive the repo label from the folder name
        project_allowed = allowed_files  # already set for --single
        if args.ui_csv and not args.single:
            folder_name = os.path.basename(project_path.rstrip("/"))
            entry = FOLDER_TO_LABEL.get(folder_name)
            if entry is None:
                print(f"  ⚠️  No CSV label for folder '{folder_name}' — skipping UI filter for this project")
                project_allowed = None
            else:
                label, strip_prefix = (entry if isinstance(entry, tuple) else (entry, ""))
                try:
                    project_allowed = load_ui_file_filter(
                        args.ui_csv, label, args.dominant_only, strip_prefix=strip_prefix)
                except ValueError as e:
                    print(f"  ⚠️  {e} — skipping UI filter for this project")
                    project_allowed = None

        result = analyze_project(project_path, sonar_token, local=args.local,
                                 allowed_files=project_allowed)
        # Use framework prefix so same-app migrations don't overwrite each other
        # e.g. sunflower → compose_sunflower.json and views_sunflower.json
        out_path = os.path.join(RESULTS_DIR, f"{result['framework']}_{result['project']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  -> {out_path}")


if __name__ == "__main__":
    main()
