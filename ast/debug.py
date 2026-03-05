
import sys
from tree_sitter import Parser, Language
from tree_sitter_kotlin import language as kotlin_language
from tree_sitter_swift import language as swift_language

ext_map = {
    '.kt': kotlin_language(),
    '.swift': swift_language(),
}

file_path = sys.argv[1]
ext = '.' + file_path.rsplit('.', 1)[-1]
lang = Language(ext_map.get(ext))

parser = Parser(lang)

code = open(file_path, 'rb').read()
tree = parser.parse(code)

def dump(node, indent=0):
    snippet = code[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
    snippet = snippet.replace('\n', '↵')[:60]
    print(' ' * indent + f"[{node.type}] {repr(snippet)}")
    for child in node.children:
        dump(child, indent + 2)

dump(tree.root_node)