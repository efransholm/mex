"""
CBO (Coupling Between Objects) calculator for Kotlin source files.

Analyzes .kt files and counts how many distinct external classes each class
is coupled to. Can be run standalone or imported into the GitHub miner.

Usage:
    python cbo.py --input /path/to/kotlin/src --output cbo_results.csv
    python cbo.py --input /path/to/single/File.kt
"""

import re
import csv
import argparse
from pathlib import Path
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# EXCLUDED TYPES
# Kotlin/Java builtins that don't count as coupling
# ──────────────────────────────────────────────

EXCLUDED = {
    "String", "Int", "Long", "Double", "Float", "Boolean", "Char", "Byte", "Short",
    "Unit", "Any", "Nothing", "Number", "Void",
    "List", "MutableList", "Set", "MutableSet", "Map", "MutableMap",
    "Collection", "MutableCollection", "Iterable", "Sequence",
    "Array", "IntArray", "LongArray", "BooleanArray", "ByteArray", "CharArray",
    "Pair", "Triple", "Result", "Lazy", "Optional",
    "Exception", "Throwable", "Error", "RuntimeException",
    "Function", "Comparator", "Iterator",
    "Override", "Suppress", "JvmStatic", "JvmField", "JvmOverloads",
    "Throws", "Deprecated", "Nullable", "NonNull",
    # Common noise from annotations and keywords that look like types
    "True", "False", "Null", "This", "Super", "It",
}

# Single-word prefixes that indicate a stdlib/language reference, not a user class
EXCLUDED_PREFIXES = ("kotlin.", "java.", "android.os.", "androidx.annotation.")


@dataclass
class ClassCbo:
    file: str
    class_name: str
    cbo: int
    coupled_to: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# PARSING
# ──────────────────────────────────────────────

# Matches class/object/interface declarations
CLASS_DECL = re.compile(
    r"(?:^|\n)[ \t]*(?:(?:data|sealed|abstract|open|inner|enum|annotation|value)\s+)*"
    r"(class|object|interface)\s+(\w+)"
)

# Matches any PascalCase identifier — our proxy for "a type reference"
PASCAL_CASE = re.compile(r"\b([A-Z][a-zA-Z0-9]+)\b")

# Strip string literals and comments before analysis to avoid false positives
STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')
LINE_COMMENT   = re.compile(r"//[^\n]*")
BLOCK_COMMENT  = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_noise(source: str) -> str:
    source = BLOCK_COMMENT.sub(" ", source)
    source = LINE_COMMENT.sub(" ", source)
    source = STRING_LITERAL.sub('""', source)
    return source


def split_into_class_blocks(source: str) -> list[tuple[str, str]]:
    """
    Returns [(class_name, block_source), ...] where block_source is the
    portion of the file from the class declaration until the next top-level
    class declaration (or EOF).
    """
    matches = list(CLASS_DECL.finditer(source))
    if not matches:
        return []

    blocks = []
    for i, m in enumerate(matches):
        name = m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        blocks.append((name, source[start:end]))
    return blocks


def collect_coupled_types(block: str, class_name: str) -> list[str]:
    coupled = set()
    for m in PASCAL_CASE.finditer(block):
        t = m.group(1)
        if (
            t != class_name
            and t not in EXCLUDED
            and len(t) > 2
            and not any(t.startswith(p) for p in EXCLUDED_PREFIXES)
        ):
            coupled.add(t)
    return sorted(coupled)


def analyze_file(path: Path) -> list[ClassCbo]:
    try:
        source = strip_noise(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        print(f"WARN: Could not read {path}: {e}")
        return []

    results = []
    for class_name, block in split_into_class_blocks(source):
        coupled = collect_coupled_types(block, class_name)
        results.append(ClassCbo(
            file=str(path),
            class_name=class_name,
            cbo=len(coupled),
            coupled_to=coupled,
        ))
    return results


def analyze_directory(root: Path) -> list[ClassCbo]:
    results = []
    kt_files = list(root.rglob("*.kt"))
    print(f"Found {len(kt_files)} Kotlin files under {root}")
    for f in kt_files:
        results.extend(analyze_file(f))
    return results


# ──────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────

def write_csv(results: list[ClassCbo], output: str):
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "class", "cbo", "coupled_to"])
        writer.writeheader()
        for r in sorted(results, key=lambda x: -x.cbo):
            writer.writerow({
                "file": r.file,
                "class": r.class_name,
                "cbo": r.cbo,
                "coupled_to": "; ".join(r.coupled_to),
            })
    print(f"Results written to: {output}")


def print_summary(results: list[ClassCbo], threshold: int):
    if not results:
        print("No classes found.")
        return
    sorted_results = sorted(results, key=lambda x: -x.cbo)
    avg = sum(r.cbo for r in results) / len(results)
    over = [r for r in results if r.cbo >= threshold]

    print(f"\n{'─' * 72}")
    print(f"  {'Class':<45} {'CBO':>5}  Status")
    print(f"{'─' * 72}")
    for r in sorted_results:
        status = f"⚠  >= {threshold}" if r.cbo >= threshold else "✓"
        print(f"  {r.class_name:<45} {r.cbo:>5}  {status}")
    print(f"{'─' * 72}")
    print(f"  Classes analyzed : {len(results)}")
    print(f"  Average CBO      : {avg:.2f}")
    print(f"  Max CBO          : {sorted_results[0].cbo} ({sorted_results[0].class_name})")
    print(f"  Over threshold   : {len(over)} (threshold={threshold})")
    print()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate CBO for Kotlin source files.")
    parser.add_argument("--input",     required=True, help="Path to a .kt file or directory")
    parser.add_argument("--output",    default="cbo_results.csv", help="Output CSV (default: cbo_results.csv)")
    parser.add_argument("--threshold", type=int, default=10, help="Flag classes at or above this CBO (default: 10)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Path does not exist: {input_path}")
        raise SystemExit(1)

    results = analyze_file(input_path) if input_path.is_file() else analyze_directory(input_path)
    print_summary(results, args.threshold)
    write_csv(results, args.output)