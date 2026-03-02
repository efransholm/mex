## MEX

Repository for master thesis to calculate complexities

### How to run SonarQube

Move repo to repos folder and add file sonar-project.properties.
Run

```cmd
sonar-scanner
```

in terminal from the repo.

### Run Swift-complexity

Inside the swift-complexity folder run

```cmd
./.build/arm64-apple-macosx/release/SwiftComplexityCLI ~/Documents/mex/MEX/repos/swiftreponame --recursive
```

### Run Halstead metrics

```cmd
python3 scripts/halstead.py scripts/fibonacci.kt
```

### Run state analyzer

```cmd
python3 scripts/state.py "filepath" [language] [--verbose]
```
