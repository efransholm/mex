"""
CBO (Coupling Between Object Classes) Analyzer for Kotlin and Swift.

Definition: CBO measures the number of distinct external classes a class is coupled to,
via inheritance, field types, method parameter/return types, local variable types,
and constructor/function calls.

Usage:
    python cbo_analyzer.py path/to/file_or_directory [--lang kotlin|swift|auto]
    python cbo_analyzer.py --help
"""

import re
import sys
import argparse
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Primitive / built-in type sets (excluded from CBO counts)
# ---------------------------------------------------------------------------

KOTLIN_PRIMITIVES = {
    "Int", "Long", "Short", "Byte", "Double", "Float", "Boolean", "Char",
    "String", "Unit", "Any", "Nothing", "Number", "Void",
    "List", "MutableList", "Set", "MutableSet", "Map", "MutableMap",
    "Collection", "MutableCollection", "Iterable", "Sequence",
    "Array", "IntArray", "LongArray", "DoubleArray", "FloatArray",
    "BooleanArray", "CharArray", "ByteArray", "ShortArray",
    "Pair", "Triple", "Result", "Lazy",
    "Exception", "Error", "Throwable", "RuntimeException",
    "println", "print", "TODO", "require", "check", "error",
}

SWIFT_PRIMITIVES = {
    "Int", "Int8", "Int16", "Int32", "Int64",
    "UInt", "UInt8", "UInt16", "UInt32", "UInt64",
    "Float", "Double", "Bool", "Character", "String",
    "Void", "Never", "Any", "AnyObject",
    "Optional", "Array", "Dictionary", "Set",
    "Range", "ClosedRange", "PartialRangeFrom", "PartialRangeThrough",
    "Error", "NSError",
    "Comparable", "Equatable", "Hashable", "Codable", "Identifiable",
    "Sendable", "CustomStringConvertible", "CustomDebugStringConvertible",
    "print", "fatalError", "precondition", "assert", "debugPrint",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CouplingDetail:
    """Tracks where each coupling was detected."""
    coupled_class: str
    reasons: list = field(default_factory=list)

    def add_reason(self, reason: str):
        if reason not in self.reasons:
            self.reasons.append(reason)


@dataclass
class ClassCBO:
    name: str
    language: str
    file: str
    couplings: dict = field(default_factory=dict)

    @property
    def cbo(self) -> int:
        return len(self.couplings)

    def add_coupling(self, class_name: str, reason: str):
        if class_name == self.name:
            return  # skip self-references
        if class_name not in self.couplings:
            self.couplings[class_name] = CouplingDetail(coupled_class=class_name)
        self.couplings[class_name].add_reason(reason)


@dataclass
class AnalysisResult:
    file: str
    language: str
    classes: list = field(default_factory=list)

    @property
    def total_cbo(self) -> int:
        return sum(c.cbo for c in self.classes)

    @property
    def average_cbo(self) -> float:
        return self.total_cbo / len(self.classes) if self.classes else 0.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def extract_type_names(type_str: str) -> list:
    """Return all PascalCase identifiers from a type expression."""
    if not type_str:
        return []
    cleaned = re.sub(r'[\[\]?!]', ' ', type_str)
    return re.findall(r'\b[A-Z][A-Za-z0-9_]*\b', cleaned)


def is_user_type(name: str, primitives: set) -> bool:
    """True if the name looks like a user-defined class (not a primitive)."""
    return (
        bool(name)
        and len(name) > 1
        and name[0].isupper()
        and name not in primitives
    )


def strip_comments(source: str) -> str:
    """Remove single-line and block comments from source."""
    # Block comments /* ... */
    source = re.sub(r'/\*.*?\*/', ' ', source, flags=re.DOTALL)
    # Single-line comments // ...
    source = re.sub(r'//[^\n]*', ' ', source)
    return source


# ---------------------------------------------------------------------------
# Kotlin Analyzer
# ---------------------------------------------------------------------------

class KotlinAnalyzer:
    PRIMITIVES = KOTLIN_PRIMITIVES

    # Matches class/interface/object/enum class declarations
    CLASS_RE = re.compile(
        r'(?:(?:public|private|protected|internal|abstract|open|sealed|data|inline|value|annotation|enum)\s+)*'
        r'(?:class|interface|object)\s+([A-Z][A-Za-z0-9_]*)'
    )
    # Supertype list after class Foo(...) : Bar, Baz<T>
    SUPERTYPE_RE = re.compile(
        r'(?:class|interface|object)\s+[A-Za-z0-9_]+(?:\s*<[^>]*>)?\s*(?:\([^)]*\))?\s*:\s*([^{]+)'
    )
    # val/var name: Type
    FIELD_RE = re.compile(r'(?:val|var)\s+\w+\s*:\s*([A-Za-z][A-Za-z0-9_<>, ?\[\]]*)')
    # fun name(...): ReturnType
    FUN_RETURN_RE = re.compile(
        r'\bfun\s+(?:<[^>]*>\s*)?\w+\s*\([^)]*\)\s*:\s*([A-Za-z][A-Za-z0-9_<>, ?\[\]]*)'
    )
    # name: Type  (parameter or local)
    TYPED_NAME_RE = re.compile(r'\b\w+\s*:\s*([A-Z][A-Za-z0-9_<>, ?\[\]]*)')
    # UpperCase( or UpperCase.  (constructor/static calls)
    CALL_RE = re.compile(r'\b([A-Z][A-Za-z0-9_]*)\s*[.(]')

    def analyze_file(self, source: str, filepath: str) -> AnalysisResult:
        source = strip_comments(source)
        result = AnalysisResult(file=filepath, language="kotlin")
        class_spans = self._find_class_spans(source)

        for class_name, body in class_spans:
            entry = ClassCBO(name=class_name, language="kotlin", file=filepath)
            self._analyze_supertypes(body, entry)
            self._analyze_fields(body, entry)
            self._analyze_fun_returns(body, entry)
            self._analyze_typed_names(body, entry)
            self._analyze_calls(body, entry)
            result.classes.append(entry)

        return result

    def _find_class_spans(self, source: str) -> list:
        """Find (class_name, body_text) for each class in the file."""
        positions = [(m.group(1), m.start()) for m in self.CLASS_RE.finditer(source)]
        spans = []
        for i, (name, start) in enumerate(positions):
            end = positions[i + 1][1] if i + 1 < len(positions) else len(source)
            spans.append((name, source[start:end]))
        return spans

    def _register(self, cbo: ClassCBO, type_str: str, reason: str):
        for name in extract_type_names(type_str):
            if is_user_type(name, self.PRIMITIVES):
                cbo.add_coupling(name, reason)

    def _analyze_supertypes(self, body: str, cbo: ClassCBO):
        for m in self.SUPERTYPE_RE.finditer(body):
            for part in re.split(r',\s*(?=[A-Z])', m.group(1)):
                self._register(cbo, part.strip(), "inheritance/implements")

    def _analyze_fields(self, body: str, cbo: ClassCBO):
        for m in self.FIELD_RE.finditer(body):
            self._register(cbo, m.group(1), "field type")

    def _analyze_fun_returns(self, body: str, cbo: ClassCBO):
        for m in self.FUN_RETURN_RE.finditer(body):
            self._register(cbo, m.group(1), "return type")

    def _analyze_typed_names(self, body: str, cbo: ClassCBO):
        for m in self.TYPED_NAME_RE.finditer(body):
            self._register(cbo, m.group(1), "parameter/local type")

    def _analyze_calls(self, body: str, cbo: ClassCBO):
        for m in self.CALL_RE.finditer(body):
            name = m.group(1)
            if is_user_type(name, self.PRIMITIVES):
                cbo.add_coupling(name, "constructor/static call")


# ---------------------------------------------------------------------------
# Swift Analyzer
# ---------------------------------------------------------------------------

class SwiftAnalyzer:
    PRIMITIVES = SWIFT_PRIMITIVES

    CLASS_RE = re.compile(
        r'(?:(?:public|private|internal|fileprivate|open|final)\s+)*'
        r'(?:class|struct|enum|protocol|actor)\s+([A-Z][A-Za-z0-9_]*)'
    )
    SUPERTYPE_RE = re.compile(
        r'(?:class|struct|enum|protocol|actor)\s+[A-Za-z0-9_]+(?:\s*<[^>]*>)?\s*:\s*([^{]+)'
    )
    FIELD_RE = re.compile(r'(?:var|let)\s+\w+\s*:\s*([A-Za-z][A-Za-z0-9_<>, ?\[\]!]*)')
    RETURN_RE = re.compile(r'->\s*([A-Za-z][A-Za-z0-9_<>, ?\[\]!]*)')
    TYPED_NAME_RE = re.compile(r'\b\w+\s*:\s*([A-Z][A-Za-z0-9_<>, ?\[\]!]*)')
    CALL_RE = re.compile(r'\b([A-Z][A-Za-z0-9_]*)\s*[.(]')
    ATTR_RE = re.compile(r'@\w+|#\w+')

    def analyze_file(self, source: str, filepath: str) -> AnalysisResult:
        source = strip_comments(source)
        source = self.ATTR_RE.sub('', source)  # remove @attributes / #directives
        result = AnalysisResult(file=filepath, language="swift")
        class_spans = self._find_class_spans(source)

        for class_name, body in class_spans:
            entry = ClassCBO(name=class_name, language="swift", file=filepath)
            self._analyze_supertypes(body, entry)
            self._analyze_fields(body, entry)
            self._analyze_returns(body, entry)
            self._analyze_typed_names(body, entry)
            self._analyze_calls(body, entry)
            result.classes.append(entry)

        return result

    def _find_class_spans(self, source: str) -> list:
        positions = [(m.group(1), m.start()) for m in self.CLASS_RE.finditer(source)]
        spans = []
        for i, (name, start) in enumerate(positions):
            end = positions[i + 1][1] if i + 1 < len(positions) else len(source)
            spans.append((name, source[start:end]))
        return spans

    def _register(self, cbo: ClassCBO, type_str: str, reason: str):
        for name in extract_type_names(type_str):
            if is_user_type(name, self.PRIMITIVES):
                cbo.add_coupling(name, reason)

    def _analyze_supertypes(self, body: str, cbo: ClassCBO):
        for m in self.SUPERTYPE_RE.finditer(body):
            for part in re.split(r',\s*(?=[A-Z])', m.group(1)):
                self._register(cbo, part.strip(), "inheritance/conformance")

    def _analyze_fields(self, body: str, cbo: ClassCBO):
        for m in self.FIELD_RE.finditer(body):
            self._register(cbo, m.group(1), "field type")

    def _analyze_returns(self, body: str, cbo: ClassCBO):
        for m in self.RETURN_RE.finditer(body):
            self._register(cbo, m.group(1), "return type")

    def _analyze_typed_names(self, body: str, cbo: ClassCBO):
        for m in self.TYPED_NAME_RE.finditer(body):
            self._register(cbo, m.group(1), "parameter/local type")

    def _analyze_calls(self, body: str, cbo: ClassCBO):
        for m in self.CALL_RE.finditer(body):
            name = m.group(1)
            if is_user_type(name, self.PRIMITIVES):
                cbo.add_coupling(name, "constructor/static call")


# ---------------------------------------------------------------------------
# File dispatcher
# ---------------------------------------------------------------------------

def detect_language(filepath: str):
    ext = Path(filepath).suffix.lower()
    if ext in (".kt", ".kts"):
        return "kotlin"
    if ext == ".swift":
        return "swift"
    return None


def analyze_file(filepath: str, language=None):
    lang = language or detect_language(filepath)
    if lang is None:
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError as e:
        print(f"[ERROR] Cannot read {filepath}: {e}", file=sys.stderr)
        return None

    if lang == "kotlin":
        return KotlinAnalyzer().analyze_file(source, filepath)
    elif lang == "swift":
        return SwiftAnalyzer().analyze_file(source, filepath)
    return None


def analyze_path(path: str, language=None) -> list:
    p = Path(path)
    results = []
    if p.is_file():
        r = analyze_file(str(p), language)
        if r:
            results.append(r)
    elif p.is_dir():
        for fpath in sorted(p.rglob("*")):
            if fpath.suffix.lower() in (".kt", ".kts", ".swift"):
                r = analyze_file(str(fpath), language)
                if r:
                    results.append(r)
    else:
        print(f"[ERROR] Path not found: {path}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def coupling_label(cbo: int) -> str:
    if cbo < 5:
        return "LOW"
    if cbo < 10:
        return "MEDIUM"
    return "HIGH"


def coupling_icon(cbo: int) -> str:
    if cbo < 5:
        return "OK "
    if cbo < 10:
        return "WRN"
    return "ERR"


def print_report(results: list, verbose: bool = False):
    if not results:
        print("No classes found.")
        return

    all_classes = [cls for r in results for cls in r.classes]

    print()
    print("=" * 72)
    print("  CBO ANALYSIS REPORT")
    print("=" * 72)

    for r in results:
        if not r.classes:
            continue
        print(f"\n  File : {r.file}")
        print(f"  Lang : {r.language}  |  Classes: {len(r.classes)}  "
              f"|  Total CBO: {r.total_cbo}  |  Avg CBO: {r.average_cbo:.1f}")

        for cls in sorted(r.classes, key=lambda c: c.cbo, reverse=True):
            icon = coupling_icon(cls.cbo)
            print(f"\n  [{icon}] {cls.name}  —  CBO = {cls.cbo}  ({coupling_label(cls.cbo)})")
            if cls.couplings:
                for cname, detail in sorted(cls.couplings.items()):
                    reasons = ", ".join(detail.reasons)
                    print(f"        • {cname:<32} [{reasons}]")
            else:
                print("        (no external couplings)")
    print()

    # ── Summary table ──────────────────────────────────────────────────────
    print("=" * 72)
    print("  SUMMARY TABLE")
    print("=" * 72)
    print(f"  {'Class':<34} {'File':<22} {'CBO':>4}  {'Level'}")
    print(f"  {'-'*34} {'-'*22} {'-'*4}  {'-'*8}")
    for cls in sorted(all_classes, key=lambda c: c.cbo, reverse=True):
        fname = Path(cls.file).name
        print(f"  {cls.name:<34} {fname:<22} {cls.cbo:>4}  {coupling_label(cls.cbo)}")

    total  = len(all_classes)
    n_low  = sum(1 for c in all_classes if c.cbo < 5)
    n_med  = sum(1 for c in all_classes if 5 <= c.cbo < 10)
    n_high = sum(1 for c in all_classes if c.cbo >= 10)
    avg    = sum(c.cbo for c in all_classes) / total if total else 0

    print()
    print(f"  Total classes   : {total}")
    print(f"  Average CBO     : {avg:.2f}")
    print(f"  Low   (<5)  OK  : {n_low}")
    print(f"  Medium (5-9) WRN: {n_med}")
    print(f"  High  (>=10) ERR: {n_high}")
    print("=" * 72)
    print()


def export_csv(results: list, output_path: str):
    import csv
    rows = []
    for r in results:
        for cls in r.classes:
            coupled = "; ".join(
                f"{name}({','.join(d.reasons)})"
                for name, d in sorted(cls.couplings.items())
            )
            rows.append({
                "file": r.file,
                "language": r.language,
                "class": cls.name,
                "cbo": cls.cbo,
                "level": coupling_label(cls.cbo),
                "coupled_classes": coupled,
            })
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["file", "language", "class", "cbo", "level", "coupled_classes"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV exported → {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CBO Analyzer for Kotlin and Swift.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cbo_analyzer.py MyClass.kt
  python cbo_analyzer.py src/  --lang kotlin
  python cbo_analyzer.py src/  --lang swift  --csv report.csv
  python cbo_analyzer.py src/  --threshold 7
        """,
    )
    parser.add_argument("path", help="File or directory to analyze")
    parser.add_argument(
        "--lang", choices=["kotlin", "swift", "auto"], default="auto",
        help="Language override (default: auto-detect from extension)"
    )
    parser.add_argument("--csv", metavar="FILE", help="Export results to CSV")
    parser.add_argument(
        "--threshold", type=int, default=None,
        help="Only report classes with CBO >= threshold"
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    lang = None if args.lang == "auto" else args.lang
    results = analyze_path(args.path, lang)

    if not results:
        print("No Kotlin or Swift source files found.")
        sys.exit(1)

    if args.threshold is not None:
        for r in results:
            r.classes = [c for c in r.classes if c.cbo >= args.threshold]
        results = [r for r in results if r.classes]

    print_report(results, verbose=args.verbose)

    if args.csv:
        export_csv(results, args.csv)


# ---------------------------------------------------------------------------
# Programmatic API
# ---------------------------------------------------------------------------

def analyze(path: str, language=None) -> list:
    """
    Public API for use as a library.

    Args:
        path:     Path to a .kt / .swift file or a directory.
        language: 'kotlin', 'swift', or None (auto-detect from extension).

    Returns:
        List of AnalysisResult objects.

    Example:
        from cbo_analyzer import analyze
        for result in analyze("src/"):
            for cls in result.classes:
                print(f"{cls.name}: CBO={cls.cbo}")
    """
    return analyze_path(path, language)


if __name__ == "__main__":
    main()