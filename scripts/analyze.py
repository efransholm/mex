#!/usr/bin/env python3
"""
Analyze complexity metrics for projects in a target folder.

Runs per project:
  - Halstead metrics (all .swift / .kt files)
  - SonarQube (bugs, smells, complexity, cognitive complexity, …)
  - SwiftComplexityCLI (cyclomatic + cognitive per function, Swift only)

Results are written to results/<app_name>.json

Usage:
    python3 scripts/analyze.py                  # analyzes all projects in test/
    python3 scripts/analyze.py path/to/folder   # analyzes all projects in given folder
"""
import contextlib
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
    app_name = os.path.basename(project_path)
    gradle_files = find_files(project_path, ("build.gradle.kts", "build.gradle"))
    if gradle_files:
        for gf in gradle_files:
            try:
                with open(gf, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                m = re.search(r'applicationId\s*[=:]\s*["\']([^"\']+)["\']', content)
                if m:
                    app_name = m.group(1).split(".")[-1]
                    break
            except OSError:
                pass
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
def run_halstead(project_path: str, language: str) -> dict:
    """
    Run Halstead analysis on every source file in project_path.
    Returns {relative_path: metrics_dict}.
    """
    ext = (".swift",) if language == "swift" else (".kt",)
    files = find_files(project_path, ext)
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
def run_swift_complexity(project_path: str) -> dict:
    """
    Run SwiftComplexityCLI --recursive on project_path.
    Returns {relative_path: {functions, avg_cyclomatic, avg_cognitive}}.
    """
    if not os.path.isfile(SWIFT_CLI):
        print(f"    [swift-complexity] CLI not found at {SWIFT_CLI}")
        return {}

    result = subprocess.run(
        [SWIFT_CLI, project_path, "--recursive"],
        capture_output=True,
        text=True,
    )
    return _parse_swift_complexity(result.stdout, project_path)


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
def run_state_metrics(project_path: str, language: str) -> dict:
    """
    Run swift_analyzer or kotlin_analyzer on every source file.
    Returns {relative_path: state_metrics_dict}.
    """
    if language == "swift":
        from swift_analyzer import analyze_file as state_analyze_file
        ext = (".swift",)
    else:
        from kotlin_analyzer import analyze_file as state_analyze_file
        ext = (".kt",)

    files = find_files(project_path, ext)
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
# Project analysis orchestrator
# ---------------------------------------------------------------------------
def analyze_project(project_path: str, sonar_token: str) -> dict:
    language, framework, app_name = detect_project(project_path)
    project_key = f"thesis-{framework}-{app_name}"

    print(f"\n=== {app_name}  [{framework} / {language}]  key: {project_key} ===")

    result: dict = {
        "project":          app_name,
        "framework":        framework,
        "language":         language,
        "sonar_project_key": project_key,
        "project_path":     project_path,
        "halstead":         {},
        "sonarqube":        {},
    }

    # Halstead
    print("  Running Halstead...")
    result["halstead"] = run_halstead(project_path, language)
    print(f"  Halstead: {len(result['halstead'])} file(s) analysed")

    # SonarQube
    print("  Running SonarQube...")
    result["sonarqube"] = analyze_with_sonar(
        project_path, project_key, sonar_token, SONAR_ORG
    )
    n_files = len(result["sonarqube"].get("files", {}))
    print(f"  SonarQube: project-level + {n_files} file(s)")

    # Swift complexity (Swift projects only)
    if language == "swift":
        print("  Running SwiftComplexityCLI...")
        swift_results = run_swift_complexity(project_path)
        result["swift_complexity"] = swift_results
        print(f"  SwiftComplexityCLI: {len(swift_results)} file(s) analysed")

    # State metrics
    print("  Running state metrics...")
    result["state_metrics"] = run_state_metrics(project_path, language)
    print(f"  State metrics: {len(result['state_metrics'])} file(s) analysed")

    # Derived metrics (mutable_variable_ratio, maintainability_index)
    print("  Computing derived metrics...")
    compute_derived_metrics(result)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    env = load_env()
    sonar_token = env.get("SONAR_TOKEN") or os.environ.get("SONAR_TOKEN", "")
    if not sonar_token:
        print("ERROR: SONAR_TOKEN not set in .env")
        sys.exit(1)

    target = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "test"))
    if not os.path.isdir(target):
        print(f"ERROR: target folder not found: {target}")
        sys.exit(1)

    project_dirs = sorted(
        os.path.join(target, d)
        for d in os.listdir(target)
        if os.path.isdir(os.path.join(target, d))
    )
    print(f"Found {len(project_dirs)} project(s) in {target}")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    for project_path in project_dirs:
        result = analyze_project(project_path, sonar_token)
        out_path = os.path.join(RESULTS_DIR, f"{result['project']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  -> {out_path}")


if __name__ == "__main__":
    main()
