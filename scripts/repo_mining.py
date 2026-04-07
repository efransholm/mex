import os
import requests
import csv
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional
import time

# Load .env from repo root (two levels up from this script)
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN environment variable is not set.")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# can also add the repo at a specific commit/branch/tag like "owner/repo@commitish" if needed
REPOS = [
    # Photo / image gallery
    "SimpleMobileTools/Simple-Gallery",         # views
    "IacobIonut01/Gallery",                     # compose

    # Large navigation / content browsing
    "mozilla-mobile/fenix",                     # views
    "android/nowinandroid",                     # compose

    # Music / podcast player
    "SimpleMobileTools/Simple-Music-Player",    # views
    "android/compose-samples",                  # compose — Jetcaster subfolder

    # Gardening app (same repo, two versions)
    "android/sunflower@views",                  # views branch
    "android/sunflower",                        # compose (main)

    # To-do app (same repo, two versions)
    "android/architecture-samples@views",       # views branch
    "android/architecture-samples",             # compose (main)

    # Pokedex app (two separate repos)
    "skydoves/pokedex",                         # views
    "skydoves/pokedex-compose",                 # compose

    # Voice assistant (same repo, before/after migration)
    "Stypox/dicio-android@1075d6966930c299ab6095825a2adbb3c1eeed8e",  # views — last commit before Compose
    "Stypox/dicio-android",                     # compose (main)

    # News feed
    "nameisjayant/News-feed-app-android-kotlin", # views
    # compose — JetNews is a subfolder of compose-samples (already listed above)

    # TV / content tracking
    "trakt/showly",                              # views
    "chrisbanes/tivi",                          # compose
]

OUTPUT_CSV = "repo_data.csv"
OUTPUT_SUMMARY_CSV = "repo_summary.csv"

# How many files to scan per repo (set to None for unlimited — can be slow)
MAX_FILES_PER_REPO: Optional[int] = 500

REQUEST_DELAY = 0.3

KOTLIN_EXTENSIONS = {".kt", ".kts"}
STORYBOARD_EXTENSIONS = {".storyboard", ".xib"}
XML_EXTENSIONS = {".xml"}
SWIFT_EXTENSIONS = {".swift"}

# Jetpack Compose — import/usage patterns
COMPOSE_KEYWORDS = [
    "androidx.compose",
    "@Composable",
    "setContent {",
    "setContent{",
    "ComposeView",
    "rememberCoroutineScope",
    "remember {",
    "LaunchedEffect",
    "Scaffold(",
    "Column(",
    "Row(",
    "Box(",
    "LazyColumn(",
    "LazyRow(",
    "Surface(",
    "Modifier.",
    "MaterialTheme",
    "androidx.activity.compose",
]

# Android XML Views — layout file indicators
XML_VIEW_KEYWORDS = [
    "xmlns:android=",
    'android:layout_width',
    "<LinearLayout",
    "<RelativeLayout",
    "<ConstraintLayout",
    "<FrameLayout",
    "<ScrollView",
    "<RecyclerView",
    "<TextView",
    "<Button",
    "<ImageView",
    "<EditText",
    "<ViewGroup",
    "<merge",
    "<include",
    "android.widget",
    "android.view",
]

# Android Views in Kotlin — programmatic view usage (non-Compose)
KOTLIN_ANDROID_VIEW_KEYWORDS = [
    "findViewById",
    "setContentView",
    "LayoutInflater",
    "addView(",
    "removeView(",
    "android.widget.TextView",
    "android.widget.Button",
    "android.widget.ImageView",
    "android.widget.EditText",
    "android.widget.RecyclerView",
    "RecyclerView.Adapter",
    "RecyclerView.ViewHolder",
    "android.view.View",
    "android.view.ViewGroup",
    "View.OnClickListener",
    "setOnClickListener",
    "inflater.inflate",
    "ViewBinding",
    "DataBinding",
    "databinding",
    "viewBinding",
    "ActivityMainBinding",
    "FragmentBinding",
]

# SwiftUI patterns
SWIFTUI_KEYWORDS = [
    "import SwiftUI",
    "View {",
    "some View",
    "body: some View",
    "@State",
    "@Binding",
    "@ObservedObject",
    "@StateObject",
    "@EnvironmentObject",
    "NavigationView",
    "NavigationStack",
    "VStack",
    "HStack",
    "ZStack",
    "List {",
    "ForEach(",
    "ViewBuilder",
    ".padding(",
    ".frame(",
    "PreviewProvider",
]

# UIKit patterns
UIKIT_KEYWORDS = [
    "import UIKit",
    "UIViewController",
    "UIView",
    "UITableView",
    "UICollectionView",
    "UILabel",
    "UIButton",
    "UIImageView",
    "UINavigationController",
    "UITabBarController",
    "viewDidLoad()",
    "loadView()",
    "storyboard",
    "IBOutlet",
    "IBAction",
    "addSubview(",
    "layoutSubviews()",
    "UIStackView",
    "UIScrollView",
    "NSLayoutConstraint",
    "autoresizingMask",
]

STORYBOARD_KEYWORDS = [
    "<viewController",
    "<tableView",
    "<collectionView",
    "<label",
    "<button",
    "<imageView",
    "<constraints>",
    "<connections>",
    "customClass=",
    ]

# ──────────────────────────────────────────────
# DATA MODEL
# ──────────────────────────────────────────────

@dataclass
class FileResult:
    repo: str
    file_path: str
    language: str          # "Kotlin" | "XML" | "Swift"
    framework: str         # "Jetpack Compose" | "XML Views" | "SwiftUI" | "UIKit" | "Mixed" | "Unknown"
    matched_keywords: list = field(default_factory=list)
    html_url: str = ""


@dataclass
class RepoSummary:
    repo: str
    stars: Optional[int]
    open_issues: Optional[int]
    last_push: Optional[str]
    forks: Optional[int]
    commits: Optional[int]
    contributors: Optional[int]
    open_pull_requests: Optional[int]
    total_ui_files: int
    # Framework file counts
    compose_files: int = 0
    android_views_files: int = 0
    swiftui_files: int = 0
    uikit_files: int = 0
    mixed_files: int = 0
    # Percentages (of total_ui_files)
    compose_pct: float = 0.0
    android_views_pct: float = 0.0
    swiftui_pct: float = 0.0
    uikit_pct: float = 0.0
    dominant_framework: str = ""

# ──────────────────────────────────────────────
# GITHUB API CLIENT
# ──────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
})


def api_get(url: str, params: dict = None) -> Optional[dict]:
    """GET request with basic rate-limit handling."""
    while True:
        response = session.get(url, params=params)
        if response.status_code == 200:
            time.sleep(REQUEST_DELAY)
            return response.json()
        elif response.status_code == 403:
            reset_time = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
            sleep_for = max(reset_time - int(time.time()), 1) + 5
            logger.warning(f"Rate limited. Sleeping {sleep_for}s ...")
            time.sleep(sleep_for)
        elif response.status_code == 404:
            logger.warning(f"404 Not Found: {url}")
            return None
        else:
            logger.error(f"HTTP {response.status_code} for {url}: {response.text[:200]}")
            return None


def api_count(url: str, params: dict = None) -> Optional[int]:
    """Fetch only the first page (per_page=1) and extract the total count from the Link header.

    Returns the total number of items, or None on failure.
    Falls back to counting the returned list if no Link header is present (i.e. ≤1 page).
    """
    p = {"per_page": 1}
    if params:
        p.update(params)
    while True:
        response = session.get(url, params=p)
        if response.status_code == 200:
            time.sleep(REQUEST_DELAY)
            link = response.headers.get("Link", "")
            # Link header looks like: <url?page=N>; rel="last"
            import re
            match = re.search(r'[?&]page=(\d+)>; rel="last"', link)
            if match:
                return int(match.group(1))
            # No pagination — all items fit on one page
            data = response.json()
            return len(data) if isinstance(data, list) else None
        elif response.status_code == 403:
            reset_time = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
            sleep_for = max(reset_time - int(time.time()), 1) + 5
            logger.warning(f"Rate limited. Sleeping {sleep_for}s ...")
            time.sleep(sleep_for)
        elif response.status_code == 404:
            logger.warning(f"404 Not Found: {url}")
            return None
        else:
            logger.error(f"HTTP {response.status_code} for {url}: {response.text[:200]}")
            return None


def resolve_to_tree_sha(owner: str, repo: str, ref: str) -> Optional[str]:
    """Resolve a branch name, tag, or commit SHA to the corresponding git tree SHA."""
    commit_data = api_get(f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}")
    if commit_data and "commit" in commit_data:
        return commit_data["commit"]["tree"]["sha"]
    return None


def get_tree(owner: str, repo: str, ref: Optional[str] = None) -> list[dict]:
    """Retrieve the full file tree for a branch, commit SHA, or tag.

    If ref is None, falls back to the repo's default branch.
    ref can be a branch name, a full/short commit SHA, or a tag name.
    """
    if ref is None:
        repo_data = api_get(f"https://api.github.com/repos/{owner}/{repo}")
        if not repo_data:
            return []
        ref = repo_data.get("default_branch", "main")

    # The git trees API needs a tree SHA — resolve commits/branches/tags first
    tree_sha = resolve_to_tree_sha(owner, repo, ref)
    if not tree_sha:
        logger.warning(f"Could not resolve ref '{ref}' to a tree SHA for {owner}/{repo}")
        return []

    tree_data = api_get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}",
        params={"recursive": "1"},
    )
    if not tree_data:
        return []
    if tree_data.get("truncated"):
        logger.warning(f"Tree truncated for {owner}/{repo}@{ref} — large repo, some files may be missed.")
    return [item for item in tree_data.get("tree", []) if item["type"] == "blob"]


def get_file_content_by_sha(owner: str, repo: str, sha: str) -> Optional[str]:
    """Fetch and decode file content using the blob SHA from the tree.

    Using the blob SHA (rather than the Contents API path) means:
      - No 404s for files that only exist on a non-default branch
      - Slightly faster — no branch/path resolution step
    """
    data = api_get(f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{sha}")
    if not data:
        return None
    encoding = data.get("encoding")
    raw = data.get("content", "")
    try:
        if encoding == "base64":
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        elif encoding == "utf-8":
            return raw
    except Exception:
        return None
    return None

# ──────────────────────────────────────────────
# DETECTION LOGIC
# ──────────────────────────────────────────────

def detect_keywords(content: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw in content]


def classify_kotlin_file(content: str) -> tuple[str, list[str]]:
    compose_hits = detect_keywords(content, COMPOSE_KEYWORDS)
    view_hits = detect_keywords(content, KOTLIN_ANDROID_VIEW_KEYWORDS)
    if compose_hits and view_hits:
        return "Mixed (Compose + Android Views)", compose_hits + view_hits
    if compose_hits:
        return "Jetpack Compose", compose_hits
    if view_hits:
        return "Android Views", view_hits
    return "Unknown", []


def classify_xml_file(content: str) -> tuple[str, list[str]]:
    xml_hits = detect_keywords(content, XML_VIEW_KEYWORDS)
    if xml_hits:
        return "Android Views", xml_hits
    return "Unknown", []


def classify_swift_file(content: str) -> tuple[str, list[str]]:
    swiftui_hits = detect_keywords(content, SWIFTUI_KEYWORDS)
    uikit_hits = detect_keywords(content, UIKIT_KEYWORDS)
    if swiftui_hits and uikit_hits:
        return "Mixed (SwiftUI + UIKit)", swiftui_hits + uikit_hits
    if swiftui_hits:
        return "SwiftUI", swiftui_hits
    if uikit_hits:
        return "UIKit", uikit_hits
    return "Unknown", []

def classify_storyboard_file(content: str) -> tuple[str, list[str]]:
    storyboard_hits = detect_keywords(content, STORYBOARD_KEYWORDS)
    if storyboard_hits:
        return "UIKit (Storyboard/XIB)", storyboard_hits
    return "Unknown", []

# ──────────────────────────────────────────────
# REPO METADATA
# ──────────────────────────────────────────────

def get_repo_metadata(owner: str, repo: str) -> dict:
    """Fetch stars, open issues, forks, last push, commits, contributors, and open PRs."""
    base = f"https://api.github.com/repos/{owner}/{repo}"
    data = api_get(base)
    if not data:
        return {}

    commits      = api_count(f"{base}/commits")
    contributors = api_count(f"{base}/contributors", params={"anon": "true"})
    open_prs     = api_count(f"{base}/pulls", params={"state": "open"})

    return {
        "stars":              data.get("stargazers_count"),
        "open_issues":        data.get("open_issues_count"),
        "forks":              data.get("forks_count"),
        "last_push":          data.get("pushed_at", "")[:10],
        "commits":            commits,
        "contributors":       contributors,
        "open_pull_requests": open_prs,
    }


def summarize_results(repo_label: str, results: list[FileResult], metadata: dict) -> RepoSummary:
    """Aggregate file-level results into a single RepoSummary row."""
    counts: dict[str, int] = {}
    for r in results:
        counts[r.framework] = counts.get(r.framework, 0) + 1

    compose   = counts.get("Jetpack Compose", 0)
    views     = counts.get("Android Views", 0)
    swiftui   = counts.get("SwiftUI", 0)
    uikit     = counts.get("UIKit", 0)
    mixed     = sum(v for k, v in counts.items() if "Mixed" in k)
    total     = sum(counts.values())

    def pct(n: int) -> float:
        return round(100 * n / total, 1) if total > 0 else 0.0

    dominant = max(counts, key=counts.get) if counts else "Unknown"

    return RepoSummary(
        repo=repo_label,
        stars=metadata.get("stars"),
        open_issues=metadata.get("open_issues"),
        last_push=metadata.get("last_push"),
        forks=metadata.get("forks"),
        commits=metadata.get("commits"),
        contributors=metadata.get("contributors"),
        open_pull_requests=metadata.get("open_pull_requests"),
        total_ui_files=total,
        compose_files=compose,
        android_views_files=views,
        swiftui_files=swiftui,
        uikit_files=uikit,
        mixed_files=mixed,
        compose_pct=pct(compose),
        android_views_pct=pct(views),
        swiftui_pct=pct(swiftui),
        uikit_pct=pct(uikit),
        dominant_framework=dominant,
    )


# ──────────────────────────────────────────────
# MAIN MINING LOGIC
# ──────────────────────────────────────────────

def mine_repo(owner: str, repo: str, ref: Optional[str] = None) -> list[FileResult]:
    full_name = f"{owner}/{repo}"
    label = f"{full_name}@{ref}" if ref else full_name
    logger.info(f"Mining: {label}")
    results = []

    tree = get_tree(owner, repo, ref)
    if not tree:
        logger.warning(f"No files found for {label}")
        return results

    candidates = []
    for item in tree:
        path = item["path"]
        _, ext = os.path.splitext(path.lower())
        if ext in XML_EXTENSIONS:
            # Only scan XML files inside a res/layout directory — skip manifests,
            # values, drawables, navigation graphs, etc.
            path_lower = path.lower()
            is_layout_xml = any(
                part.startswith("layout") for part in path_lower.split("/")
            )
            if not is_layout_xml:
                continue
        elif ext not in KOTLIN_EXTENSIONS | SWIFT_EXTENSIONS | STORYBOARD_EXTENSIONS:
            continue
        candidates.append(item)

    if MAX_FILES_PER_REPO is not None:
        candidates = candidates[:MAX_FILES_PER_REPO]

    logger.info(f"  {len(candidates)} candidate files to scan in {label}")

    # Use the ref in the GitHub URL so links point to the right branch/commit
    url_ref = ref or "HEAD"

    for item in candidates:
        path = item["path"]
        sha = item["sha"]
        _, ext = os.path.splitext(path.lower())
        html_url = f"https://github.com/{full_name}/blob/{url_ref}/{path}"

        content = get_file_content_by_sha(owner, repo, sha)
        if content is None:
            continue

        if ext in KOTLIN_EXTENSIONS:
            framework, keywords = classify_kotlin_file(content)
            language = "Kotlin"
        elif ext in XML_EXTENSIONS:
            framework, keywords = classify_xml_file(content)
            language = "XML"
        elif ext in SWIFT_EXTENSIONS:
            framework, keywords = classify_swift_file(content)
            language = "Swift"
        elif ext in STORYBOARD_EXTENSIONS:
            framework, keywords = classify_storyboard_file(content)
            language = "Storyboard/xib"
        else:
            continue

        if framework == "Unknown":
            continue  # skip unclassified files

        results.append(FileResult(
            repo=label,          # includes @ref so CSV is unambiguous
            file_path=path,
            language=language,
            framework=framework,
            matched_keywords=keywords[:10],  # cap to keep CSV tidy
            html_url=html_url,
        ))
        logger.info(f"    ✓ [{framework}] {path}")

    logger.info(f"  Done. {len(results)} relevant files found in {label}.")
    return results


def save_summary_csv(summaries: list[RepoSummary], output_path: str):
    fields = [
        "repo", "stars", "open_issues", "last_push", "forks",
        "commits", "contributors", "open_pull_requests",
        "total_ui_files",
        "compose_files", "android_views_files", "swiftui_files", "uikit_files", "mixed_files",
        "compose_pct", "android_views_pct", "swiftui_pct", "uikit_pct",
        "dominant_framework",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for s in summaries:
            writer.writerow({k: getattr(s, k) for k in fields})
    logger.info(f"Summary saved to: {output_path}")


def save_csv(results: list[FileResult], output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "repo", "file_path", "language", "framework", "matched_keywords", "html_url"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "repo": r.repo,
                "file_path": r.file_path,
                "language": r.language,
                "framework": r.framework,
                "matched_keywords": "; ".join(r.matched_keywords),
                "html_url": r.html_url,
            })
    logger.info(f"Results saved to: {output_path}")


def parse_repo_str(repo_str: str) -> tuple[str, str, Optional[str]]:
    """Parse 'owner/repo' or 'owner/repo@ref' into (owner, repo, ref)."""
    repo_str = repo_str.strip()
    ref = None
    if "@" in repo_str:
        repo_str, ref = repo_str.split("@", 1)
    owner, repo = repo_str.split("/", 1)
    return owner, repo, ref


def update_single_repo(repo_str: str):
    """Re-mine one repo and replace only its rows in both CSVs."""
    owner, repo, ref = parse_repo_str(repo_str)
    label = f"{owner}/{repo}@{ref}" if ref else f"{owner}/{repo}"
    logger.info(f"Updating single repo: {label}")

    metadata = get_repo_metadata(owner, repo)
    results  = mine_repo(owner, repo, ref)
    summary  = summarize_results(label, results, metadata)

    # --- Update repo_summary.csv ---
    summary_fields = [
        "repo", "stars", "open_issues", "last_push", "forks",
        "commits", "contributors", "open_pull_requests",
        "total_ui_files",
        "compose_files", "android_views_files", "swiftui_files", "uikit_files", "mixed_files",
        "compose_pct", "android_views_pct", "swiftui_pct", "uikit_pct",
        "dominant_framework",
    ]
    if os.path.exists(OUTPUT_SUMMARY_CSV):
        with open(OUTPUT_SUMMARY_CSV, newline="", encoding="utf-8") as f:
            existing_summaries = list(csv.DictReader(f))
        existing_summaries = [r for r in existing_summaries if r["repo"] != label]
    else:
        existing_summaries = []
    existing_summaries.append({k: getattr(summary, k) for k in summary_fields})

    with open(OUTPUT_SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(existing_summaries)
    logger.info(f"Summary updated: {OUTPUT_SUMMARY_CSV}")

    # --- Update repo_data.csv ---
    file_fields = ["repo", "file_path", "language", "framework", "matched_keywords", "html_url"]
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            existing_files = list(csv.DictReader(f))
        existing_files = [r for r in existing_files if r["repo"] != label]
    else:
        existing_files = []
    for r in results:
        existing_files.append({
            "repo": r.repo,
            "file_path": r.file_path,
            "language": r.language,
            "framework": r.framework,
            "matched_keywords": "; ".join(r.matched_keywords),
            "html_url": r.html_url,
        })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=file_fields)
        writer.writeheader()
        writer.writerows(existing_files)
    logger.info(f"File data updated: {OUTPUT_CSV}")

    print(f"\n✅ Updated {label}: {len(results)} files found.")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update", metavar="REPO",
        help="Re-mine a single repo and update CSVs (e.g. 'Stypox/dicio-android@81e0cbda')"
    )
    args = parser.parse_args()

    if args.update:
        update_single_repo(args.update)
        return

    if not REPOS:
        raise ValueError("Please add at least one repository to the REPOS list.")

    all_results: list[FileResult] = []
    all_summaries: list[RepoSummary] = []

    for repo_str in REPOS:
        owner, repo, ref = parse_repo_str(repo_str)
        try:
            metadata = get_repo_metadata(owner, repo)
            results = mine_repo(owner, repo, ref)
            all_results.extend(results)
            label = f"{owner}/{repo}@{ref}" if ref else f"{owner}/{repo}"
            all_summaries.append(summarize_results(label, results, metadata))
        except Exception as e:
            logger.error(f"Failed to mine {repo_str}: {e}")

    if all_results:
        save_csv(all_results, OUTPUT_CSV)
        save_summary_csv(all_summaries, OUTPUT_SUMMARY_CSV)
        print(f"\n✅ Done! {len(all_results)} files across {len(REPOS)} repos")
        print(f"   File-level  → {OUTPUT_CSV}")
        print(f"   Repo summary → {OUTPUT_SUMMARY_CSV}")
    else:
        print("\n⚠️  No matching files found. Check your repo list and token.")


if __name__ == "__main__":
    main()