#!/usr/bin/env python3
"""
Halstead Complexity Measures Calculator for Kotlin and Swift

This script calculates Halstead complexity metrics for Kotlin and Swift source code.

Generated with Claude Sonnet 4.5
"""

import re
from typing import List, Set, Dict, Tuple
from collections import Counter
import math


class HalsteadMetrics:
    """Container for Halstead complexity metrics"""
    
    def __init__(self, operators: List[str], operands: List[str]):
        self.operators = operators
        self.operands = operands
        
        # Basic counts
        self.n1 = len(set(operators))  # Number of unique operators
        self.n2 = len(set(operands))   # Number of unique operands
        self.N1 = len(operators)       # Total number of operators
        self.N2 = len(operands)        # Total number of operands
        
        # Calculate derived metrics
        self._calculate_metrics()
    
    def _calculate_metrics(self):
        """Calculate derived Halstead metrics"""
        print(f"""Calculating Halstead metrics with 
operators={self.operators}, 
operands={self.operands}""")
        # Program vocabulary
        self.n = self.n1 + self.n2
        
        # Program length
        self.N = self.N1 + self.N2
        
        # Calculated program length
        self.N_hat = self.n1 * math.log2(self.n1) + self.n2 * math.log2(self.n2) if self.n1 > 0 and self.n2 > 0 else 0
        
        # Volume
        self.V = self.N * math.log2(self.n) if self.n > 0 else 0
        
        # Difficulty
        self.D = (self.n1 / 2) * (self.N2 / self.n2) if self.n2 > 0 else 0
        
        # Effort
        self.E = self.D * self.V
        
        # Time required to program (in seconds)
        self.T = self.E / 18
        
        # Number of delivered bugs
        self.B = self.V / 3000
    
    def __str__(self):
        return f"""Halstead Complexity Metrics:
==========================================
Basic Counts:
  n1 (unique operators):     {self.n1}
  n2 (unique operands):      {self.n2}
  N1 (total operators):      {self.N1}
  N2 (total operands):       {self.N2}

Derived Metrics:
  n  (vocabulary):           {self.n}
  N  (length):               {self.N}
  N^ (calculated length):    {self.N_hat:.2f}
  V  (volume):               {self.V:.2f}
  D  (difficulty):           {self.D:.2f}
  E  (effort):               {self.E:.2f}
  T  (time in seconds):      {self.T:.2f}
  B  (delivered bugs):       {self.B:.3f}
"""


class KotlinHalsteadAnalyzer:
    """Analyzer for Kotlin code"""
    
    # Kotlin operators (ordered by length for proper matching)
    OPERATORS = [
        # Compound operators (check these first)
        '===', '!==', '==', '!=', '<=', '>=', '&&', '||', '++', '--', 
        '+=', '-=', '*=', '/=', '%=', '!!', '?.', '?:', '..', '..<', '->', '::',
        # Single character operators
        '+', '-', '*', '/', '%', '=', '<', '>', '!', '&', '|', '^', '~',
        '?', ':', ';'
    ]
    
    # Kotlin keywords that act as operators
    KEYWORD_OPERATORS = [
         'if', 'else', 'when', 'for', 'while', 'do', 'return', 'break', 'continue',
        'try', 'catch', 'finally', 'throw', 'in', 'is', 'as', 'typeof', 'val', 'var',
        'fun', 'class', 'interface', 'object', 'enum', 'data', 'sealed', 'inner',
        'open', 'abstract', 'override', 'private', 'public', 'internal', 'protected',
        'lateinit', 'const', 'companion', 'typealias', 'this', 'super', 'by', 'shl', 
        'shr', 'ushr', 'and', 'or', 'xor', 'inv', '!in', '!is'
    ]
    
    def __init__(self):
        self.operators = []
        self.operands = []
    
    def analyze(self, code: str) -> HalsteadMetrics:
        """Analyze Kotlin code and return Halstead metrics"""
        self.operators = []
        self.operands = []

        code = self._strip_comments(code)

        for token in self._tokenize(code):
            if self._is_operator(token):
                self.operators.append(token)
            elif self._is_operand(token):
                self.operands.append(token)

        return HalsteadMetrics(self.operators, self.operands)

    def _strip_comments(self, code: str) -> str:
        """Remove single-line and multi-line comments"""
        code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
        code = re.sub(r'//.*?$', ' ', code, flags=re.MULTILINE)
        return code

    def _tokenize(self, code: str) -> List[str]:
        """Tokenize Kotlin code, yielding raw string contents as operand tokens"""
        tokens = []

        # Order matters: triple-quoted strings before single-quoted chars before
        # regular double-quoted strings, so the longer patterns win.
        # Each string alternative captures the full literal including quotes so
        # its raw text (quotes and all) becomes the token — identical strings
        # therefore deduplicate naturally when counting unique operands.
        pattern = (
            r'""".*?"""'                  # triple-quoted (raw) string
            r"|'(?:[^'\\]|\\.)*'"         # character literal
            r'|"(?:[^"\\]|\\.)*"'         # regular string
            r'|\b\w+\b'                   # identifiers, keywords, numbers
            r'|[+\-*/%=<>!&|^~?:.,;()\[\]{}]+'  # symbol runs
        )

        for match in re.finditer(pattern, code, re.DOTALL):
            token = match.group()

            # String literals: keep as-is and hand straight to the classifier
            if token.startswith(('"', "'")):
                tokens.append(token)
                continue

            # Symbol run: split into individual/compound operators
            if not token.isalnum() and not token.startswith('_'):
                i = 0
                while i < len(token):
                    matched = False
                    for op_len in range(min(3, len(token) - i), 0, -1):
                        potential_op = token[i:i + op_len]
                        if potential_op in self.OPERATORS:
                            tokens.append(potential_op)
                            i += op_len
                            matched = True
                            break
                    if not matched:
                        if token[i] in self.OPERATORS:
                            tokens.append(token[i])
                        i += 1
            else:
                tokens.append(token)

        return tokens
    
    def _is_operator(self, token: str) -> bool:
        """Check if token is an operator"""
        return token in self.OPERATORS or token in self.KEYWORD_OPERATORS
    
    def _is_operand(self, token: str) -> bool:
        """Check if token is an operand"""
        # String literals (kept verbatim from source, including quotes)
        if token.startswith(('"', "'")):
            return True

        # Keyword operators are not operands
        if token in self.KEYWORD_OPERATORS:
            return False

        # Symbol operators are not operands
        if token in self.OPERATORS:
            return False

        # Identifiers (variables, function names, type names, etc.)
        if re.match(r'^[a-zA-Z_]\w*$', token):
            kotlin_keywords = {
                'abstract', 'annotation', 'by', 'class', 'companion', 'const',
                'constructor', 'crossinline', 'data', 'delegate', 'enum', 'external',
                'field', 'file', 'fun', 'get', 'import', 'init', 'inline', 'inner',
                'interface', 'internal', 'lateinit', 'noinline', 'object', 'open',
                'operator', 'out', 'override', 'package', 'param', 'private', 'property',
                'protected', 'public', 'receiver', 'reified', 'sealed', 'set', 'setparam',
                'suspend', 'tailrec', 'val', 'var', 'vararg', 'where'
            }
            return token not in kotlin_keywords

        # Numeric literals
        if re.match(r'^\d+\.?\d*[fFdDlL]?$', token):
            return True

        return False


class SwiftHalsteadAnalyzer:
    """Analyzer for Swift code"""
    
    # Swift operators (ordered by length for proper matching)
    OPERATORS = [
        # Compound operators (check these first)
        '===', '!==', '==', '!=', '<=', '>=', '&&', '||',
        '++', '--', '+=', '-=', '*=', '/=', '%=', '??', '...', '..<', '->', '~=',
        '.!', '.<', '.<=', '.>', '.>=', '.==', '.!=', '.&&', '.||', '.^', '.&=', '.|=', '.^=',
        # Single character operators
        '+', '-', '*', '/', '%', '=', '<', '>', '!', '&', '|', '^', '~',
        '?', ':', '.', ';'
    ]
    
    # Swift keywords that act as operators
    KEYWORD_OPERATORS = [
        'if', 'else', 'guard', 'switch', 'case', 'default', 'for', 'while', 'repeat',
        'return', 'break', 'continue', 'fallthrough', 'try', 'catch', 'throw', 'defer', 'do',
        'in', 'is', 'as', 'as?', 'as!', 'self', 'super', 'nil', 'true', 'false', 'inout',
        'let', 'var', 'func', 'class', 'struct', 'enum', 'protocol', 'extension', 'import',
        'init', 'deinit', 'static', 'subscript', 'typealias', 'operator', 'precedencegroup',
        'public', 'private', 'internal', 'fileprivate', 'open', '#available', 
        '#colorLiteral', '#else', '#elseif', '#endif', '#fileLiteral', '#if', 
        '#imageLiteral', '#keyPath', '#selector', '#sourceLocation', '#unavailable'
    ]
    
    def __init__(self):
        self.operators = []
        self.operands = []
    
    def analyze(self, code: str) -> HalsteadMetrics:
        """Analyze Swift code and return Halstead metrics"""
        self.operators = []
        self.operands = []

        code = self._strip_comments(code)

        for token in self._tokenize(code):
            if self._is_operator(token):
                self.operators.append(token)
            elif self._is_operand(token):
                self.operands.append(token)

        return HalsteadMetrics(self.operators, self.operands)

    def _strip_comments(self, code: str) -> str:
        """Remove single-line and multi-line comments"""
        code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
        code = re.sub(r'//.*?$', ' ', code, flags=re.MULTILINE)
        return code

    def _tokenize(self, code: str) -> List[str]:
        """Tokenize Swift code, yielding raw string contents as operand tokens"""
        tokens = []

        # Triple-quoted strings must come before regular strings so the longer
        # pattern wins. Raw string contents (quotes included) become the token,
        # so identical strings deduplicate naturally when counting unique operands.
        pattern = (
            r'""".*?"""'                  # multi-line string
            r'|"(?:[^"\\]|\\.)*"'         # regular string
            r'|\b\w+\b'                   # identifiers, keywords, numbers
            r'|[+\-*/%=<>!&|^~?:.,;()\[\]{}]+'  # symbol runs
        )

        for match in re.finditer(pattern, code, re.DOTALL):
            token = match.group()

            # String literals: keep as-is and hand straight to the classifier
            if token.startswith('"'):
                tokens.append(token)
                continue

            # Symbol run: split into individual/compound operators
            if not token.isalnum() and not token.startswith('_'):
                i = 0
                while i < len(token):
                    matched = False
                    for op_len in range(min(3, len(token) - i), 0, -1):
                        potential_op = token[i:i + op_len]
                        if potential_op in self.OPERATORS:
                            tokens.append(potential_op)
                            i += op_len
                            matched = True
                            break
                    if not matched:
                        if token[i] in self.OPERATORS:
                            tokens.append(token[i])
                        i += 1
            else:
                tokens.append(token)

        return tokens
    
    def _is_operator(self, token: str) -> bool:
        """Check if token is an operator"""
        return token in self.OPERATORS or token in self.KEYWORD_OPERATORS
    
    def _is_operand(self, token: str) -> bool:
        """Check if token is an operand"""
        # String literals (kept verbatim from source, including quotes)
        if token.startswith('"'):
            return True

        # Keyword operators are not operands
        if token in self.KEYWORD_OPERATORS:
            return False

        # Symbol operators are not operands
        if token in self.OPERATORS:
            return False

        # Identifiers (variables, function names, type names, etc.)
        if re.match(r'^[a-zA-Z_]\w*$', token):
            swift_keywords = {
                'associatedtype', 'class', 'deinit', 'enum', 'extension', 'func',
                'import', 'init', 'inout', 'internal', 'let', 'operator', 'private',
                'protocol', 'public', 'static', 'struct', 'subscript', 'typealias',
                'var', 'fileprivate', 'open', 'defer', 'do', 'catch', 'throws',
                'rethrows', 'indirect', 'lazy', 'mutating', 'nonmutating', 'optional',
                'override', 'required', 'weak', 'unowned', 'final', 'dynamic',
                'convenience', 'Any', 'Self'
            }
            return token not in swift_keywords

        # Numeric literals
        if re.match(r'^\d+\.?\d*$', token):
            return True

        return False


def analyze_file(filepath: str, language: str = 'auto') -> HalsteadMetrics:
    """
    Analyze a source code file and return Halstead metrics
    
    Args:
        filepath: Path to the source code file
        language: 'kotlin', 'swift', or 'auto' (auto-detect from extension)
    
    Returns:
        HalsteadMetrics object
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    # Auto-detect language from file extension
    if language == 'auto':
        if filepath.endswith('.kt') or filepath.endswith('.kts'):
            language = 'kotlin'
        elif filepath.endswith('.swift'):
            language = 'swift'
        else:
            raise ValueError(f"Cannot auto-detect language from file: {filepath}")
    
    # Select appropriate analyzer
    if language.lower() == 'kotlin':
        analyzer = KotlinHalsteadAnalyzer()
    elif language.lower() == 'swift':
        analyzer = SwiftHalsteadAnalyzer()
    else:
        raise ValueError(f"Unsupported language: {language}")
    
    return analyzer.analyze(code)


def analyze_code_string(code: str, language: str) -> HalsteadMetrics:
    """
    Analyze a code string and return Halstead metrics
    
    Args:
        code: Source code as a string
        language: 'kotlin' or 'swift'
    
    Returns:
        HalsteadMetrics object
    """
    if language.lower() == 'kotlin':
        analyzer = KotlinHalsteadAnalyzer()
    elif language.lower() == 'swift':
        analyzer = SwiftHalsteadAnalyzer()
    else:
        raise ValueError(f"Unsupported language: {language}")
    
    return analyzer.analyze(code)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python halstead_complexity.py <file_path> [language]")
        print("  language: 'kotlin', 'swift', or 'auto' (default: auto)")
        print("\nExample:")
        print("  python halstead_complexity.py MyClass.kt")
        print("  python halstead_complexity.py MyClass.swift")
        sys.exit(1)
    
    filepath = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    
    try:
        metrics = analyze_file(filepath, language)
        print(f"File: {filepath}")
        print(metrics)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)