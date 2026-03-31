"""
CBO (Coupling Between Object Classes) Analyzer — Strict Chidamber & Kemerer Definition
========================================================================================

C&K Definition (Chidamber & Kemerer, 1994):
  CBO = number of *other* classes to which a class is coupled.
  Two classes are coupled when methods declared in one class use methods or
  instance variables *defined* by the other class.

What IS counted (per C&K):
  • Method/function call expressions on an object of another class
  • Instance variable / property accesses on an object of another class

What is NOT counted (per C&K):
  • Inheritance / protocol conformance
  • Type annotations (parameter types, return types, field type declarations)
  • Object instantiation / constructor calls   ← explicitly excluded by C&K
  • Use of constants
  • Calls to standard library / API

Important nuances implemented:
  • Multiple calls/accesses to the same class count as ONE coupling (dedup per pair)
  • Only instance variables are counted; class/static variables are not (C&K spec)
  • All method calls are counted, both instance and static (C&K spec)
  • Bidirectional: if A is coupled to B, A.cbo++ AND B.cbo++ (each counted once)
  • Threshold: CBO > 14 is considered too high (Sahraoui, Godin & Miceli)

AST Strategy
------------
We need to know the *declared type* of a receiver to determine which class a
call/access targets. Full type inference requires a type-checker, which tree-sitter
does not provide. We therefore use a two-pass approach:

  Pass 1 — collect all class declarations and their members (methods + fields)
            from across the entire file set, building a global symbol table:
            {class_name -> {method_names}, {field_names}}

  Pass 2 — for each class body, walk call_expressions and navigation_expressions.
            Resolve the receiver's type by looking up the receiver identifier
            in the current scope's variable→type map (built from constructor
            parameters and field declarations within the class).
            If receiver_type is found in the symbol table and the called
            member is declared in that class → record coupling.

This gives us genuine C&K coupling (based on actual class membership) rather
than a heuristic. It won't handle complex chains (a.b().c) or generics fully,
but covers the dominant patterns in real code.

Usage (CLI):
    python cbo_analyzer.py path/to/file_or_dir [--lang kotlin|swift|auto]
    python cbo_analyzer.py src/ --csv report.csv
    python cbo_analyzer.py src/ --threshold 14   # flag only C&K-too-high classes

Programmatic:
    from cbo_analyzer import analyze
    results = analyze("src/", language="kotlin")

Dependencies:
    pip install tree-sitter tree-sitter-kotlin tree-sitter-swift
"""

from __future__ import annotations

import sys
import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path
from tree_sitter import Language, Parser



def _load_kotlin_parser() -> Parser:
    try:
        from tree_sitter_kotlin import language as kotlin_language
        return Parser(Language(kotlin_language()))
    except ImportError:
        sys.exit("[ERROR] tree-sitter-kotlin not installed. Run: pip install tree-sitter-kotlin")


def _load_swift_parser() -> Parser:
    try:
        from tree_sitter_swift import language as swift_language
        return Parser(Language(swift_language()))
    except ImportError:
        sys.exit("[ERROR] tree-sitter-swift not installed. Run: pip install tree-sitter-swift")


# ── Standard library / platform primitives (never counted as user classes) ─

KOTLIN_STDLIB = {
    "Int", "Long", "Short", "Byte", "Double", "Float", "Boolean", "Char",
    "String", "Unit", "Any", "Nothing", "Number", "Void",
    "List", "MutableList", "Set", "MutableSet", "Map", "MutableMap",
    "Collection", "MutableCollection", "Iterable", "Sequence",
    "Array", "Pair", "Triple", "Result", "Lazy",
    "Exception", "Error", "Throwable", "RuntimeException",
    # kotlin.* builtins
    "println", "print", "TODO", "require", "check", "error", "also",
    "let", "run", "apply", "with", "repeat", "forEach",
}

SWIFT_STDLIB = {
    "Int", "Int8", "Int16", "Int32", "Int64",
    "UInt", "UInt8", "UInt16", "UInt32", "UInt64",
    "Float", "Double", "Bool", "Character", "String",
    "Void", "Never", "Any", "AnyObject",
    "Optional", "Array", "Dictionary", "Set",
    "Error", "NSError",
    "print", "fatalError", "precondition", "assert", "debugPrint",
    # Swift standard protocols (conformance-only, not coupled)
    "Comparable", "Equatable", "Hashable", "Codable", "Identifiable",
    "Sendable", "CustomStringConvertible",
}


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class MemberTable:
    """All methods and instance fields declared in a class."""
    methods: set[str] = field(default_factory=set)
    # instance fields only (no class/static vars, per C&K)
    instance_fields: set[str] = field(default_factory=set)

    def has_member(self, name: str) -> bool:
        return name in self.methods or name in self.instance_fields


@dataclass
class CouplingEvidence:
    """Records *why* a coupling was detected (for reporting)."""
    target_class: str
    accesses: list[str] = field(default_factory=list)   # member names accessed

    def add(self, member: str):
        if member not in self.accesses:
            self.accesses.append(member)


@dataclass
class ClassCBO:
    name: str
    language: str
    file: str
    # target_class_name -> CouplingEvidence
    couplings: dict[str, CouplingEvidence] = field(default_factory=dict)

    @property
    def cbo(self) -> int:
        return len(self.couplings)

    def add_coupling(self, target: str, member: str):
        if target == self.name:
            return
        if target not in self.couplings:
            self.couplings[target] = CouplingEvidence(target_class=target)
        self.couplings[target].add(member)


@dataclass
class AnalysisResult:
    file: str
    language: str
    classes: list[ClassCBO] = field(default_factory=list)

    @property
    def total_cbo(self) -> int:
        return sum(c.cbo for c in self.classes)

    @property
    def average_cbo(self) -> float:
        return self.total_cbo / len(self.classes) if self.classes else 0.0


# ── AST helpers (shared) ────────────────────────────────────────────────────

def get_text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def first_child_of_type(node, *types):
    for child in node.children:
        if child.type in types:
            return child
    return None


def children_of_type(node, *types):
    return [c for c in node.children if c.type in types]


def walk(node):
    """Depth-first generator over all nodes."""
    yield node
    for child in node.children:
        yield from walk(child)


def walk_skip_classes(node, class_node_types: set):
    """Depth-first walk that does NOT descend into nested class declarations."""
    yield node
    for child in node.children:
        if child.type not in class_node_types:
            yield from walk_skip_classes(child, class_node_types)


# ══════════════════════════════════════════════════════════════════════════════
#  KOTLIN ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class KotlinCBOAnalyzer:
    """
    Kotlin tree-sitter node types used:
      class_declaration          — class / interface / object / enum
      function_declaration       — fun foo(...)
      property_declaration       — val / var
      primary_constructor        — class Foo(val x: Bar)
      class_parameter            — individual constructor parameter
      call_expression            — foo.bar(...)  or  bar(...)
      navigation_expression      — foo.bar  (field/method access)
      simple_identifier          — leaf identifier
      type_reference             — e.g. `: UserRepository`
      variable_declaration       — LHS of val/var
      value_argument             — arguments inside call
    """

    STDLIB = KOTLIN_STDLIB

    # Node types that introduce a new class scope
    CLASS_NODES = {"class_declaration", "object_declaration", "interface_declaration"}

    def __init__(self):
        self._parser = _load_kotlin_parser()

    def analyze_files(self, files: list[Path]) -> list[AnalysisResult]:
        # Parse all files first
        parsed: list[tuple[Path, object, bytes]] = []
        for fp in files:
            src = fp.read_bytes()
            tree = self._parser.parse(src)
            parsed.append((fp, tree.root_node, src))

        # Pass 1: build global symbol table across all files
        symbol_table: dict[str, MemberTable] = {}
        for fp, root, src in parsed:
            self._collect_symbols(root, src, symbol_table)

        # Pass 2: compute CBO per class per file
        all_results: list[AnalysisResult] = []
        for fp, root, src in parsed:
            result = AnalysisResult(file=str(fp), language="kotlin")
            self._compute_cbo(root, src, symbol_table, result)
            all_results.append(result)

        # Pass 3: apply bidirectional coupling
        _apply_bidirectional(all_results)

        return all_results

    # ── Pass 1: symbol collection ──────────────────────────────────────────

    def _collect_symbols(self, root, src: bytes, table: dict[str, MemberTable]):
        for node in walk(root):
            if node.type in self.CLASS_NODES:
                # Kotlin uses "identifier" for class names (not "type_identifier")
                name_node = first_child_of_type(node, "identifier")
                if not name_node:
                    continue
                class_name = get_text(name_node, src)
                if class_name not in table:
                    table[class_name] = MemberTable()
                mt = table[class_name]

                # Constructor parameters  →  instance fields
                # primary_constructor is a direct child of class_declaration;
                # walk(node) would wrongly descend into nested classes.
                for ctor in node.children:
                    if ctor.type == "primary_constructor":
                        for param in walk(ctor):
                            if param.type == "class_parameter":
                                # Only val/var params become fields
                                has_val_var = any(
                                    c.type in ("val", "var") for c in param.children
                                )
                                if has_val_var:
                                    id_node = first_child_of_type(
                                        param, "identifier"
                                    )
                                    if id_node:
                                        mt.instance_fields.add(
                                            get_text(id_node, src)
                                        )

                # Body: property_declarations and function_declarations
                body = first_child_of_type(node, "class_body")
                if not body:
                    continue
                for child in body.children:
                    if child.type == "property_declaration":
                        # Only non-companion, non-const = instance field
                        if not _kotlin_is_static(child, src):
                            vd = first_child_of_type(child, "variable_declaration")
                            if vd:
                                id_node = first_child_of_type(
                                    vd, "identifier"
                                )
                                if id_node:
                                    mt.instance_fields.add(
                                        get_text(id_node, src)
                                    )
                    elif child.type == "function_declaration":
                        fn_name = first_child_of_type(child, "identifier")
                        if fn_name:
                            mt.methods.add(get_text(fn_name, src))

    # ── Pass 2: CBO computation ────────────────────────────────────────────

    def _compute_cbo(
        self,
        root,
        src: bytes,
        symbol_table: dict[str, MemberTable],
        result: AnalysisResult,
    ):
        for node in walk(root):
            if node.type in self.CLASS_NODES:
                name_node = first_child_of_type(node, "identifier")
                if not name_node:
                    continue
                class_name = get_text(name_node, src)
                entry = ClassCBO(
                    name=class_name, language="kotlin", file=result.file
                )

                # Build local scope: identifier → declared type
                scope = self._build_scope(node, src)

                # Walk the class body for call/navigation expressions
                body = first_child_of_type(node, "class_body")
                if body:
                    self._scan_calls(body, src, scope, symbol_table, entry)

                result.classes.append(entry)

    def _build_scope(self, class_node, src: bytes) -> dict[str, str]:
        """
        Map local identifier → class name for all:
          - constructor parameters  (val/var and plain)
          - property declarations
          - local val/var declarations inside function bodies
        Returns dict {identifier: TypeName}
        """
        scope: dict[str, str] = {}

        for node in walk_skip_classes(class_node, self.CLASS_NODES):
            # Constructor params: val repo: UserRepository
            if node.type == "class_parameter":
                id_node = first_child_of_type(node, "identifier")
                type_node = _kotlin_extract_type(node)
                if id_node and type_node:
                    scope[get_text(id_node, src)] = get_text(type_node, src).strip("?")

            # Property declarations: val repo: UserRepository = ...
            elif node.type == "property_declaration":
                vd = first_child_of_type(node, "variable_declaration")
                if vd:
                    id_node = first_child_of_type(vd, "identifier")
                    type_node = _kotlin_extract_type(node)
                    if id_node and type_node:
                        scope[get_text(id_node, src)] = get_text(type_node, src).strip("?")

        return scope

    def _scan_calls(
        self,
        body,
        src: bytes,
        scope: dict[str, str],
        symbol_table: dict[str, MemberTable],
        entry: ClassCBO,
    ):
        """
        Walk body for:
          call_expression      — receiver.method(args)
          navigation_expression — receiver.field
        and record couplings when receiver type is a known user class.
        """
        # We also track local val/var inside functions to extend scope
        local_scope = dict(scope)

        for node in walk_skip_classes(body, self.CLASS_NODES):
            # Local variable type annotations inside function bodies
            if node.type == "property_declaration":
                vd = first_child_of_type(node, "variable_declaration")
                if vd:
                    id_node = first_child_of_type(vd, "identifier")
                    type_node = _kotlin_extract_type(node)
                    if id_node and type_node:
                        local_scope[get_text(id_node, src)] = (
                            get_text(type_node, src).strip("?")
                        )

            # navigation_expression: covers both  foo.bar  and  foo.bar(...)
            # tree-sitter-kotlin actual structure:
            #   navigation_expression
            #     identifier   ← receiver
            #     "."
            #     identifier   ← member name   (NO navigation_suffix!)
            elif node.type == "navigation_expression":
                self._process_navigation(
                    node, src, local_scope, symbol_table, entry
                )

    def _process_navigation(
        self, node, src, scope, symbol_table, entry: ClassCBO
    ):
        # Kotlin navigation_expression: identifier  "."  identifier
        non_dot = [c for c in node.children if c.type != "."]
        if len(non_dot) < 2:
            return
        receiver_node = non_dot[0]
        member_node = non_dot[-1]

        if member_node.type != "identifier":
            return
        member_name = get_text(member_node, src)

        # Resolve receiver type
        receiver_type = _resolve_receiver_type(receiver_node, src, scope)
        if not receiver_type:
            return

        # Is this a known user class (not stdlib)?
        if receiver_type in self.STDLIB:
            return
        if receiver_type not in symbol_table:
            return  # unknown class — skip to avoid false positives

        mt = symbol_table[receiver_type]
        if mt.has_member(member_name):
            entry.add_coupling(receiver_type, member_name)


# ── Kotlin helpers ──────────────────────────────────────────────────────────

def _kotlin_extract_type(node):
    """
    Return the identifier node whose text is the declared type name.

    Actual tree-sitter-kotlin structures observed:
      property_declaration
        variable_declaration
          identifier  (var name)
          user_type
            identifier  (type name)  ← return this
      class_parameter
        identifier  (param name)
        user_type
          identifier  (type name)    ← return this
    """
    # property_declaration → variable_declaration → user_type → identifier
    for child in node.children:
        if child.type == "variable_declaration":
            for vd_child in child.children:
                if vd_child.type == "user_type":
                    return first_child_of_type(vd_child, "identifier") or vd_child
    # class_parameter → user_type → identifier  (direct child)
    for child in node.children:
        if child.type == "user_type":
            return first_child_of_type(child, "identifier") or child
    return None


def _kotlin_is_static(prop_node, src: bytes) -> bool:
    """Returns True if property is inside a companion object (= static)."""
    parent = prop_node.parent
    while parent:
        if parent.type == "companion_object":
            return True
        parent = parent.parent
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  SWIFT ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class SwiftCBOAnalyzer:
    """
    Swift tree-sitter node types used (tree-sitter-swift grammar):
      class_declaration          — class Foo
      struct_declaration         — struct Foo
      enum_declaration           — enum Foo
      protocol_declaration       — protocol Foo
      actor_declaration          — actor Foo
      function_declaration       — func foo(...)
      property_declaration       — var/let foo: Bar  (NOT variable_declaration)
      init_declaration           — init(...)
      parameter                  — individual function parameter
      call_expression            — foo.bar(...)
      navigation_expression      — foo.bar
      simple_identifier          — leaf identifier
      type_annotation            — : SomeType
      optional_type              — SomeType?
    """

    STDLIB = SWIFT_STDLIB

    CLASS_NODES = {
        "class_declaration",
        "struct_declaration",
        "enum_declaration",
        "protocol_declaration",
        "actor_declaration",
    }

    def __init__(self):
        self._parser = _load_swift_parser()

    def analyze_files(self, files: list[Path]) -> list[AnalysisResult]:
        parsed: list[tuple[Path, object, bytes]] = []
        for fp in files:
            src = fp.read_bytes()
            tree = self._parser.parse(src)
            parsed.append((fp, tree.root_node, src))

        # Pass 1
        symbol_table: dict[str, MemberTable] = {}
        for fp, root, src in parsed:
            self._collect_symbols(root, src, symbol_table)

        # Pass 2
        all_results: list[AnalysisResult] = []
        for fp, root, src in parsed:
            result = AnalysisResult(file=str(fp), language="swift")
            self._compute_cbo(root, src, symbol_table, result)
            all_results.append(result)

        # Pass 3
        _apply_bidirectional(all_results)

        return all_results

    # ── Pass 1 ─────────────────────────────────────────────────────────────

    def _collect_symbols(self, root, src: bytes, table: dict[str, MemberTable]):
        for node in walk(root):
            if node.type in self.CLASS_NODES:
                name_node = first_child_of_type(node, "type_identifier", "simple_identifier")
                if not name_node:
                    continue
                class_name = get_text(name_node, src)
                if class_name not in table:
                    table[class_name] = MemberTable()
                mt = table[class_name]

                body = first_child_of_type(node, "class_body", "enum_class_body")
                if not body:
                    continue

                for child in walk_skip_classes(body, self.CLASS_NODES):
                    if child.type == "function_declaration":
                        fn_name = first_child_of_type(child, "simple_identifier")
                        if fn_name:
                            mt.methods.add(get_text(fn_name, src))

                    elif child.type == "property_declaration":
                        # Only instance stored properties (no static/class)
                        # Swift structure: property_declaration > pattern > simple_identifier
                        if not _swift_is_static(child, src):
                            for pat in walk(child):
                                if pat.type == "pattern":
                                    id_node = first_child_of_type(
                                        pat, "simple_identifier"
                                    )
                                    if id_node:
                                        mt.instance_fields.add(
                                            get_text(id_node, src)
                                        )

    # ── Pass 2 ─────────────────────────────────────────────────────────────

    def _compute_cbo(self, root, src, symbol_table, result: AnalysisResult):
        for node in walk(root):
            if node.type in self.CLASS_NODES:
                name_node = first_child_of_type(
                    node, "type_identifier", "simple_identifier"
                )
                if not name_node:
                    continue
                class_name = get_text(name_node, src)
                entry = ClassCBO(
                    name=class_name, language="swift", file=result.file
                )
                scope = self._build_scope(node, src)
                body = first_child_of_type(node, "class_body", "enum_class_body")
                if body:
                    self._scan_calls(body, src, scope, symbol_table, entry)
                result.classes.append(entry)

    def _build_scope(self, class_node, src: bytes) -> dict[str, str]:
        scope: dict[str, str] = {}
        for node in walk_skip_classes(class_node, self.CLASS_NODES):
            # init parameters: init(repo: UserRepository)
            if node.type == "parameter":
                id_node = first_child_of_type(node, "simple_identifier")
                type_node = _swift_extract_type(node, src)
                if id_node and type_node:
                    scope[get_text(id_node, src)] = type_node

            # Stored properties: var repo: UserRepository
            # Swift structure: property_declaration > pattern > simple_identifier
            elif node.type == "property_declaration":
                for pat in walk(node):
                    if pat.type == "pattern":
                        id_node = first_child_of_type(pat, "simple_identifier")
                        type_node = _swift_extract_type(node, src)
                        if id_node and type_node:
                            scope[get_text(id_node, src)] = type_node
                            break  # one name per declaration

        return scope

    def _scan_calls(self, body, src, scope, symbol_table, entry: ClassCBO):
        local_scope = dict(scope)

        for node in walk_skip_classes(body, self.CLASS_NODES):
            # Local let/var inside functions
            # Swift structure: property_declaration > pattern > simple_identifier
            if node.type == "property_declaration":
                for pat in walk(node):
                    if pat.type == "pattern":
                        id_node = first_child_of_type(pat, "simple_identifier")
                        type_node = _swift_extract_type(node, src)
                        if id_node and type_node:
                            local_scope[get_text(id_node, src)] = type_node
                            break

            elif node.type == "navigation_expression":
                self._process_navigation(
                    node, src, local_scope, symbol_table, entry
                )

    def _process_navigation(self, node, src, scope, symbol_table, entry):
        # Swift navigation_expression actual structure:
        #   navigation_expression
        #     <receiver_expr>          ← simple_identifier or nested expr
        #     navigation_suffix
        #       "."
        #       simple_identifier      ← member name
        receiver_node = None
        member_name = None
        for child in node.children:
            if child.type == "navigation_suffix":
                m = first_child_of_type(child, "simple_identifier")
                if m:
                    member_name = get_text(m, src)
            elif child.type not in (".", "?."):
                receiver_node = child

        if not receiver_node or not member_name:
            return

        receiver_type = _resolve_receiver_type(receiver_node, src, scope)
        if not receiver_type:
            return
        if receiver_type in self.STDLIB:
            return
        if receiver_type not in symbol_table:
            return

        mt = symbol_table[receiver_type]
        if mt.has_member(member_name):
            entry.add_coupling(receiver_type, member_name)


# ── Swift helpers ───────────────────────────────────────────────────────────

def _swift_extract_type(node, src: bytes) -> str | None:
    """
    Find the declared type from a variable_declaration or parameter node.
    Handles: plain type, optional type (Foo?), array type ([Foo]).
    """
    for child in node.children:
        if child.type == "type_annotation":
            # type_annotation → ":" → <type_node>
            for tc in child.children:
                if tc.type in ("user_type", "type_identifier", "simple_type_identifier"):
                    return get_text(tc, src).rstrip("?!")
                if tc.type == "optional_type":
                    inner = first_child_of_type(
                        tc, "user_type", "type_identifier", "simple_type_identifier"
                    )
                    if inner:
                        return get_text(inner, src).rstrip("?!")
    return None


def _swift_is_static(node, src: bytes) -> bool:
    """Returns True if property has static or class modifier."""
    parent = node.parent
    while parent:
        if parent.type in ("class_declaration", "struct_declaration"):
            break
        parent = parent.parent
    # Check modifiers on the declaration node
    for child in node.children:
        if child.type == "modifiers":
            text = get_text(child, src)
            if "static" in text or "class " in text:
                return True
    return False


# ── Shared receiver-type resolution ────────────────────────────────────────

def _resolve_receiver_type(receiver_node, src: bytes, scope: dict[str, str]) -> str | None:
    """
    Best-effort: given a receiver AST node, return the class name of its type.

    Handles:
      simple_identifier              → look up in scope
      self / this                    → skip (coupling to own class, not counted)
      navigation_expression (chain)  → recursively resolve outermost
    """
    ntype = receiver_node.type

    # Swift uses "simple_identifier"; Kotlin uses "identifier"
    if ntype in ("simple_identifier", "identifier"):
        name = get_text(receiver_node, src)
        if name in ("self", "this", "super"):
            return None
        return scope.get(name)

    if ntype == "navigation_expression":
        # For chained access a.b.c(), try to resolve the root
        children = [c for c in receiver_node.children if c.type not in (".", "?.")]
        if children:
            return _resolve_receiver_type(children[0], src, scope)

    # call_expression result type — would need full type inference; skip
    return None


# ── Bidirectional coupling (Pass 3) ────────────────────────────────────────

def _apply_bidirectional(all_results: list[AnalysisResult]):
    """
    C&K: "uses relationship can go either way — both uses and used-by
    relationships are taken into account, but only once."

    Build a reverse index so that if class A is coupled to class B,
    class B also records a coupling to A (for its own CBO count).
    """
    # index: class_name → ClassCBO object
    index: dict[str, ClassCBO] = {}
    for result in all_results:
        for cls in result.classes:
            index[cls.name] = cls

    # collect all (A→B, evidence) pairs first, then add B→A
    pairs: list[tuple[str, str, list[str]]] = []
    for cls in index.values():
        for target, evidence in cls.couplings.items():
            pairs.append((cls.name, target, evidence.accesses))

    for src_name, tgt_name, accesses in pairs:
        if tgt_name in index:
            tgt_cls = index[tgt_name]
            # Add reverse coupling if not already present
            if src_name not in tgt_cls.couplings:
                for member in accesses:
                    tgt_cls.add_coupling(src_name, f"used-by:{member}")


# ══════════════════════════════════════════════════════════════════════════════
#  File dispatcher
# ══════════════════════════════════════════════════════════════════════════════

def _detect_lang(path: Path) -> str | None:
    if path.suffix in (".kt", ".kts"):
        return "kotlin"
    if path.suffix == ".swift":
        return "swift"
    return None


def analyze(path: str, language: str | None = None) -> list[AnalysisResult]:
    """
    Public API.

    Args:
        path:     File or directory path.
        language: 'kotlin', 'swift', or None (auto-detect).

    Returns:
        List of AnalysisResult, one per source file.
    """
    p = Path(path)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        files = sorted(p.rglob("*.kt")) + sorted(p.rglob("*.kts")) + sorted(p.rglob("*.swift"))
    else:
        print(f"[ERROR] Path not found: {path}", file=sys.stderr)
        return []

    kotlin_files = [f for f in files if _detect_lang(f) == "kotlin"]
    swift_files  = [f for f in files if _detect_lang(f) == "swift"]

    if language == "kotlin":
        swift_files = []
    elif language == "swift":
        kotlin_files = []

    results: list[AnalysisResult] = []
    if kotlin_files:
        results += KotlinCBOAnalyzer().analyze_files(kotlin_files)
    if swift_files:
        results += SwiftCBOAnalyzer().analyze_files(swift_files)
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Reporting
# ══════════════════════════════════════════════════════════════════════════════

# C&K threshold: CBO > 14 is "too high" (Sahraoui, Godin & Miceli)
CBO_HIGH = 14
CBO_WARN = 7


def _level(cbo: int) -> str:
    if cbo > CBO_HIGH:
        return "HIGH"
    if cbo > CBO_WARN:
        return "MEDIUM"
    return "LOW"


def _icon(cbo: int) -> str:
    if cbo > CBO_HIGH:
        return "ERR"
    if cbo > CBO_WARN:
        return "WRN"
    return " OK"


def print_report(results: list[AnalysisResult]):
    if not results:
        print("No classes found.")
        return

    all_classes = [cls for r in results for cls in r.classes]

    print()
    print("=" * 72)
    print("  CBO ANALYSIS REPORT  [Strict Chidamber & Kemerer, 1994]")
    print("  Counting: method calls + field accesses on other classes only")
    print("  Threshold: LOW ≤7 | MEDIUM 8–14 | HIGH >14  (Sahraoui et al.)")
    print("=" * 72)

    for r in results:
        if not r.classes:
            continue
        print(f"\n  File : {r.file}")
        print(
            f"  Lang : {r.language}  |  Classes: {len(r.classes)}"
            f"  |  Total CBO: {r.total_cbo}  |  Avg CBO: {r.average_cbo:.1f}"
        )

        for cls in sorted(r.classes, key=lambda c: c.cbo, reverse=True):
            icon = _icon(cls.cbo)
            print(f"\n  [{icon}] {cls.name}  —  CBO = {cls.cbo}  ({_level(cls.cbo)})")
            if cls.couplings:
                for tname, ev in sorted(cls.couplings.items()):
                    members = ", ".join(ev.accesses[:5])
                    more = f" +{len(ev.accesses)-5} more" if len(ev.accesses) > 5 else ""
                    print(f"        • {tname:<34} via: {members}{more}")
            else:
                print("        (no external couplings detected)")

    print()
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  {'Class':<34} {'File':<22} {'CBO':>4}  Level")
    print(f"  {'-'*34} {'-'*22} {'-'*4}  {'-'*8}")
    for cls in sorted(all_classes, key=lambda c: c.cbo, reverse=True):
        fname = Path(cls.file).name
        print(f"  {cls.name:<34} {fname:<22} {cls.cbo:>4}  {_level(cls.cbo)}")

    n  = len(all_classes)
    avg = sum(c.cbo for c in all_classes) / n if n else 0
    n_low  = sum(1 for c in all_classes if c.cbo <= CBO_WARN)
    n_med  = sum(1 for c in all_classes if CBO_WARN < c.cbo <= CBO_HIGH)
    n_high = sum(1 for c in all_classes if c.cbo > CBO_HIGH)

    print()
    print(f"  Total classes : {n}")
    print(f"  Average CBO   : {avg:.2f}")
    print(f"  LOW   (≤7)    : {n_low}")
    print(f"  MEDIUM (8–14) : {n_med}")
    print(f"  HIGH  (>14)   : {n_high}  ← C&K fault-prone threshold")
    print("=" * 72)
    print()


def export_csv(results: list[AnalysisResult], out_path: str):
    rows = []
    for r in results:
        for cls in r.classes:
            coupled = "; ".join(
                f"{t}({','.join(ev.accesses)})"
                for t, ev in sorted(cls.couplings.items())
            )
            rows.append({
                "file": r.file,
                "language": r.language,
                "class": cls.name,
                "cbo": cls.cbo,
                "level": _level(cls.cbo),
                "coupled_classes": coupled,
            })
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["file","language","class","cbo","level","coupled_classes"]
        )
        w.writeheader()
        w.writerows(rows)
    print(f"  CSV → {out_path}")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _build_parser():
    p = argparse.ArgumentParser(
        description="Strict C&K CBO Analyzer for Kotlin and Swift (tree-sitter).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cbo_analyzer.py MyClass.kt
  python cbo_analyzer.py src/ --lang kotlin
  python cbo_analyzer.py src/ --lang swift --csv report.csv
  python cbo_analyzer.py src/ --threshold 14
        """,
    )
    p.add_argument("path", help="Source file or directory")
    p.add_argument("--lang", choices=["kotlin","swift","auto"], default="auto")
    p.add_argument("--csv", metavar="FILE")
    p.add_argument(
        "--threshold", type=int, default=None,
        help="Only report classes with CBO >= threshold"
    )
    return p


def main():
    args = _build_parser().parse_args()
    lang = None if args.lang == "auto" else args.lang
    results = analyze(args.path, lang)

    if not results:
        print("No source files found.")
        sys.exit(1)

    if args.threshold is not None:
        for r in results:
            r.classes = [c for c in r.classes if c.cbo >= args.threshold]
        results = [r for r in results if r.classes]

    print_report(results)

    if args.csv:
        export_csv(results, args.csv)


if __name__ == "__main__":
    main()