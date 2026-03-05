#!/usr/bin/env python3
"""
State Mutation Metrics Analyzer for Kotlin and Swift

Analyzes mutable state usage in mobile UI code (Compose, Android Views, SwiftUI, UIKit).
"""

import re
from typing import List, Tuple
from dataclasses import dataclass, field


@dataclass
class StateMetrics:
    """Container for state mutation metrics"""
    
    # Raw counts
    mutable_vars: int = 0
    immutable_vars: int = 0
    observable_state_vars: int = 0
    state_updates: int = 0
    
    # Context counts for normalization
    total_lines: int = 0
    non_empty_lines: int = 0
    classes: int = 0
    
    # Detailed findings
    mutable_var_names: List[str] = field(default_factory=list)
    immutable_var_names: List[str] = field(default_factory=list)
    observable_var_names: List[str] = field(default_factory=list)
    state_update_lines: List[Tuple[int, str]] = field(default_factory=list)
    
    def total_vars(self) -> int:
        """Total number of variables"""
        return self.mutable_vars + self.immutable_vars
    
    def mutable_ratio(self) -> float:
        """Ratio of mutable to total variables"""
        total = self.total_vars()
        return self.mutable_vars / total if total > 0 else 0.0
    
    def mutable_per_file(self) -> float:
        """Mutable variables per file (always 1 file, so just count)"""
        return float(self.mutable_vars)
    
    def mutable_per_class(self) -> float:
        """Mutable variables per class"""
        return self.mutable_vars / self.classes if self.classes > 0 else float(self.mutable_vars)
    
    def mutable_per_loc(self) -> float:
        """Mutable variables per line of code (non-empty)"""
        return self.mutable_vars / self.non_empty_lines if self.non_empty_lines > 0 else 0.0
    
    def observable_per_file(self) -> float:
        """Observable state variables per file"""
        return float(self.observable_state_vars)
    
    def observable_per_class(self) -> float:
        """Observable state variables per class"""
        return self.observable_state_vars / self.classes if self.classes > 0 else float(self.observable_state_vars)
    
    def observable_per_loc(self) -> float:
        """Observable state variables per line of code"""
        return self.observable_state_vars / self.non_empty_lines if self.non_empty_lines > 0 else 0.0
    
    def __str__(self):
        return f"""State Mutation Metrics:
==========================================
Variable Counts:
  Mutable variables (var):        {self.mutable_vars}
  Immutable variables (val/let):  {self.immutable_vars}
  Total variables:                {self.total_vars()}
  Observable state variables:     {self.observable_state_vars}
  State updates detected:         {self.state_updates}

Normalized Metrics:
  Mutable per file:               {self.mutable_per_file():.2f}
  Mutable per class:              {self.mutable_per_class():.2f}
  Mutable per LoC:                {self.mutable_per_loc():.4f}
  Mutable ratio:                  {self.mutable_ratio():.2%}
  
  Observable per file:            {self.observable_per_file():.2f}
  Observable per class:           {self.observable_per_class():.2f}
  Observable per LoC:             {self.observable_per_loc():.4f}

Context:
  Total lines:                    {self.total_lines}
  Non-empty lines (LoC):          {self.non_empty_lines}
  Classes/structs:                {self.classes}
"""


class KotlinStateAnalyzer:
    """Analyzes state mutation in Kotlin code (Compose and Android Views)"""
    
    # Compose observable state patterns
    COMPOSE_STATE_PATTERNS = [
        r'\bmutableStateOf\b',
        r'\bMutableState\b',
        r'\bremember\s*\{[^}]*mutableStateOf',
        r'\brememberSaveable\s*\{[^}]*mutableStateOf',
        r'\bMutableLiveData\b',
        r'\bLiveData\b',
        r'\bStateFlow\b',
        r'\bMutableStateFlow\b',
        r'\bSharedFlow\b',
        r'\bMutableSharedFlow\b',
    ]
    
    # Android Views observable patterns
    ANDROID_VIEWS_PATTERNS = [
        r'\bObservable\b',
        r'\bLiveData\b',
        r'\bMutableLiveData\b',
    ]
    
    # State update patterns (assignments to var or state)
    STATE_UPDATE_PATTERNS = [
        r'\bset\s*\(',  # state.set(...)
        r'\.value\s*=',  # state.value = ...
        r'\.postValue\s*\(',  # liveData.postValue(...)
        r'\.setValue\s*\(',  # liveData.setValue(...)
        r'\.emit\s*\(',  # flow.emit(...)
    ]
    
    def analyze(self, code: str) -> StateMetrics:
        """Analyze Kotlin code for state mutation patterns"""
        metrics = StateMetrics()
        
        # Strip comments for cleaner analysis
        code_no_comments = self._strip_comments(code)
        lines = code.split('\n')
        
        # Count lines
        metrics.total_lines = len(lines)
        metrics.non_empty_lines = sum(1 for line in lines if line.strip())
        
        # Count classes
        metrics.classes = len(re.findall(r'\b(class|object|interface)\s+\w+', code_no_comments))
        if metrics.classes == 0:
            metrics.classes = 1  # Treat file-level code as one implicit class
        
        # Find variable declarations
        self._analyze_variables(code_no_comments, metrics)
        
        # Find observable state variables
        self._analyze_observable_state(code_no_comments, metrics)
        
        # Find state updates
        self._analyze_state_updates(code, lines, metrics)
        
        return metrics
    
    def detect_kotlin_mutations(self, line: str) -> bool:
        patterns = [
            r'\b\w+\s*=',                         # assignment
            r'\b\w+\s*(\+=|-=|\*=|/=|%=)',        # compound
            r'\b\w+\s*(\+\+|--)',                 # inc/dec
            r'\b\w+\s*\[.*?\]\s*=',               # indexed assignment
            r'\b\w+(?:\.\w+)+\s*=',               # property assignment
            r'\.(add|addAll|remove|removeAt|removeAll|clear|put|putAll|set|replace)\s*\(',
            r'\.(value|postValue|emit|tryEmit)\s*(=|\()',
        ]

        return any(re.search(p, line) for p in patterns)
    
    def _strip_comments(self, code: str) -> str:
        """Remove single-line and multi-line comments"""
        code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
        code = re.sub(r'//.*?$', ' ', code, flags=re.MULTILINE)
        return code
    
    def _analyze_variables(self, code: str, metrics: StateMetrics):
        """Analyze variable declarations"""
        # Match var declarations (including delegated properties with 'by')
        var_pattern = r'\bvar\s+(\w+)\s*(?::|by\s+|=)'
        for match in re.finditer(var_pattern, code):
            var_name = match.group(1)
            metrics.mutable_vars += 1
            metrics.mutable_var_names.append(var_name)
        
        # Match val declarations (including delegated properties with 'by')
        val_pattern = r'\bval\s+(\w+)\s*(?::|by\s+|=)'
        for match in re.finditer(val_pattern, code):
            var_name = match.group(1)
            metrics.immutable_vars += 1
            metrics.immutable_var_names.append(var_name)
    
    def _analyze_observable_state(self, code: str, metrics: StateMetrics):
        """Analyze observable state variables"""
        # Collect all observable state variable names
        observable_names = set()
        
        # Check for Compose state patterns with 'by' delegation
        # Pattern: var name by remember { mutableStateOf(...) }
        by_remember_pattern = r'\b(?:var|val)\s+(\w+)\s+by\s+(?:remember|rememberSaveable)'
        for match in re.finditer(by_remember_pattern, code):
            var_name = match.group(1)
            observable_names.add(var_name)
        
        # Handle delegated mutableStateOf (e.g., var count by mutableStateOf(0))
        by_mutablestate_pattern = r'\b(?:var|val)\s+(\w+)\s+by\s+mutableStateOf'
        for match in re.finditer(by_mutablestate_pattern, code):
            var_name = match.group(1)
            observable_names.add(var_name)
    
        # Check for direct state type declarations
        for pattern in self.COMPOSE_STATE_PATTERNS:
            for match in re.finditer(pattern, code):
                # Try to find the variable name before this pattern
                start = match.start()
                # Look backwards for var/val declaration
                prefix = code[max(0, start-150):start]
                var_match = re.search(r'\b(?:var|val)\s+(\w+)\s*[=:][^=]*$', prefix)
                if var_match:
                    var_name = var_match.group(1)
                    observable_names.add(var_name)
        
        # Check for Android Views patterns
        for pattern in self.ANDROID_VIEWS_PATTERNS:
            for match in re.finditer(pattern, code):
                # Look for variable declarations with these types
                start = match.start()
                prefix = code[max(0, start-150):start]
                var_match = re.search(r'\b(?:var|val)\s+(\w+)\s*[=:][^=]*$', prefix)
                if var_match:
                    var_name = var_match.group(1)
                    observable_names.add(var_name)
        
        metrics.observable_state_vars = len(observable_names)
        metrics.observable_var_names = list(observable_names)
    
    def _analyze_state_updates(self, code: str, lines: List[str], metrics: StateMetrics):
        """Analyze state update operations"""

        # Track which lines we've already counted
        counted_lines = set()
        
        for line_num, line in enumerate(lines, 1):
            line_clean = line.strip()
            if not line_clean or line_clean.startswith('//'):
                continue

            if line_num in counted_lines:
                continue

            # Do not count initializations (var name = ...) as updates
            if line_clean.startswith("var ") or line_clean.startswith("val "):
                continue

            # Remove string literals to reduce false positives
            line_clean = re.sub(r'".*?"', '', line_clean)

            # Use centralized mutation detection
            if self.detect_kotlin_mutations(line_clean):
                metrics.state_updates += 1
                metrics.state_update_lines.append((line_num, line_clean[:80]))
                counted_lines.add(line_num)


class SwiftStateAnalyzer:
    """Analyzes state mutation in Swift code (SwiftUI and UIKit)"""
    
    # SwiftUI state patterns
    SWIFTUI_STATE_PATTERNS = [
        r'@State\b',
        r'@Binding\b',
        r'@ObservedObject\b',
        r'@StateObject\b',
        r'@EnvironmentObject\b',
        r'@Published\b',
    ]
    
    # UIKit observable patterns
    UIKIT_PATTERNS = [
        r'\bObservable\b',
        r'\bPublished\b',
    ]
    
    # State update patterns
    STATE_UPDATE_PATTERNS = [
        r'\.toggle\s*\(',
        r'\.append\s*\(',
        r'\.remove\s*\(',
        r'\.removeAll\s*\(',
    ]
    
    def analyze(self, code: str) -> StateMetrics:
        """Analyze Swift code for state mutation patterns"""
        metrics = StateMetrics()
        
        # Strip comments for cleaner analysis
        code_no_comments = self._strip_comments(code)
        lines = code.split('\n')
        
        # Count lines
        metrics.total_lines = len(lines)
        metrics.non_empty_lines = sum(1 for line in lines if line.strip())
        
        # Count classes/structs
        metrics.classes = len(re.findall(r'\b(class|struct|actor)\s+\w+', code_no_comments))
        if metrics.classes == 0:
            metrics.classes = 1  # Treat file-level code as one implicit class
        
        # Find variable declarations
        self._analyze_variables(code_no_comments, metrics)
        
        # Find observable state variables
        self._analyze_observable_state(code_no_comments, metrics)
        
        # Find state updates
        self._analyze_state_updates(code, lines, metrics)
        
        return metrics
    
    def detect_swift_mutations(self, line: str) -> bool:
        patterns = [
            r'\b\w+\s*=',                         # assignment
            r'\b\w+\s*(\+=|-=|\*=|/=|%=)',        # compound
            r'\b\w+\s*(\+\+|--)',                 # inc/dec
            r'\b\w+\s*\[.*?\]\s*=',               # indexed
            r'\b\w+(?:\.\w+)+\s*=',               # property
            r'\.(append|remove|removeAll|insert|replaceSubrange|sort|shuffle)\s*\(',
            r'\.toggle\s*\(',
        ]

        return any(re.search(p, line) for p in patterns)
        
    def _strip_comments(self, code: str) -> str:
        """Remove single-line and multi-line comments"""
        code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
        code = re.sub(r'//.*?$', ' ', code, flags=re.MULTILINE)
        return code
    
    def _analyze_variables(self, code: str, metrics: StateMetrics):
        """Analyze variable declarations"""
        # Match var declarations
        var_pattern = r'\bvar\s+(\w+)\s*[=:]'
        for match in re.finditer(var_pattern, code):
            var_name = match.group(1)
            metrics.mutable_vars += 1
            metrics.mutable_var_names.append(var_name)
        
        # Match let declarations
        let_pattern = r'\blet\s+(\w+)\s*[=:]'
        for match in re.finditer(let_pattern, code):
            var_name = match.group(1)
            metrics.immutable_vars += 1
            metrics.immutable_var_names.append(var_name)
    
    def _analyze_observable_state(self, code: str, metrics: StateMetrics):
        """Analyze observable state variables"""
        # Collect all observable state variable names
        observable_names = set()
        
        # Check for SwiftUI state patterns
        for pattern in self.SWIFTUI_STATE_PATTERNS:
            for match in re.finditer(pattern, code):
                # Look for the variable name after this annotation
                start = match.end()
                suffix = code[start:start+100]
                # Match: @State var name or @State private var name
                var_match = re.search(r'(?:private\s+)?(?:var|let)\s+(\w+)', suffix)
                if var_match:
                    var_name = var_match.group(1)
                    observable_names.add(var_name)
        
        # Check for UIKit patterns
        for pattern in self.UIKIT_PATTERNS:
            for match in re.finditer(pattern, code):
                start = match.start()
                prefix = code[max(0, start-100):start]
                var_match = re.search(r'\b(var|let)\s+(\w+)\s*[=:][^=]*$', prefix)
                if var_match:
                    var_name = var_match.group(2)
                    observable_names.add(var_name)
        
        metrics.observable_state_vars = len(observable_names)
        metrics.observable_var_names = list(observable_names)
    
    def _analyze_state_updates(self, code: str, lines: List[str], metrics: StateMetrics):
        """Analyze state update operations"""

        # Track which lines we've already counted
        counted_lines = set()

        for line_num, line in enumerate(lines, 1):
            line_clean = line.strip()
            if not line_clean or line_clean.startswith('//'):
                continue

            if line_num in counted_lines:
                continue

            # Do nto count initializations (var name = ...) as updates
            if line_clean.startswith("var ") or line_clean.startswith("let "):
                continue

            # Remove string literals to reduce false positives
            line_clean = re.sub(r'".*?"', '', line_clean)

            # Use centralized mutation detection
            if self.detect_swift_mutations(line_clean):
                metrics.state_updates += 1
                metrics.state_update_lines.append((line_num, line_clean[:80]))
                counted_lines.add(line_num)
        
    


def analyze_file(filepath: str, language: str = 'auto') -> StateMetrics:
    """
    Analyze a source code file for state mutation metrics
    
    Args:
        filepath: Path to the source code file
        language: 'kotlin', 'swift', or 'auto' (auto-detect from extension)
    
    Returns:
        StateMetrics object
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
        analyzer = KotlinStateAnalyzer()
    elif language.lower() == 'swift':
        analyzer = SwiftStateAnalyzer()
    else:
        return StateMetrics(
            mutable_vars = float('nan'),
            immutable_vars = float('nan'),
            observable_state_vars = float('nan'),
            state_updates = float('nan'),
            total_lines = float('nan'),
            non_empty_lines = float('nan'),
            classes = float('nan'),
        )
    
    return analyzer.analyze(code)


def analyze_code_string(code: str, language: str) -> StateMetrics:
    """
    Analyze a code string for state mutation metrics
    
    Args:
        code: Source code as a string
        language: 'kotlin' or 'swift'
    
    Returns:
        StateMetrics object
    """
    if language.lower() == 'kotlin':
        analyzer = KotlinStateAnalyzer()
    elif language.lower() == 'swift':
        analyzer = SwiftStateAnalyzer()
    else:
        raise ValueError(f"Unsupported language: {language}")
    
    return analyzer.analyze(code)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python state_metrics.py <file_path> [language] [--verbose]")
        print("  language: 'kotlin', 'swift', or 'auto' (default: auto)")
        print("  --verbose: Show detailed findings")
        print("\nExample:")
        print("  python state_metrics.py MyView.kt")
        print("  python state_metrics.py MyView.swift --verbose")
        sys.exit(1)
    
    filepath = sys.argv[1]
    language = 'auto'
    verbose = False
    
    for arg in sys.argv[2:]:
        if arg == '--verbose':
            verbose = True
        else:
            language = arg
    
    try:
        metrics = analyze_file(filepath, language)
        print(f"File: {filepath}")
        print(metrics)
        
        if verbose:
            print("\nDetailed Findings:")
            print("=" * 60)
            
            if metrics.mutable_var_names:
                print(f"\nMutable variables ({len(metrics.mutable_var_names)}):")
                for name in metrics.mutable_var_names[:20]:  # Limit output
                    print(f"  - {name}")
                if len(metrics.mutable_var_names) > 20:
                    print(f"  ... and {len(metrics.mutable_var_names) - 20} more")
            
            if metrics.immutable_var_names:
                print(f"\nImmutable variables ({len(metrics.immutable_var_names)}):")
                for name in metrics.immutable_var_names[:20]:
                    print(f"  - {name}")
                if len(metrics.immutable_var_names) > 20:
                    print(f"  ... and {len(metrics.immutable_var_names) - 20} more")
            
            if metrics.observable_var_names:
                print(f"\nObservable state variables ({len(metrics.observable_var_names)}):")
                for name in metrics.observable_var_names:
                    print(f"  - {name}")
            
            if metrics.state_update_lines:
                print(f"\nState updates ({len(metrics.state_update_lines)}):")
                for line_num, line in metrics.state_update_lines[:20]:
                    print(f"  Line {line_num}: {line}")
                if len(metrics.state_update_lines) > 20:
                    print(f"  ... and {len(metrics.state_update_lines) - 20} more")
    
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)