from tree_sitter import Language, Parser
from tree_sitter_kotlin import language as kotlin_language
from dataclasses import dataclass, field
from typing import List, Tuple

parser = Parser(Language(kotlin_language()))

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

OBSERVABLE_PATTERNS = [
    # Compose state
    'mutableStateOf', 'MutableState', 'SnapshotStateList', 'SnapshotStateMap',
    'mutableStateListOf', 'mutableStateMapOf', 'derivedStateOf',
    # LiveData
    'LiveData', 'MutableLiveData', 'MediatorLiveData',
    # Flows
    'StateFlow', 'MutableStateFlow', 'SharedFlow', 'MutableSharedFlow',
    # Mutable collections used as state
    'MutableList', 'MutableMap', 'MutableSet',
    # Coroutines
    'Channel',
    # Concurrent
    'AtomicInteger', 'AtomicReference',
]

REACTIVE_CALL_PATTERNS = [
    '.postValue(', '.setValue(', '.emit(', '.tryEmit(',
    '.update(', '.update {',
    '.compareAndSet(', '.toggle(',
    '.getAndSet(', '.getAndUpdate(',
]

COLLECTION_CALL_PATTERNS = [
    '.add(', '.addAll(', '.remove(', '.removeAt(', '.removeAll(',
    '.clear(', '.put(', '.putAll(', '.append(', '.insert(',
    '.sort(', '.shuffle(', '.set(', '.retainAll(',
]

def parse_file(file_path: str):
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

def walk_ast(node, code_bytes: bytes, metrics: StateMetrics):

    # === PROPERTY DECLARATIONS ===
    if node.type == 'property_declaration':
        kw_node = first_child_of_type(node, 'var', 'val')
        keyword = kw_node.type if kw_node else None

        var_decl = first_child_of_type(node, 'variable_declaration')
        name_node = first_child_of_type(var_decl, 'identifier') if var_decl else None

        if keyword and name_node:
            var_name = get_text(name_node, code_bytes)

            if keyword == 'var':
                metrics.mutable_vars += 1
                metrics.mutable_var_names.append(var_name)
            else:
                metrics.immutable_vars += 1
                metrics.immutable_var_names.append(var_name)

            # Check initializer (child after `=`)
            eq_seen = False
            for child in node.children:
                if child.type == '=':
                    eq_seen = True
                    continue
                if eq_seen:
                    if any(p in get_text(child, code_bytes) for p in OBSERVABLE_PATTERNS):
                        metrics.observable_state_vars += 1
                        metrics.observable_var_names.append(var_name)
                    break

            # Check delegate: `var x by mutableStateOf(...)`
            delegate = first_child_of_type(node, 'property_delegate')
            if delegate:
                if any(p in get_text(delegate, code_bytes) for p in OBSERVABLE_PATTERNS):
                    metrics.observable_state_vars += 1
                    if var_name not in metrics.observable_var_names:
                        metrics.observable_var_names.append(var_name)

    # === ASSIGNMENTS ===
    elif node.type == 'assignment':
        start_line = node.start_point[0] + 1
        node_text = get_text(node, code_bytes)

        lhs_node = node.children[0] if node.children else None
        if lhs_node:
            lhs_text = get_text(lhs_node, code_bytes)
            all_tracked = set(metrics.mutable_var_names + metrics.observable_var_names)
            if any(lhs_text == n or lhs_text.startswith(n + '.') for n in all_tracked):
                metrics.state_updates += 1
                metrics.state_update_lines.append((start_line, node_text))

    # === REACTIVE / MUTATING CALL EXPRESSIONS ===
    elif node.type == 'call_expression':
        start_line = node.start_point[0] + 1
        call_text = get_text(node, code_bytes)
        if any(m in call_text for m in REACTIVE_CALL_PATTERNS + COLLECTION_CALL_PATTERNS):
            metrics.state_updates += 1
            metrics.state_update_lines.append((start_line, call_text))

    for child in node.children:
        walk_ast(child, code_bytes, metrics)

def analyze_file(file_path: str) -> StateMetrics:
    root_node, code_bytes = parse_file(file_path)
    metrics = StateMetrics()
    walk_ast(root_node, code_bytes, metrics)
    return metrics

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python kotlin_analyzer.py <Kotlin file>")
        sys.exit(1)

    metrics = analyze_file(sys.argv[1])

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