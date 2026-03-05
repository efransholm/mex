from tree_sitter import Language, Parser

'''
Ran once and don't need to be run again
'''

Language.build_library(
    'build/my-languages.so',
    [
        'tree-sitter-kotlin',
        'tree-sitter-swift',
    ]
)