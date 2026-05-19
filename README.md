# Code Complexity in Modern Mobile UI Frameworks

This repository contains all analysis code for the master's thesis _Quantitative Analysis of Code Complexity in Mobile Framework Migration: from Imperative to Declarative User Interface_, which compares code complexity between:

- **Android**: Jetpack Compose vs. traditional Views
- **iOS**: SwiftUI vs. UIKit

The study collects a range of complexity metrics — cyclomatic complexity, cognitive complexity, Halstead measures, and SonarQube static analysis — across real open-source mobile applications, then compares results between framework pairs.

---

## Repository structure

```
mex/
├── scripts/          # Main analysis and plotting scripts
│   ├── analyze.py               # Orchestrates all analyzers for one or more repos
│   ├── repo_mining.py           # Discovers and clones repos via GitHub API
│   ├── halstead.py              # Halstead complexity metrics (Swift & Kotlin)
│   ├── maintainability_index.py # Maintainability index calculation (Microsoft definition)
│   ├── sonar_utils.py           # SonarQube/SonarCloud helpers
│   ├── plot_summary_table.py    # Generates repo summary table image
│   ├── fibonacci.kt             # Sample file for Halstead testing
│   ├── fibonacci.swift          # Sample file for Halstead testing
│   ├── results_table.ipynb      # Android results notebook
│   ├── results_table_ios.ipynb  # iOS results notebook
│   └── spearman_heatmap.ipynb   # Correlation analysis notebook
├── ast/              # AST-based state and complexity analyzers
│   ├── swift_analyzer.py     # Swift AST analyzer
│   └── kotlin_analyzer.py    # Kotlin AST analyzer
├── test/             # Minimal test apps used for tool validation
│   ├── UIKit_app/
│   ├── compose_app/
│   ├── views_app/
│   └── small_app/
├── results/          # JSON and CSV output from analysis runs
│   ├── metrics_table.csv        # Aggregated Android metrics (from results_table.ipynb)
│   └── metrics_table_ios.csv    # Aggregated iOS metrics (from results_table_ios.ipynb)
├── repo_data.csv                # Android UI-file metadata (from repo_mining.py)
├── repo_data_ios.csv            # iOS UI-file metadata
├── repo_summary.csv             # Android repo summary table
├── repo_summary_ios.csv         # iOS repo summary table
├── repo_summary_table_android.png  # Generated Android repo summary image
└── repo_summary_table_ios.png      # Generated iOS repo summary image
```

---

## Prerequisites

| Tool                                                                                                            | Purpose                              |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Python 3.10+                                                                                                    | All analysis scripts                 |
| [lizard](https://github.com/terryyin/lizard)                                                                    | Cyclomatic/cognitive complexity      |
| [SonarQube](https://www.sonarsource.com/products/sonarqube/) (Docker)                                           | Static analysis                      |
| [sonar-scanner](https://docs.sonarsource.com/sonarqube/latest/analyzing-source-code/scanners/sonarscanner/) CLI | Running SonarQube scans              |
| [SwiftComplexityCLI](https://github.com/fummicc1/swift-complexity)                                              | Per-function Swift complexity        |
| GitHub personal access token                                                                                    | `repo_mining.py` — GitHub API access |

Install Python dependencies:

```bash
pip install lizard requests pandas matplotlib scipy
```

### Environment variables

Create a `.env` file in the repository root (it is git-ignored):

```
GITHUB_TOKEN=your_personal_access_token
SONAR_TOKEN=your_sonarcloud_or_sonarqube_token   # if using SonarCloud
```

---

## Running the tools

### 1. Start SonarQube (Docker)

Required before running `analyze.py` locally.

```bash
docker run -d --name sonarqube \
  -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true \
  -p 9000:9000 sonarqube:community
```

SonarQube will be available at `http://localhost:9000`. Default credentials: `admin` / `admin`.

### 2. Run all analyzers on one or more repos

`analyze.py` orchestrates Halstead metrics, SonarQube, and SwiftComplexityCLI for each project.

```bash
# Analyze all projects in test/
python3 scripts/analyze.py

# Analyze all sub-folders in a given directory
python3 scripts/analyze.py path/to/folder

# Analyze a single repository
python3 scripts/analyze.py --single repos/nowinandroid

# Use local SonarQube (localhost:9000) instead of SonarCloud
python3 scripts/analyze.py --local --single repos/nowinandroid

# Restrict analysis to UI files only (requires repo_data.csv from repo_mining.py)
python3 scripts/analyze.py --single repos/nowinandroid \
    --ui-csv repo_data.csv --repo-label android/nowinandroid

# UI files, dominant framework only
python3 scripts/analyze.py --single repos/apps-android-wikipedia \
    --ui-csv repo_data.csv --repo-label wikimedia/apps-android-wikipedia \
    --dominant-only

# iOS — all files, local SonarQube
python3 scripts/analyze.py ../repositories/iOS --local \
    --ui-csv repo_data_ios.csv
```

Results are written to `results/<app_name>.json`.

### 3. Mine repository metadata from GitHub

`repo_mining.py` discovers UI files in each repo and writes `repo_data.csv` / `repo_data_ios.csv`. The list of repos is defined at the top of the script.

```bash
# Android repos
python3 scripts/repo_mining.py

# iOS repos
python3 scripts/repo_mining.py --platform ios

# Update a single repo entry
python3 scripts/repo_mining.py --update "Stypox/dicio-android@1075d6966930c299ab6095825a2adbb3c1eeed8e"
python3 scripts/repo_mining.py --platform ios --update "kickstarter/ios-oss"
```

### 4. Generate the repo summary table image

```bash
python3 scripts/plot_summary_table.py
```

Outputs `repo_summary_table_android.png` and `repo_summary_table_ios.png`.

### 5. Run SwiftComplexityCLI

From within the `swift-complexity` folder:

```bash
./.build/arm64-apple-macosx/release/SwiftComplexityCLI \
    ~/path/to/repos/swiftreponame --recursive
```

### 6. Run Halstead metrics on a single file

```bash
python3 scripts/halstead.py scripts/fibonacci.kt
python3 scripts/halstead.py scripts/fibonacci.swift
```

### 7. Run the AST state analyzer

```bash
python3 ast/swift_analyzer.py ast/swift_example.swift
```

### 8. Analyze results (notebooks)

Open and run the Jupyter notebooks in `scripts/`:

- `results_table.ipynb` — Android aggregate metrics table
- `results_table_ios.ipynb` — iOS aggregate metrics table
- `spearman_heatmap.ipynb` — Spearman correlation heatmaps across metrics

### 9. Run a SonarQube scan manually on a repo

Add a `sonar-project.properties` file to the repo root, then run:

```bash
sonar-scanner
```

from the repo directory.

---

## Results

Pre-computed results for all studied repositories are stored in `results/` as JSON files, one per repo. Aggregate CSV tables are at the root: `repo_summary.csv` (Android) and `repo_summary_ios.csv` (iOS).
