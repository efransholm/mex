from tree_sitter import Language, Parser
from dataclasses import dataclass, field
from typing import List, Tuple

SWIFT_LANGUAGE = Language('build/my-languages.so', 'swift')

parser = Parser()
parser.set_language(SWIFT_LANGUAGE)

# ── Debug helper ────────────────────────────────────────────────────────────
# If you get 0s on everything, run this first to see the real node types:
#
#   python3 debug_swift.py your_file.swift
#
# A ready-made debug script is at the bottom of this file (see __main__).
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class StateMetrics:
    mutable_vars: int = 0
    immutable_vars: int = 0
    observable_state_vars: int = 0
    state_updates: int = 0
    mutable_var_names: List[str] = field(default_factory=list)
    immutable_var_names: List[str] = field(default_factory=list)
    observable_var_names: List[str] = field(default_factory=list)
    state_update_lines: List[Tuple[int, str]] = field(default_factory=list)


def parse_swift_file(file_path: str):
    with open(file_path, 'r', encoding='utf-8') as f:
        code = f.read().encode()
    tree = parser.parse(code)
    return tree.root_node, code


def get_text(node, code_bytes: bytes) -> str:
    return code_bytes[node.start_byte:node.end_byte].decode('utf-8')


def first_child_of_type(node, *types):
    for child in node.children:
        if child.type in types:
            return child
    return None


def all_children_of_type(node, *types):
    return [c for c in node.children if c.type in types]


# Observable / reactive patterns used in Swift / SwiftUI / Combine
OBSERVABLE_PATTERNS = [
    # SwiftUI property wrappers (source text will contain the wrapper name)
    '@State', '@StateObject', '@ObservedObject', '@Published',
    '@Binding', '@EnvironmentObject', '@Environment',
    # Combine
    'CurrentValueSubject', 'PassthroughSubject',
    # ObservableObject / @Observable (Swift 5.9 macro)
    '@Observable',
    # Common reactive helpers
    'MutableLiveData', 'LiveData',
]

REACTIVE_CALL_PATTERNS = [
    '.send(', '.value =', '.toggle(', '.append(', '.remove(',
    '.insert(', '.removeAll(', '.removeFirst(', '.removeLast(',
    '.sort(', '.shuffle(', '.reverse(',
]


def walk_ast(node, code_bytes: bytes, metrics: StateMetrics):
    """Recursively walk the Swift AST and collect state metrics.

    The tree-sitter-swift grammar uses these key node types:
      property_declaration  – stored properties (var / let at class/struct level)
      value_binding_pattern – contains the 'var' or 'let' keyword
      pattern              – holds the identifier (variable name)
      local_variable_declaration / variable_declaration – inside function bodies
      assignment           – `a = b` or `a.field = b`
      call_expression      – function / method calls
    """

    # ── STORED PROPERTIES (class / struct / extension body) ─────────────────
    if node.type == 'property_declaration':
        _handle_property(node, code_bytes, metrics)

    # ── LOCAL VARIABLE DECLARATIONS (inside function bodies) ────────────────
    elif node.type in ('local_variable_declaration', 'variable_declaration'):
        _handle_property(node, code_bytes, metrics)

    # ── ASSIGNMENTS ──────────────────────────────────────────────────────────
    elif node.type == 'assignment':
        start_line = node.start_point[0] + 1
        node_text = get_text(node, code_bytes)

        lhs_node = node.children[0] if node.children else None
        if lhs_node:
            lhs_text = get_text(lhs_node, code_bytes)
            all_tracked = set(metrics.mutable_var_names + metrics.observable_var_names)
            matched = any(
                lhs_text == name or lhs_text.startswith(name + '.')
                for name in all_tracked
            )
            if matched:
                metrics.state_updates += 1
                metrics.state_update_lines.append((start_line, node_text))

    # ── REACTIVE / MUTATING METHOD CALLS ────────────────────────────────────
    elif node.type == 'call_expression':
        start_line = node.start_point[0] + 1
        call_text = get_text(node, code_bytes)
        if any(pat in call_text for pat in REACTIVE_CALL_PATTERNS):
            metrics.state_updates += 1
            metrics.state_update_lines.append((start_line, call_text))

    # Recurse
    for child in node.children:
        walk_ast(child, code_bytes, metrics)


def _handle_property(node, code_bytes: bytes, metrics: StateMetrics):
    """Extract mutability, name, and observable status from a (local) variable
    declaration node.

    The tree-sitter-swift grammar wraps var/let inside a
    `value_binding_pattern` node whose first child is the keyword token.
    The variable name lives in a `pattern` → `simple_identifier` subtree, or
    sometimes directly as a `simple_identifier` child of the declaration.
    """

    # ── 1. Find var / let keyword ────────────────────────────────────────────
    keyword = None

    # Preferred path: value_binding_pattern → (var|let)
    vbp = first_child_of_type(node, 'value_binding_pattern')
    if vbp:
        kw = first_child_of_type(vbp, 'var', 'let')
        if kw:
            keyword = kw.type
    # Fallback: keyword is a direct child of the declaration node
    if keyword is None:
        kw = first_child_of_type(node, 'var', 'let')
        if kw:
            keyword = kw.type

    if keyword is None:
        return  # not a var/let declaration we recognise

    # ── 2. Find variable name ────────────────────────────────────────────────
    var_name = None

    # Walk looking for pattern → simple_identifier, or bare simple_identifier
    for child in node.children:
        if child.type == 'pattern':
            si = first_child_of_type(child, 'simple_identifier')
            if si:
                var_name = get_text(si, code_bytes)
                break
        if child.type == 'simple_identifier' and var_name is None:
            var_name = get_text(child, code_bytes)

    if var_name is None:
        return

    # ── 3. Record mutability ─────────────────────────────────────────────────
    if keyword == 'var':
        metrics.mutable_vars += 1
        metrics.mutable_var_names.append(var_name)
    else:
        metrics.immutable_vars += 1
        metrics.immutable_var_names.append(var_name)

    # ── 4. Check for observable / reactive annotations / initializers ────────
    # The full declaration text includes property-wrapper attributes like
    # @State, @Published, etc. that appear before the var/let keyword.
    full_text = get_text(node, code_bytes)

    # Also collect any initializer text (after `=`)
    init_text = ''
    eq_seen = False
    for child in node.children:
        if child.type == '=':
            eq_seen = True
            continue
        if eq_seen:
            init_text = get_text(child, code_bytes)
            break

    combined = full_text + ' ' + init_text
    if any(pat in combined for pat in OBSERVABLE_PATTERNS):
        metrics.observable_state_vars += 1
        if var_name not in metrics.observable_var_names:
            metrics.observable_var_names.append(var_name)


def analyze_swift_file(file_path: str) -> StateMetrics:
    root_node, code_bytes = parse_swift_file(file_path)
    metrics = StateMetrics()
    walk_ast(root_node, code_bytes, metrics)
    return metrics


# ── AST debug helper ─────────────────────────────────────────────────────────
def dump_ast(file_path: str):
    """Print the full AST so you can verify node/field names.
    Run as:  python3 swift_analyzer.py --dump your_file.swift
    """
    root_node, code_bytes = parse_swift_file(file_path)

    def _dump(node, indent=0):
        snippet = get_text(node, code_bytes).replace('\n', '↵')[:60]
        print(' ' * indent + f"[{node.type}] {repr(snippet)}")
        for child in node.children:
            _dump(child, indent + 2)

    _dump(root_node)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python swift_analyzer.py <Swift file>")
        print("       python swift_analyzer.py --dump <Swift file>  (show AST)")
        sys.exit(1)

    if sys.argv[1] == '--dump':
        if len(sys.argv) < 3:
            print("Usage: python swift_analyzer.py --dump <Swift file>")
            sys.exit(1)
        dump_ast(sys.argv[2])
        sys.exit(0)

    file_path = sys.argv[1]
    metrics = analyze_swift_file(file_path)

    print("Mutable vars:          ", metrics.mutable_vars)
    print("Immutable vars:        ", metrics.immutable_vars)
    print("Observable state vars: ", metrics.observable_state_vars)
    print("State updates:         ", metrics.state_updates)

    if metrics.mutable_var_names:
        print("\nMutable var names:   ", metrics.mutable_var_names)
    if metrics.immutable_var_names:
        print("Immutable var names: ", metrics.immutable_var_names)
    if metrics.observable_var_names:
        print("Observable var names:", metrics.observable_var_names)

    if metrics.state_update_lines:
        print("\nState update lines (first 20):")
        for ln, text in metrics.state_update_lines[:20]:
            print(f"  Line {ln}: {text.strip()}")