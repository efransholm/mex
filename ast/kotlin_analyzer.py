from tree_sitter import Language, Parser
from dataclasses import dataclass, field
from typing import List, Tuple

KOTLIN_LANGUAGE = Language('build/my-languages.so', 'kotlin')

parser = Parser()
parser.set_language(KOTLIN_LANGUAGE)

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

def parse_kotlin_file(file_path: str):
    with open(file_path, 'r', encoding='utf-8') as f:
        code = f.read().encode()
    tree = parser.parse(code)
    return tree.root_node, code

def get_text(node, code_bytes: bytes) -> str:
    return code_bytes[node.start_byte:node.end_byte].decode('utf-8')

def first_child_of_type(node, *types):
    """Return the first direct child whose type is in `types`, or None."""
    for child in node.children:
        if child.type in types:
            return child
    return None

def walk_ast(node, code_bytes: bytes, metrics: StateMetrics):

    # === PROPERTY DECLARATIONS (top-level and class-level) ===
    if node.type == 'property_declaration':
        # var/val lives inside a binding_pattern_kind node as its first child
        # e.g. [binding_pattern_kind] -> [var] or [val]
        bpk = first_child_of_type(node, 'binding_pattern_kind')
        keyword = None
        if bpk:
            kw_node = first_child_of_type(bpk, 'var', 'val')
            if kw_node:
                keyword = kw_node.type  # literally 'var' or 'val'

        # The name lives in variable_declaration -> simple_identifier
        var_decl = first_child_of_type(node, 'variable_declaration')
        name_node = None
        if var_decl:
            name_node = first_child_of_type(var_decl, 'simple_identifier')

        if keyword and name_node:
            var_name = get_text(name_node, code_bytes)

            if keyword == 'var':
                metrics.mutable_vars += 1
                metrics.mutable_var_names.append(var_name)
            else:
                metrics.immutable_vars += 1
                metrics.immutable_var_names.append(var_name)

            observable_patterns = [
                'mutableStateOf', 'MutableState', 'LiveData',
                'MutableLiveData', 'StateFlow', 'MutableStateFlow',
                'SharedFlow', 'MutableSharedFlow',
                'mutableStateListOf', 'mutableStateMapOf',
            ]

            # Check initializer: everything after the `=` token
            eq_seen = False
            for child in node.children:
                if child.type == '=':
                    eq_seen = True
                    continue
                if eq_seen:
                    value_text = get_text(child, code_bytes)
                    if any(pat in value_text for pat in observable_patterns):
                        metrics.observable_state_vars += 1
                        metrics.observable_var_names.append(var_name)
                    break

            # Check delegate: `var x by mutableStateOf(...)`
            delegate = first_child_of_type(node, 'property_delegate')
            if delegate:
                delegate_text = get_text(delegate, code_bytes)
                if any(pat in delegate_text for pat in observable_patterns):
                    metrics.observable_state_vars += 1
                    if var_name not in metrics.observable_var_names:
                        metrics.observable_var_names.append(var_name)

    # === LOCAL VARIABLE DECLARATIONS (inside functions) ===
    elif node.type == 'local_variable_declaration':
        bpk = first_child_of_type(node, 'binding_pattern_kind')
        keyword = None
        if bpk:
            kw_node = first_child_of_type(bpk, 'var', 'val')
            if kw_node:
                keyword = kw_node.type

        var_decl = first_child_of_type(node, 'variable_declaration')
        name_node = None
        if var_decl:
            name_node = first_child_of_type(var_decl, 'simple_identifier')

        if keyword and name_node:
            var_name = get_text(name_node, code_bytes)

            if keyword == 'var':
                metrics.mutable_vars += 1
                metrics.mutable_var_names.append(var_name)
            else:
                metrics.immutable_vars += 1
                metrics.immutable_var_names.append(var_name)

            observable_patterns = [
                'mutableStateOf', 'MutableState', 'LiveData',
                'MutableLiveData', 'StateFlow', 'MutableStateFlow',
                'SharedFlow', 'MutableSharedFlow',
                'mutableStateListOf', 'mutableStateMapOf',
            ]

            eq_seen = False
            for child in node.children:
                if child.type == '=':
                    eq_seen = True
                    continue
                if eq_seen:
                    value_text = get_text(child, code_bytes)
                    if any(pat in value_text for pat in observable_patterns):
                        metrics.observable_state_vars += 1
                        metrics.observable_var_names.append(var_name)
                    break

    # === ASSIGNMENTS ===
    elif node.type == 'assignment':
        start_line = node.start_point[0] + 1
        node_text = get_text(node, code_bytes)

        # LHS is the first child: [directly_assignable_expression] -> [simple_identifier]
        lhs_node = node.children[0] if node.children else None
        if lhs_node:
            lhs_text = get_text(lhs_node, code_bytes)
            all_tracked = set(metrics.mutable_var_names + metrics.observable_var_names)
            # Match plain name or member access like `state.value`
            matched = any(
                lhs_text == name or lhs_text.startswith(name + '.')
                for name in all_tracked
            )
            if matched:
                metrics.state_updates += 1
                metrics.state_update_lines.append((start_line, node_text))

    # === REACTIVE METHOD CALLS ===
    elif node.type == 'call_expression':
        start_line = node.start_point[0] + 1
        call_text = get_text(node, code_bytes)

        reactive_methods = [
            '.postValue(', '.emit(', '.tryEmit(',
            '.setValue(', '.toggle(',
        ]
        collection_methods = [
            '.add(', '.addAll(', '.remove(', '.removeAt(', '.removeAll(',
            '.clear(', '.put(', '.putAll(', '.append(', '.insert(',
            '.replaceSubrange(', '.sort(', '.shuffle(',
        ]
        if any(m in call_text for m in reactive_methods + collection_methods):
            metrics.state_updates += 1
            metrics.state_update_lines.append((start_line, call_text))

    # Recurse
    for child in node.children:
        walk_ast(child, code_bytes, metrics)

def analyze_kotlin_file(file_path: str) -> StateMetrics:
    root_node, code_bytes = parse_kotlin_file(file_path)
    metrics = StateMetrics()
    walk_ast(root_node, code_bytes, metrics)
    return metrics

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python kotlin_analyzer.py <Kotlin file>")
        sys.exit(1)

    file_path = sys.argv[1]
    metrics = analyze_kotlin_file(file_path)

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