"""
SonarCloud utilities: generate config, run scanner, wait for analysis, fetch results.
"""
import json
import os
import re
import ssl
import subprocess
import time
import urllib.request
import urllib.error

SONAR_HOST = "https://sonarcloud.io"
SONAR_LOCAL_HOST = "http://localhost:9000"

# Project-level metrics (includes file/class/function counts)
METRICS_PROJECT = ",".join([
    "ncloc", "lines", "comment_lines", "comment_lines_density",
    "statements", "files", "classes", "functions",
    "complexity", "cognitive_complexity",
    "bugs", "code_smells", "sqale_debt_ratio",
    "duplicated_lines_density",
])

# Per-file metrics (same minus the aggregate-only "files" counter)
METRICS_FILE = ",".join([
    "ncloc", "lines", "comment_lines", "comment_lines_density",
    "statements", "classes", "functions",
    "complexity", "cognitive_complexity",
    "bugs", "code_smells", "sqale_debt_ratio",
    "duplicated_lines_density",
])


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context that works on macOS where Python may lack system certs."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        # macOS: load system keychain certs
        ctx.load_default_certs()
    return ctx


def generate_properties(project_path: str, project_key: str, org: str, local: bool = False) -> str:
    """Write sonar-project.properties into project_path. Returns the file path."""
    host = SONAR_LOCAL_HOST if local else SONAR_HOST
    if local:
        content = (
            f"sonar.projectKey={project_key}\n"
            f"sonar.sources=.\n"
            f"sonar.host.url={host}\n"
        )
    else:
        content = (
            f"sonar.projectKey={project_key}\n"
            f"sonar.organization={org}\n"
            f"sonar.sources=.\n"
            f"sonar.host.url={host}\n"
            f"sonar.projectVisibility=public\n"
        )
    props_path = os.path.join(project_path, "sonar-project.properties")
    with open(props_path, "w") as f:
        f.write(content)
    return props_path


def run_scanner(project_path: str, sonar_token: str) -> str | None:
    """
    Run sonar-scanner in project_path.
    Returns the CE task ID, or None if the scan failed.
    """
    result = subprocess.run(
        ["sonar-scanner", f"-Dsonar.token={sonar_token}"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"    [sonar] Scanner failed (exit {result.returncode}):")
        print(result.stderr[-1500:])
        return None

    for line in result.stdout.splitlines():
        m = re.search(r"ceTaskUrl.*?id=([A-Za-z0-9_-]+)", line)
        if m:
            return m.group(1)
        # alternate format: "More about the report processing at <url>"
        m = re.search(r"api/ce/task\?id=([A-Za-z0-9_-]+)", line)
        if m:
            return m.group(1)

    print("    [sonar] Scanner succeeded but no task ID found in output.")
    return None


def wait_for_analysis(task_id: str, sonar_token: str, timeout: int = 180, host: str = SONAR_HOST) -> bool:
    """
    Poll the CE task endpoint until the analysis is SUCCESS or FAILED.
    Returns True if successful.
    """
    url = f"{host}/api/ce/task?id={task_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {sonar_token}")
        try:
            with urllib.request.urlopen(req, context=_ssl_context()) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as e:
            print(f"    [sonar] Poll error: {e}")
            time.sleep(5)
            continue

        status = data.get("task", {}).get("status", "PENDING")
        print(f"    [sonar] Task status: {status}")
        if status == "SUCCESS":
            return True
        if status in ("FAILED", "CANCELLED"):
            return False
        time.sleep(5)

    print(f"    [sonar] Timed out waiting for task {task_id}")
    return False


def _coerce(raw) -> int | float | str | None:
    """Coerce a SonarQube measure value string to a number where possible."""
    try:
        return float(raw) if "." in str(raw) else int(raw)
    except (TypeError, ValueError):
        return raw


def _get_json(url: str, sonar_token: str) -> dict | None:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {sonar_token}")
    try:
        with urllib.request.urlopen(req, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"    [sonar] HTTP {e.code} fetching {url}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"    [sonar] URL error fetching {url}: {e}")
        return None


def fetch_measures_project(project_key: str, sonar_token: str, host: str = SONAR_HOST) -> dict:
    """Fetch project-level measures. Returns {metric: value}."""
    url = (
        f"{host}/api/measures/component"
        f"?component={project_key}&metricKeys={METRICS_PROJECT}"
    )
    data = _get_json(url, sonar_token)
    if not data:
        return {}
    return {
        m["metric"]: _coerce(m.get("value"))
        for m in data.get("component", {}).get("measures", [])
    }


def fetch_measures_per_file(project_key: str, sonar_token: str, host: str = SONAR_HOST) -> dict:
    """
    Fetch per-file measures using the component_tree API.
    Returns {relative_file_path: {metric: value}}.
    Handles pagination automatically.
    """
    files: dict[str, dict] = {}
    page = 1
    page_size = 500

    while True:
        url = (
            f"{host}/api/measures/component_tree"
            f"?component={project_key}"
            f"&metricKeys={METRICS_FILE}"
            f"&strategy=leaves&qualifiers=FIL"
            f"&ps={page_size}&p={page}"
        )
        data = _get_json(url, sonar_token)
        if not data:
            break

        for component in data.get("components", []):
            path = component.get("path", component.get("key", "unknown"))
            measures = {
                m["metric"]: _coerce(m.get("value"))
                for m in component.get("measures", [])
            }
            files[path] = measures

        paging = data.get("paging", {})
        total = paging.get("total", 0)
        if page * page_size >= total:
            break
        page += 1

    return files


def analyze_with_sonar(
    project_path: str,
    project_key: str,
    sonar_token: str,
    org: str = "complexity-metrics",
    local: bool = False,
) -> dict:
    """
    Full pipeline: generate properties → scan → wait → fetch measures.
    Returns {"project": {metric: value}, "files": {path: {metric: value}}},
    or {"project": {}, "files": {}} on failure.
    """
    host = SONAR_LOCAL_HOST if local else SONAR_HOST
    generate_properties(project_path, project_key, org, local=local)
    print(f"    [sonar] Running scanner for {project_key} ...")
    task_id = run_scanner(project_path, sonar_token)

    if task_id:
        print(f"    [sonar] Waiting for task {task_id} ...")
        if not wait_for_analysis(task_id, sonar_token, host=host):
            print(f"    [sonar] Analysis did not complete for {project_key}")
            return {"project": {}, "files": {}}
    else:
        print("    [sonar] No task ID — attempting to fetch existing measures anyway.")

    project_measures = fetch_measures_project(project_key, sonar_token, host=host)
    file_measures = fetch_measures_per_file(project_key, sonar_token, host=host)
    print(f"    [sonar] Fetched {len(file_measures)} file(s) from SonarCloud")
    return {"project": project_measures, "files": file_measures}
