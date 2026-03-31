"""
Tests for ckcbo_analyzer.py — verifying correctness against the
Chidamber & Kemerer (1994) CBO definition.

Definition summary (what we test):
  1. CBO = number of *distinct* classes a class is coupled to.
  2. Coupled = methods declared in A use methods OR instance variables of B.
  3. Bidirectional: if A uses B, both A.CBO and B.CBO increase (once each).
  4. Multiple accesses to the same class count as ONE coupling.
  5. NOT counted: object instantiation, type annotations, constants, API/stdlib.
  6. Shared/class variables (companion object / static) are NOT counted.
  7. All method calls are counted (instance and static/shared).
  8. Child class calling its own inherited methods → coupled to parent.
"""

import textwrap
import tempfile
from pathlib import Path
import pytest
from ckcbo_analyzer import KotlinCBOAnalyzer, SwiftCBOAnalyzer, analyze


# ── helpers ──────────────────────────────────────────────────────────────────

def run_kotlin(source: str) -> dict[str, int]:
    """Parse a Kotlin source string; return {class_name: cbo}."""
    with tempfile.NamedTemporaryFile(suffix=".kt", mode="w", delete=False, encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
        path = Path(f.name)
    try:
        results = KotlinCBOAnalyzer().analyze_files([path])
        return {cls.name: cls.cbo for r in results for cls in r.classes}
    finally:
        path.unlink(missing_ok=True)


def run_swift(source: str) -> dict[str, int]:
    """Parse a Swift source string; return {class_name: cbo}."""
    with tempfile.NamedTemporaryFile(suffix=".swift", mode="w", delete=False, encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
        path = Path(f.name)
    try:
        results = SwiftCBOAnalyzer().analyze_files([path])
        return {cls.name: cls.cbo for r in results for cls in r.classes}
    finally:
        path.unlink(missing_ok=True)


def run_kotlin_multifile(files: dict[str, str]) -> dict[str, int]:
    """
    Write multiple .kt files into a temp directory and run the analyzer on
    the whole directory (simulating a real project). Returns {class_name: cbo}.
    """
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, source in files.items():
            p = Path(d) / name
            p.write_text(textwrap.dedent(source), encoding="utf-8")
            paths.append(p)
        results = KotlinCBOAnalyzer().analyze_files(paths)
        return {cls.name: cls.cbo for r in results for cls in r.classes}


def run_swift_multifile(files: dict[str, str]) -> dict[str, int]:
    """
    Write multiple .swift files into a temp directory and run the analyzer on
    the whole directory. Returns {class_name: cbo}.
    """
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, source in files.items():
            p = Path(d) / name
            p.write_text(textwrap.dedent(source), encoding="utf-8")
            paths.append(p)
        results = SwiftCBOAnalyzer().analyze_files(paths)
        return {cls.name: cls.cbo for r in results for cls in r.classes}


def run_dir(tmpdir: Path, lang: str) -> dict[str, int]:
    """Run the public analyze() API on a directory path."""
    results = analyze(str(tmpdir), language=lang)
    return {cls.name: cls.cbo for r in results for cls in r.classes}


# ── Rule 1+2: method call creates coupling ───────────────────────────────────

class TestMethodCallCreatesCoupling:
    """A method in A that calls a method defined in B → A coupled to B."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                fun process() {}
            }
            class A(val b: B) {
                fun run() { b.process() }
            }
        """)
        assert cbo["A"] == 1

    def test_swift(self):
        cbo = run_swift("""
            class B {
                func process() {}
            }
            class A {
                var b: B
                init(b: B) { self.b = b }
                func run() { b.process() }
            }
        """)
        assert cbo["A"] == 1


# ── Rule 2: instance variable access creates coupling ────────────────────────

class TestInstanceVariableAccessCreatesCoupling:
    """Accessing an instance variable of another class counts as coupling."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                val value: Int = 0
            }
            class A(val b: B) {
                fun run() { val x = b.value }
            }
        """)
        assert cbo["A"] == 1

    def test_swift(self):
        cbo = run_swift("""
            class B {
                var value: Int = 0
            }
            class A {
                var b: B
                init(b: B) { self.b = b }
                func run() { let x = b.value }
            }
        """)
        assert cbo["A"] == 1


# ── Rule 3: bidirectional — used-by also increments CBO ──────────────────────

class TestBidirectionalCoupling:
    """If A uses B, then B.CBO must also reflect the coupling (used-by)."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                fun process() {}
            }
            class A(val b: B) {
                fun run() { b.process() }
            }
        """)
        # A uses B → B.cbo should be 1 (used-by A)
        assert cbo["A"] == 1
        assert cbo["B"] == 1

    def test_swift(self):
        cbo = run_swift("""
            class B {
                func process() {}
            }
            class A {
                var b: B
                init(b: B) { self.b = b }
                func run() { b.process() }
            }
        """)
        assert cbo["A"] == 1
        assert cbo["B"] == 1


# ── Rule 4: multiple accesses to same class = ONE coupling ───────────────────

class TestMultipleAccessesSameClassCountedOnce:
    """A calls b.m1() and b.m2() and accesses b.field → still CBO=1, not 3."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                val score: Int = 0
                fun start() {}
                fun stop() {}
            }
            class A(val b: B) {
                fun run() {
                    b.start()
                    b.stop()
                    val s = b.score
                }
            }
        """)
        assert cbo["A"] == 1

    def test_swift(self):
        cbo = run_swift("""
            class B {
                var score: Int = 0
                func start() {}
                func stop() {}
            }
            class A {
                var b: B
                init(b: B) { self.b = b }
                func run() {
                    b.start()
                    b.stop()
                    let s = b.score
                }
            }
        """)
        assert cbo["A"] == 1


# ── Rule 5a: object instantiation is NOT counted ─────────────────────────────

class TestInstantiationNotCounted:
    """
    `val b = Bar()` / `let b = Bar()` alone must NOT create coupling.
    C&K explicitly excludes object instantiations.
    """

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                fun process() {}
            }
            class A {
                fun run() {
                    val b = B()
                    // never calls any method on b
                }
            }
        """)
        assert cbo["A"] == 0

    def test_swift(self):
        cbo = run_swift("""
            class B {
                func process() {}
            }
            class A {
                func run() {
                    let b = B()
                    // never calls any method on b
                }
            }
        """)
        assert cbo["A"] == 0


# ── Rule 5b: type annotation alone is NOT counted ────────────────────────────

class TestTypeAnnotationAloneNotCounted:
    """
    Declaring a parameter/field of type Bar without ever calling a method
    or accessing an instance variable on it must NOT create coupling.
    C&K: "use of user-defined types … is ignored."
    """

    def test_kotlin(self):
        cbo = run_kotlin("""
            class B {
                fun process() {}
            }
            class A(val b: B) {
                // b is declared but never used
                fun run() {}
            }
        """)
        assert cbo["A"] == 0

    def test_swift(self):
        cbo = run_swift("""
            class B {
                func process() {}
            }
            class A {
                var b: B
                init(b: B) { self.b = b }
                // b is declared but never used after init
                func run() {}
            }
        """)
        assert cbo["A"] == 0


# ── Rule 5c: calls to stdlib / API are NOT counted ───────────────────────────

class TestStdlibNotCounted:
    """Method calls on standard library types (String, List, etc.) are excluded."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class A {
                fun run(): Int {
                    val s = "hello"
                    return s.length
                }
            }
        """)
        assert cbo.get("A", 0) == 0

    def test_swift(self):
        cbo = run_swift("""
            class A {
                func run() -> Int {
                    let s = "hello"
                    return s.count
                }
            }
        """)
        assert cbo.get("A", 0) == 0


# ── Rule 6: class/shared variables NOT counted (only instance vars) ───────────

class TestClassVariablesNotCounted:
    """
    C&K: shared/class variables are excluded from coupling detection.
    Accessing a companion-object val (Kotlin) or static var (Swift) must
    NOT count as coupling via instance-variable access.
    (Method calls on companion/static members still count per C&K.)
    """

    def test_kotlin_companion_val_not_counted(self):
        # B.MAX is a companion object val — not an instance variable
        cbo = run_kotlin("""
            class B {
                companion object {
                    val MAX: Int = 100
                }
            }
            class A {
                fun run(): Int {
                    return B.MAX
                }
            }
        """)
        # B.MAX is static, not an instance field → no coupling
        assert cbo.get("A", 0) == 0

    def test_swift_static_var_not_counted(self):
        # B.max is a static var — not an instance variable
        cbo = run_swift("""
            class B {
                static var max: Int = 100
            }
            class A {
                func run() -> Int {
                    return B.max
                }
            }
        """)
        assert cbo.get("A", 0) == 0


# ── Rule: distinct class count — coupling to N classes = CBO N ───────────────

class TestCBOEqualsDistinctCoupledClasses:
    """CBO counts distinct coupled classes, not total accesses."""

    def test_kotlin_three_classes(self):
        cbo = run_kotlin("""
            class Repo {
                fun find(): Int = 0
            }
            class Logger {
                fun log(msg: String) {}
            }
            class Cache {
                fun get(): Int = 0
            }
            class Service(val repo: Repo, val logger: Logger, val cache: Cache) {
                fun run() {
                    repo.find()
                    logger.log("hi")
                    cache.get()
                }
            }
        """)
        assert cbo["Service"] == 3

    def test_swift_three_classes(self):
        cbo = run_swift("""
            class Repo {
                func find() -> Int { return 0 }
            }
            class Logger {
                func log(msg: String) {}
            }
            class Cache {
                func get() -> Int { return 0 }
            }
            class Service {
                var repo: Repo
                var logger: Logger
                var cache: Cache
                init(repo: Repo, logger: Logger, cache: Cache) {
                    self.repo = repo
                    self.logger = logger
                    self.cache = cache
                }
                func run() {
                    repo.find()
                    logger.log(msg: "hi")
                    cache.get()
                }
            }
        """)
        assert cbo["Service"] == 3


# ── Rule: no coupling between unrelated classes ───────────────────────────────

class TestUnrelatedClassesHaveZeroCBO:
    """Two classes that never interact must both have CBO=0."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class Foo {
                fun doFoo() {}
            }
            class Bar {
                fun doBar() {}
            }
        """)
        assert cbo["Foo"] == 0
        assert cbo["Bar"] == 0

    def test_swift(self):
        cbo = run_swift("""
            class Foo {
                func doFoo() {}
            }
            class Bar {
                func doBar() {}
            }
        """)
        assert cbo["Foo"] == 0
        assert cbo["Bar"] == 0


# ── Rule: self / this calls are NOT counted ───────────────────────────────────

class TestSelfReferenceNotCounted:
    """Calling own methods via self/this must not create coupling to self."""

    def test_kotlin(self):
        cbo = run_kotlin("""
            class A {
                fun helper() {}
                fun run() { this.helper() }
            }
        """)
        assert cbo.get("A", 0) == 0

    def test_swift(self):
        cbo = run_swift("""
            class A {
                func helper() {}
                func run() { self.helper() }
            }
        """)
        assert cbo.get("A", 0) == 0


# ── Multi-file / whole-project tests ─────────────────────────────────────────

class TestMultiFileProject:
    """
    Verify that running the analyzer on a directory works correctly:
      - All files are scanned for class definitions (global symbol table)
      - Cross-file coupling is detected (A in file1 uses B defined in file2)
      - Bidirectional coupling works across files
      - Classes defined in one file are not invisible to another
    """

    def test_kotlin_cross_file_coupling_detected(self):
        """A calls b.process() where B is defined in a separate file → A.CBO=1."""
        cbo = run_kotlin_multifile({
            "B.kt": """
                class B {
                    fun process() {}
                }
            """,
            "A.kt": """
                class A(val b: B) {
                    fun run() { b.process() }
                }
            """,
        })
        assert cbo["A"] == 1

    def test_swift_cross_file_coupling_detected(self):
        """A calls b.process() where B is defined in a separate file → A.CBO=1."""
        cbo = run_swift_multifile({
            "B.swift": """
                class B {
                    func process() {}
                }
            """,
            "A.swift": """
                class A {
                    var b: B
                    init(b: B) { self.b = b }
                    func run() { b.process() }
                }
            """,
        })
        assert cbo["A"] == 1

    def test_kotlin_cross_file_bidirectional(self):
        """Bidirectional coupling works even when A and B are in separate files."""
        cbo = run_kotlin_multifile({
            "B.kt": """
                class B {
                    fun process() {}
                }
            """,
            "A.kt": """
                class A(val b: B) {
                    fun run() { b.process() }
                }
            """,
        })
        assert cbo["A"] == 1
        assert cbo["B"] == 1  # used-by A — bidirectional

    def test_swift_cross_file_bidirectional(self):
        cbo = run_swift_multifile({
            "B.swift": """
                class B {
                    func process() {}
                }
            """,
            "A.swift": """
                class A {
                    var b: B
                    init(b: B) { self.b = b }
                    func run() { b.process() }
                }
            """,
        })
        assert cbo["A"] == 1
        assert cbo["B"] == 1

    def test_kotlin_class_only_in_other_file_not_missed(self):
        """
        If B's member is only known from its own file, it must still appear
        in the symbol table so that A (in another file) can resolve calls to it.
        """
        cbo = run_kotlin_multifile({
            "Repo.kt": """
                class Repo {
                    fun findAll(): Int = 0
                    fun save(id: Int) {}
                }
            """,
            "Service.kt": """
                class Service(val repo: Repo) {
                    fun run() {
                        repo.findAll()
                        repo.save(1)
                    }
                }
            """,
        })
        # Both calls on repo are to Repo → CBO=1 (still just one class)
        assert cbo["Service"] == 1

    def test_swift_class_only_in_other_file_not_missed(self):
        cbo = run_swift_multifile({
            "Repo.swift": """
                class Repo {
                    func findAll() -> Int { return 0 }
                    func save(id: Int) {}
                }
            """,
            "Service.swift": """
                class Service {
                    var repo: Repo
                    init(repo: Repo) { self.repo = repo }
                    func run() {
                        repo.findAll()
                        repo.save(id: 1)
                    }
                }
            """,
        })
        assert cbo["Service"] == 1

    def test_kotlin_three_files_three_couplings(self):
        """Service (file3) uses Repo (file1) and Logger (file2) → CBO=2."""
        cbo = run_kotlin_multifile({
            "Repo.kt": """
                class Repo {
                    fun find(): Int = 0
                }
            """,
            "Logger.kt": """
                class Logger {
                    fun log(msg: String) {}
                }
            """,
            "Service.kt": """
                class Service(val repo: Repo, val logger: Logger) {
                    fun run() {
                        repo.find()
                        logger.log("done")
                    }
                }
            """,
        })
        assert cbo["Service"] == 2

    def test_swift_three_files_three_couplings(self):
        cbo = run_swift_multifile({
            "Repo.swift": """
                class Repo {
                    func find() -> Int { return 0 }
                }
            """,
            "Logger.swift": """
                class Logger {
                    func log(msg: String) {}
                }
            """,
            "Service.swift": """
                class Service {
                    var repo: Repo
                    var logger: Logger
                    init(repo: Repo, logger: Logger) {
                        self.repo = repo
                        self.logger = logger
                    }
                    func run() {
                        repo.find()
                        logger.log(msg: "done")
                    }
                }
            """,
        })
        assert cbo["Service"] == 2

    def test_analyze_public_api_walks_directory(self, tmp_path):
        """
        The public analyze(path) function must recursively find all .kt files
        in a directory, not just a flat list of files handed to it.
        """
        (tmp_path / "B.kt").write_text(textwrap.dedent("""
            class B {
                fun process() {}
            }
        """))
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "A.kt").write_text(textwrap.dedent("""
            class A(val b: B) {
                fun run() { b.process() }
            }
        """))
        cbo = run_dir(tmp_path, "kotlin")
        assert cbo["A"] == 1
        assert cbo["B"] == 1
