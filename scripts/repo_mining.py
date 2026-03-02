import os 
import requests
import csv
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional
import time

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is not set.")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# can also add the repo at a specific commit/branch/tag like "owner/repo@commitish" if needed
REPOS = [
    "android/sunflower",
    "android/sunflower@views"
]

OUTPUT_CSV = "repo_data.csv"

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

    tree_data = api_get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}",
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
        if ext in KOTLIN_EXTENSIONS | XML_EXTENSIONS | SWIFT_EXTENSIONS | STORYBOARD_EXTENSIONS:
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


def main():
    if GITHUB_TOKEN == "YOUR_TOKEN_HERE":
        raise ValueError("Please set your GitHub token in the GITHUB_TOKEN variable or GITHUB_TOKEN env var.")

    if not REPOS:
        raise ValueError("Please add at least one repository to the REPOS list.")

    all_results: list[FileResult] = []

    for repo_str in REPOS:
        repo_str = repo_str.strip()

        # Parse optional @ref suffix — works for branches, tags, and commit SHAs
        # e.g. "android/sunflower@views"  or  "android/sunflower@abc1234"
        ref = None
        if "@" in repo_str:
            repo_str, ref = repo_str.split("@", 1)

        if "/" not in repo_str:
            logger.error(f"Invalid repo format (expected 'owner/repo' or 'owner/repo@ref'): {repo_str}")
            continue

        owner, repo = repo_str.split("/", 1)
        try:
            results = mine_repo(owner, repo, ref)
            all_results.extend(results)
        except Exception as e:
            logger.error(f"Failed to mine {repo_str}@{ref or 'default'}: {e}")

    if all_results:
        save_csv(all_results, OUTPUT_CSV)
        print(f"\n✅ Done! {len(all_results)} files across {len(REPOS)} repos → {OUTPUT_CSV}")
    else:
        print("\n⚠️  No matching files found. Check your repo list and token.")


if __name__ == "__main__":
    main()