# AI-Driven File Modularization Prompt

## 🎯 Objective

Analyze the target file, understand its role in the ecosystem, and refactor it into a modular architecture where **every resulting file is under {MAX_LINES} lines** while maintaining **100% backwards compatibility**.

---

## 📋 Dynamic Configuration

```yaml
# Configure these variables for your specific context
TARGET_FILE: [INSERT FILE PATH HERE]
MAX_LINES: 500                    # Maximum lines per file (default: 500)
LANGUAGE: [auto-detect]           # Programming language (auto-detected from extension)
TEST_COMMAND: [auto-detect]       # Test runner command for the language
LINT_COMMAND: [auto-detect]       # Linter command for the language
TYPE_CHECK_COMMAND: [auto-detect] # Type checker command (if applicable)
```

### Language Auto-Detection Reference

| Extension | Language | Test Command | Lint Command | Type Check |
|-----------|----------|--------------|--------------|------------|
| `.py` | Python | `pytest` | `pylint`, `flake8` | `mypy` |
| `.ts`, `.tsx` | TypeScript | `jest`, `vitest` | `eslint` | `tsc --noEmit` |
| `.js`, `.jsx` | JavaScript | `jest`, `vitest` | `eslint` | N/A |
| `.go` | Go | `go test` | `golint`, `golangci-lint` | Built-in |
| `.rs` | Rust | `cargo test` | `clippy` | Built-in |
| `.java` | Java | `mvn test`, `gradle test` | `checkstyle` | Built-in |
| `.kt` | Kotlin | `gradle test` | `ktlint` | Built-in |
| `.rb` | Ruby | `rspec`, `minitest` | `rubocop` | `sorbet` |
| `.php` | PHP | `phpunit` | `phpcs`, `phpstan` | `psalm` |
| `.cs` | C# | `dotnet test` | `dotnet format` | Built-in |
| `.swift` | Swift | `swift test` | `swiftlint` | Built-in |
| `.scala` | Scala | `sbt test` | `scalafmt` | Built-in |
| `.ex`, `.exs` | Elixir | `mix test` | `credo` | `dialyzer` |
| `.clj` | Clojure | `lein test` | `clj-kondo` | N/A |
| `.hs` | Haskell | `stack test` | `hlint` | Built-in |
| `.cpp`, `.cc` | C++ | `ctest`, `gtest` | `clang-tidy` | N/A |
| `.c` | C | `ctest` | `clang-tidy` | N/A |

---

## 📋 Instructions for AI

### Phase 1: Deep Analysis (Understanding)

#### 1.1 File Analysis

**Analyze the target file:**
```
TARGET_FILE: {TARGET_FILE}
LANGUAGE: {LANGUAGE}
```

**Complete the following analysis:**

1. **Purpose & Responsibility**
   - What is the primary purpose of this file?
   - What business logic does it contain?
   - What are its main responsibilities?
   - Is it following Single Responsibility Principle?

2. **Dependencies Analysis**
   - What external modules/packages does it import?
   - What internal modules does it depend on?
   - Create a dependency graph showing:
     - Direct imports
     - Transitive dependencies
     - Circular dependencies (if any)

3. **Usage Analysis**
   - Where is this file imported/used in the codebase?
   - What functions/classes/exports are publicly accessible?
   - What is the public API surface?
   - Which parts are internal implementation details?
   - Generate a call graph showing all usages

4. **Complexity Metrics**
   - Total lines of code: [X]
   - Number of functions/methods: [X]
   - Number of classes/structs/types: [X]
   - Cyclomatic complexity per function
   - Cognitive complexity score
   - Code duplication percentage

5. **Code Structure**
   - List all functions/methods with line counts
   - List all classes/structs/types with line counts
   - Identify cohesive groups of related functionality
   - Identify cross-cutting concerns
   - Document data flow patterns

#### 1.2 Ecosystem Context

**Understand the broader context:**

1. **Module Placement**
   - What directory/package/namespace is this file in?
   - What is the architectural layer? (e.g., API, business logic, data access, utils)
   - What design patterns does it use? (Factory, Strategy, Repository, etc.)

2. **Integration Points**
   - HTTP/API endpoints (if route/controller)
   - Database queries (if data access)
   - External services (RPC calls, API calls)
   - Event emissions/subscriptions
   - File I/O operations
   - Message queues/streams

3. **State Management**
   - Does it maintain state? (global variables, class attributes, singletons)
   - What is the lifecycle of state?
   - Thread-safety/concurrency considerations
   - Caching mechanisms

4. **Error Handling**
   - What exceptions/errors does it raise?
   - What exceptions/errors does it catch?
   - Error propagation patterns

---

### Phase 2: Modularization Strategy (Planning)

#### 2.1 Identify Cohesive Modules

**Group related functionality into logical modules:**

1. **Apply Separation of Concerns**
   - **Data Access Layer:** Database queries, API calls, file I/O
   - **Business Logic Layer:** Core algorithms, validation, transformations
   - **Presentation Layer:** Formatting, serialization, response building
   - **Configuration:** Constants, settings, configuration
   - **Utilities:** Helper functions, shared utilities
   - **Types/Schemas/Models:** Type definitions, data models, interfaces

2. **Identify Module Boundaries**
   For each proposed module:
   - Module name
   - Responsibility (single sentence)
   - Public API (exported functions/classes/types)
   - Private implementation details
   - Dependencies on other new modules
   - Estimated line count (MUST be < {MAX_LINES})

3. **Create Module Dependency Graph**
   ```
   [Module A] --> [Module B] --> [Module C]
        |              |
        v              v
   [Module D]    [Module E]
   ```
   - Ensure no circular dependencies
   - Minimize coupling between modules
   - Maximize cohesion within modules

#### 2.2 File Structure Design

**Design the new directory structure based on language conventions:**

<details>
<summary><strong>Generic Template (Language-Agnostic)</strong></summary>

```
{original_file_location}/
├── index.{ext}              # Public API facade (< {MAX_LINES} lines)
├── core/
│   ├── index.{ext}
│   ├── module_a.{ext}       # Core functionality A (< {MAX_LINES} lines)
│   └── module_b.{ext}       # Core functionality B (< {MAX_LINES} lines)
├── services/
│   ├── index.{ext}
│   ├── service_x.{ext}      # Service layer X (< {MAX_LINES} lines)
│   └── service_y.{ext}      # Service layer Y (< {MAX_LINES} lines)
├── repositories/
│   ├── index.{ext}
│   └── data_repository.{ext} # Data access (< {MAX_LINES} lines)
├── models/
│   ├── index.{ext}
│   ├── request_models.{ext}  # Input models (< {MAX_LINES} lines)
│   └── response_models.{ext} # Output models (< {MAX_LINES} lines)
├── utils/
│   ├── index.{ext}
│   └── helpers.{ext}         # Utility functions (< {MAX_LINES} lines)
└── types/
    ├── index.{ext}
    └── custom_types.{ext}    # Type definitions (< {MAX_LINES} lines)
```

</details>

<details>
<summary><strong>Python Convention</strong></summary>

```
{module_name}/
├── __init__.py              # Public API facade
├── core/
│   ├── __init__.py
│   └── *.py
├── services/
│   ├── __init__.py
│   └── *.py
├── repositories/
│   ├── __init__.py
│   └── *.py
├── schemas/
│   ├── __init__.py
│   └── *.py
├── utils/
│   ├── __init__.py
│   └── *.py
└── types/
    ├── __init__.py
    └── *.py
```

</details>

<details>
<summary><strong>TypeScript/JavaScript Convention</strong></summary>

```
{module_name}/
├── index.ts                 # Public API facade (barrel exports)
├── core/
│   ├── index.ts
│   └── *.ts
├── services/
│   ├── index.ts
│   └── *.ts
├── repositories/
│   ├── index.ts
│   └── *.ts
├── models/
│   ├── index.ts
│   └── *.ts
├── utils/
│   ├── index.ts
│   └── *.ts
└── types/
    ├── index.ts
    └── *.ts
```

</details>

<details>
<summary><strong>Go Convention</strong></summary>

```
{package_name}/
├── {package_name}.go        # Public API facade
├── core.go                  # Core functionality
├── service.go               # Service layer
├── repository.go            # Data access
├── models.go                # Data models
├── utils.go                 # Utilities
└── types.go                 # Type definitions
```

</details>

<details>
<summary><strong>Rust Convention</strong></summary>

```
{module_name}/
├── mod.rs                   # Public API facade
├── lib.rs                   # Library root (if crate)
├── core/
│   ├── mod.rs
│   └── *.rs
├── services/
│   ├── mod.rs
│   └── *.rs
├── repositories/
│   ├── mod.rs
│   └── *.rs
├── models/
│   ├── mod.rs
│   └── *.rs
└── utils/
    ├── mod.rs
    └── *.rs
```

</details>

<details>
<summary><strong>Rust Best Practices (Detailed)</strong></summary>

### Module Declaration Patterns

**Modern Rust (2018+) - Preferred:**
```
src/
├── lib.rs                   # `mod ingestion;` declares module
├── ingestion/
│   ├── mod.rs               # Module root with re-exports
│   ├── engine.rs            # `pub mod engine;` in mod.rs
│   ├── processors/
│   │   ├── mod.rs
│   │   ├── audio.rs
│   │   └── text.rs
│   └── types.rs
```

**Legacy Pattern (avoid in new code):**
```
src/
├── lib.rs
├── ingestion.rs             # Module content in single file
```

### mod.rs Organization

**Structure your mod.rs files consistently:**
```rust
//! Module-level documentation
//! Describe the purpose and public API

// 1. Submodule declarations (private by default)
mod engine;
mod processors;
mod types;

// 2. Re-exports for public API (facade pattern)
pub use self::engine::{IngestionEngine, EngineConfig};
pub use self::processors::{AudioProcessor, TextProcessor};
pub use self::types::{IngestionResult, IngestionError};

// 3. Optional: Module-level items (keep minimal)
pub const DEFAULT_BATCH_SIZE: usize = 100;
```

### Visibility Best Practices

```rust
// Private (default) - only this module
fn internal_helper() {}

// Public to entire crate only
pub(crate) fn crate_helper() {}

// Public to parent module
pub(super) fn parent_visible() {}

// Public to specific path
pub(in crate::ingestion) fn ingestion_only() {}

// Fully public (external API)
pub fn public_api() {}
```

### Splitting Large Files - Step by Step

**Before (monolithic file > 500 lines):**
```rust
// src/ingestion.rs (800+ lines)
pub struct Engine { ... }
pub struct Config { ... }
pub struct AudioProcessor { ... }
pub struct TextProcessor { ... }
impl Engine { ... }  // 300 lines
impl AudioProcessor { ... }  // 200 lines
```

**After (modular structure):**
```
src/ingestion/
├── mod.rs              # Re-exports only (~30 lines)
├── engine.rs           # Engine struct + impl (~200 lines)
├── config.rs           # Config struct (~50 lines)
├── processors/
│   ├── mod.rs          # Re-export processors
│   ├── audio.rs        # AudioProcessor (~150 lines)
│   └── text.rs         # TextProcessor (~150 lines)
└── error.rs            # Error types (~50 lines)
```

### Re-export Patterns for Backwards Compatibility

```rust
// src/ingestion/mod.rs
mod engine;
mod config;
mod processors;
mod error;

// Flat re-export (original API preserved)
pub use self::engine::Engine;
pub use self::config::Config;
pub use self::processors::{AudioProcessor, TextProcessor};
pub use self::error::{IngestionError, Result};

// OR grouped re-export (more organized)
pub mod prelude {
    pub use super::engine::Engine;
    pub use super::config::Config;
    pub use super::error::Result;
}
```

### Type Organization Patterns

**Separate types by concern:**
```
src/ingestion/
├── types/
│   ├── mod.rs
│   ├── input.rs        # Input types, request DTOs
│   ├── output.rs       # Output types, response DTOs
│   └── internal.rs     # Internal types (pub(crate))
```

**Keep related types together:**
```rust
// src/ingestion/types/input.rs
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestionRequest {
    pub source: DataSource,
    pub options: ProcessingOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DataSource {
    File(PathBuf),
    Url(String),
    Raw(Vec<u8>),
}
```

### Trait Organization

**Traits in separate files when shared:**
```
src/
├── traits/
│   ├── mod.rs
│   ├── processor.rs    # trait Processor
│   └── storage.rs      # trait Storage
├── ingestion/
│   └── ... (implements Processor)
└── storage/
    └── ... (implements Storage)
```

**Traits inline when module-specific:**
```rust
// src/ingestion/processor.rs
pub trait Processor {
    type Input;
    type Output;
    type Error;

    fn process(&self, input: Self::Input) -> Result<Self::Output, Self::Error>;
}

// Implementations in same file if small, or separate files
impl Processor for AudioProcessor { ... }
```

### Error Type Organization

**Dedicated error module pattern:**
```rust
// src/ingestion/error.rs
use thiserror::Error;

#[derive(Debug, Error)]
pub enum IngestionError {
    #[error("Failed to read source: {0}")]
    ReadError(#[from] std::io::Error),

    #[error("Invalid format: {0}")]
    FormatError(String),

    #[error("Processing failed: {0}")]
    ProcessingError(#[source] Box<dyn std::error::Error + Send + Sync>),
}

pub type Result<T> = std::result::Result<T, IngestionError>;
```

### Feature-Gated Modules

```rust
// src/lib.rs
pub mod core;           // Always available

#[cfg(feature = "async")]
pub mod async_runtime;  // Only with "async" feature

#[cfg(feature = "gpu")]
pub mod gpu;            // Only with "gpu" feature

// Conditional re-exports
#[cfg(feature = "async")]
pub use async_runtime::AsyncEngine;
```

### Testing Module Organization

```rust
// src/ingestion/engine.rs
pub struct Engine { ... }

impl Engine {
    pub fn new(config: Config) -> Self { ... }
}

// Tests in same file for unit tests
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_engine_creation() { ... }
}
```

**Integration tests in separate directory:**
```
tests/
├── ingestion_integration.rs
└── common/
    └── mod.rs           # Shared test utilities
```

### Common Anti-Patterns to Avoid

```rust
// ❌ AVOID: God module with everything
pub mod everything {
    pub struct A { ... }
    pub struct B { ... }
    pub fn do_x() { ... }
    pub fn do_y() { ... }
    // 1000+ lines
}

// ❌ AVOID: Circular dependencies
// mod a uses mod b, mod b uses mod a

// ❌ AVOID: Deep nesting (>3-4 levels)
crate::a::b::c::d::e::Type

// ❌ AVOID: Wildcard re-exports hiding API surface
pub use self::internal::*;  // What's exposed?

// ✅ PREFER: Explicit re-exports
pub use self::internal::{TypeA, TypeB, function_c};
```

### Refactoring Checklist for Rust

1. **Identify cohesive groups** - types, impls, and functions that work together
2. **Extract to submodule** - create `module_name/` directory with `mod.rs`
3. **Move code** - relocate structs, impls, functions to appropriate files
4. **Update mod.rs** - add `mod` declarations and `pub use` re-exports
5. **Fix imports** - update `use` statements throughout codebase
6. **Run `cargo check`** - fix visibility and import errors
7. **Run `cargo test`** - ensure no regressions
8. **Run `cargo clippy`** - clean up any new warnings

### Line Count Validation for Rust

```bash
# Find Rust files over 500 lines
find src -name "*.rs" -exec wc -l {} + | \
  awk '$1 > 500 {print "⚠️ ", $0}' | sort -rn

# Verify all files under limit
find src -name "*.rs" -exec wc -l {} + | \
  awk -v max=500 '$1 > max && !/total/ {v=1; print "❌", $0}
  END {if(!v) print "✅ All Rust files under 500 lines"}'
```

</details>

<details>
<summary><strong>Java/Kotlin Convention</strong></summary>

```
{package}/
├── {ModuleName}.java        # Public API facade
├── core/
│   └── *.java
├── services/
│   └── *.java
├── repositories/
│   └── *.java
├── models/
│   ├── request/
│   │   └── *.java
│   └── response/
│       └── *.java
├── utils/
│   └── *.java
└── types/
    └── *.java
```

</details>

**For each file, specify:**
- File path
- Purpose
- Exported symbols
- Estimated line count (MUST be < {MAX_LINES})
- Dependencies

#### 2.3 Backwards Compatibility Strategy

**CRITICAL: Ensure zero breaking changes**

1. **Preserve Original Import/Include Paths**
   - The original file location MUST continue to work
   - All original imports MUST remain valid
   - All original exports MUST be accessible from the same path

2. **Create Facade/Proxy Pattern**
   - The original file becomes a thin facade that re-exports from new modules
   - All public functions/classes/types re-exported with same signatures
   - Maintain all type signatures exactly as they were

3. **Language-Specific Re-Export Patterns**

   **Python:**
   ```python
   # __init__.py - Re-export everything
   from .core.module_a import FunctionX, ClassY
   from .services.service_x import ServiceZ
   __all__ = ['FunctionX', 'ClassY', 'ServiceZ']
   ```

   **TypeScript/JavaScript:**
   ```typescript
   // index.ts - Barrel exports
   export { FunctionX, ClassY } from './core/module_a';
   export { ServiceZ } from './services/service_x';
   export * from './types';
   ```

   **Go:**
   ```go
   // Re-export via package-level variables/functions
   var FunctionX = core.FunctionX
   type ClassY = core.ClassY
   ```

   **Rust:**
   ```rust
   // mod.rs - Re-export with pub use
   pub use self::core::module_a::{FunctionX, ClassY};
   pub use self::services::service_x::ServiceZ;
   ```

4. **API Compatibility Checklist**
   - [ ] All public functions have identical signatures
   - [ ] All public classes/structs have identical constructors
   - [ ] All methods have identical signatures
   - [ ] All return types remain the same
   - [ ] All error/exception types remain the same
   - [ ] All default arguments/parameters preserved
   - [ ] All optional parameters preserved
   - [ ] All decorators/attributes/annotations preserved

---

### Phase 3: Implementation Plan (Execution)

#### 3.1 Step-by-Step Refactoring Plan

**Create a detailed, safe refactoring sequence:**

```
Step 1: Create Directory Structure
  - Create all new directories
  - Create all index/init files
  - No code moved yet
  - Verify structure matches language conventions

Step 2: Extract Types/Models (Least Dependencies)
  - Move type definitions to types/
  - Move data models to models/
  - Update imports in original file
  - Run tests: {TEST_COMMAND}

Step 3: Extract Utilities (Pure Functions)
  - Move helper functions to utils/
  - These should have no side effects
  - Update imports in original file
  - Run tests: {TEST_COMMAND}

Step 4: Extract Data Access Layer
  - Move database queries to repositories/
  - Move API calls to repositories/
  - Update imports in original file
  - Run tests: {TEST_COMMAND}

Step 5: Extract Business Logic
  - Move core algorithms to core/
  - Move validation logic to core/
  - Update imports in original file
  - Run tests: {TEST_COMMAND}

Step 6: Extract Service Layer
  - Move orchestration logic to services/
  - Move coordination logic to services/
  - Update imports in original file
  - Run tests: {TEST_COMMAND}

Step 7: Create Facade in Original File
  - Re-export all public APIs from new modules
  - Add backwards compatibility imports/exports
  - Ensure original file is now < 100 lines
  - Run ALL tests: {TEST_COMMAND}

Step 8: Validation
  - Run full test suite
  - Check all import paths still work
  - Verify no functionality broken
  - Run linter: {LINT_COMMAND}
  - Run type checker: {TYPE_CHECK_COMMAND}
  - Performance benchmarks (ensure no regression)
```

#### 3.2 Testing Strategy

**For each refactoring step:**

1. **Unit Tests**
   - All existing unit tests MUST pass without modification
   - Add new unit tests for new modules
   - Test each module in isolation

2. **Integration Tests**
   - All existing integration tests MUST pass without modification
   - Test interactions between new modules
   - Test backwards compatibility imports

3. **Import Path Tests**

   Verify both old and new import paths work:
   ```
   # Pseudocode - adapt to your language
   test_backwards_compatible_imports():
       # Old import path
       old_import = import("{original_path}", "FunctionX")
       assert old_import is not null

       # New import path
       new_import = import("{new_path}/core/module", "FunctionX")

       # Should be same implementation
       assert old_import == new_import
   ```

4. **Signature Compatibility Tests**

   Verify function signatures remain unchanged:
   ```
   # Pseudocode - adapt to your language
   test_function_signature_unchanged():
       old_signature = get_signature(old_function)
       new_signature = get_signature(new_function)
       assert old_signature == new_signature
   ```

---

### Phase 4: Output Specification

#### 4.1 Required Deliverables

**Provide the following outputs:**

1. **Analysis Document** (`docs/modularization/ANALYSIS_{FILENAME}.md`)
   - Complete analysis from Phase 1
   - Ecosystem context and dependencies
   - Current issues and technical debt identified

2. **Architecture Document** (`docs/modularization/ARCHITECTURE_{FILENAME}.md`)
   - Module breakdown with responsibilities
   - Directory structure diagram
   - Module dependency graph (Mermaid diagram)
   - Data flow diagrams

3. **Refactoring Plan** (`docs/modularization/REFACTORING_PLAN_{FILENAME}.md`)
   - Step-by-step implementation sequence
   - Risk assessment for each step
   - Rollback procedures
   - Testing checkpoints

4. **Code Implementation**
   - All new module files (< {MAX_LINES} lines each)
   - Updated original file (facade/proxy)
   - Migration guide for developers
   - Updated documentation

5. **Test Suite**
   - Backwards compatibility tests
   - New unit tests for each module
   - Integration tests
   - Import path validation tests

6. **Validation Report** (`docs/modularization/VALIDATION_{FILENAME}.md`)
   - Before/after metrics comparison
   - Test coverage report
   - Performance benchmarks
   - Breaking changes checklist (should be empty)

#### 4.2 Line Count Verification

**Every file MUST be validated:**

```
# Pseudocode - Language agnostic validation
function validate_line_counts(directory, max_lines = {MAX_LINES}):
    violations = []

    for file_path in get_source_files(directory):
        line_count = count_lines(file_path)
        if line_count > max_lines:
            violations.append({path: file_path, count: line_count})

    if violations.length > 0:
        print("❌ Line count violations:")
        for violation in violations:
            print(f"  {violation.path}: {violation.count} lines")
        return false

    print("✅ All files under {max_lines} lines")
    return true
```

**If any file exceeds {MAX_LINES} lines, further decompose it.**

---

### Phase 5: Quality Assurance

#### 5.1 Code Quality Metrics

**Verify improvements in:**

1. **Modularity**
   - Before: 1 file with X lines
   - After: N files, each < {MAX_LINES} lines
   - Coupling score (should decrease)
   - Cohesion score (should increase)

2. **Maintainability**
   - Cyclomatic complexity per function (should decrease)
   - Cognitive complexity (should decrease)
   - Code duplication (should decrease)

3. **Testability**
   - Test coverage % (should maintain or increase)
   - Number of unit tests (should increase)
   - Test execution time (should maintain or decrease)

#### 5.2 Backwards Compatibility Verification

**Run comprehensive checks:**

```bash
# 1. All tests pass
{TEST_COMMAND}

# 2. Import validation (language-specific)
# Verify original import paths still work

# 3. Type checking (if applicable)
{TYPE_CHECK_COMMAND}

# 4. Linting passes
{LINT_COMMAND}

# 5. No deprecation warnings in tests (optional)
{TEST_COMMAND} --fail-on-warnings
```

---

## 🛠️ Usage Instructions

### How to Use This Prompt

1. **Identify Target File**
   ```bash
   # Find large files (Unix/Linux/Mac)
   find . -name "*.{ext}" -exec wc -l {} + | sort -rn | head -20

   # PowerShell (Windows)
   Get-ChildItem -Recurse -Filter "*.{ext}" | ForEach-Object {
     [PSCustomObject]@{Lines=(Get-Content $_.FullName).Count; File=$_.FullName}
   } | Sort-Object Lines -Descending | Select-Object -First 20
   ```

2. **Configure Variables**
   Replace placeholders with actual values:
   ```yaml
   TARGET_FILE: src/api/routes/classify.py
   MAX_LINES: 500
   LANGUAGE: python
   TEST_COMMAND: pytest
   LINT_COMMAND: pylint
   TYPE_CHECK_COMMAND: mypy
   ```

3. **Run Analysis**
   Provide this prompt to AI with the target file

4. **Review Outputs**
   - Check analysis document for understanding
   - Review architecture design for soundness
   - Validate refactoring plan for safety

5. **Execute Refactoring**
   - Follow step-by-step plan
   - Run tests after each step
   - Commit frequently with clear messages

6. **Validate Results**
   - Run full test suite
   - Check line counts
   - Verify backwards compatibility
   - Review code quality metrics

---

## 📊 Example Output Format

### Example: Modularizing a Large File

**Analysis Summary:**
```
Original File: {TARGET_FILE} ({ORIGINAL_LINES} lines)
Language: {LANGUAGE}
Primary Purpose: [Detected purpose]
Dependencies: X external, Y internal
Public API: N exports
Issues: [Detected issues - mixed concerns, complexity, etc.]
```

**Proposed Structure:**
```
{module_name}/
├── index.{ext}                          # ~50 lines  - Facade, backwards compat
├── router.{ext}                         # ~150 lines - Route definitions
├── handlers/
│   ├── index.{ext}                      # ~15 lines
│   ├── primary_handler.{ext}            # ~200 lines - Request/response handling
│   └── validation_handler.{ext}         # ~100 lines - Input validation
├── services/
│   ├── index.{ext}                      # ~10 lines
│   ├── main_service.{ext}               # ~300 lines - Business logic
│   └── support_service.{ext}            # ~200 lines - Supporting logic
├── repositories/
│   ├── index.{ext}                      # ~10 lines
│   └── data_repository.{ext}            # ~180 lines - Data access
├── models/
│   ├── index.{ext}                      # ~20 lines
│   ├── request_models.{ext}             # ~150 lines - Request models
│   └── response_models.{ext}            # ~120 lines - Response models
├── utils/
│   ├── index.{ext}                      # ~10 lines
│   └── helpers.{ext}                    # ~200 lines - Utilities
└── types/
    ├── index.{ext}                      # ~5 lines
    └── custom_types.{ext}               # ~100 lines - Type definitions

Total Files: ~15-20
Longest File: <{MAX_LINES} lines ✅
Backwards Compatible: YES ✅
```

**Migration:**
```
# OLD (still works)
import { functionX, validateInput } from '{original_path}'

# NEW (preferred)
import { functionX } from '{new_path}/handlers'
import { validateInput } from '{new_path}/utils'
```

---

## ⚠️ Critical Requirements Checklist

Before marking refactoring as complete, verify:

- [ ] **Every new file is under {MAX_LINES} lines**
- [ ] **All existing tests pass without modification**
- [ ] **All original import paths still work** (backwards compatible)
- [ ] **No change in public API signatures** (functions, classes, methods)
- [ ] **No performance regression** (benchmark critical paths)
- [ ] **No new circular dependencies introduced**
- [ ] **All type annotations preserved** (if applicable)
- [ ] **Documentation updated** (docstrings, comments, README)
- [ ] **Code quality improved** (lower complexity, higher cohesion)
- [ ] **Test coverage maintained or increased**

---

## 🎯 Success Criteria

**The refactoring is successful when:**

1. ✅ Original file reduced from X lines to < 100 lines (facade only)
2. ✅ All new files are under {MAX_LINES} lines (HARD REQUIREMENT)
3. ✅ Zero breaking changes (100% backwards compatible)
4. ✅ All tests pass (existing + new tests)
5. ✅ Code quality metrics improved (lower complexity)
6. ✅ No performance degradation
7. ✅ Clear module boundaries with single responsibilities
8. ✅ Documentation updated and clear
9. ✅ Team review approved
10. ✅ Can be deployed without downtime

---

## 🔧 Universal Commands Reference

### Line Count Verification

**Unix/Linux/Mac:**
```bash
# Count lines in all source files
find {directory} -name "*.{ext}" -exec wc -l {} + | sort -n

# Verify all under limit
find {directory} -name "*.{ext}" -exec wc -l {} + | awk -v max={MAX_LINES} '$1 > max {print "❌", $0; found=1} END {if(!found) print "✅ All files under "max" lines"}'
```

**PowerShell (Windows):**
```powershell
# Count lines in all source files
Get-ChildItem -Recurse -Filter "*.{ext}" | ForEach-Object {
  [PSCustomObject]@{Lines=(Get-Content $_.FullName).Count; File=$_.FullName}
} | Sort-Object Lines

# Verify all under limit
$max = {MAX_LINES}
Get-ChildItem -Recurse -Filter "*.{ext}" | ForEach-Object {
  $lines = (Get-Content $_.FullName).Count
  if ($lines -gt $max) { Write-Host "❌ $($_.FullName): $lines lines" }
}
```

### Dependency Analysis

```bash
# Find all imports/usages of the target file
grep -r "import.*{module_name}" {src_directory}
grep -r "from.*{module_name}" {src_directory}
grep -r "require.*{module_name}" {src_directory}
```

### Testing

```bash
# Run test suite
{TEST_COMMAND}

# Run with coverage (tool varies by language)
{TEST_COMMAND} --coverage

# Type checking
{TYPE_CHECK_COMMAND}
```

### Code Quality

```bash
# Linting
{LINT_COMMAND} {directory}

# Complexity analysis (tool varies by language)
# Python: radon cc {directory} -a
# JS/TS: npx complexity-report {directory}
# Go: gocyclo {directory}
```

---

## 📝 Notes

- **Prioritize safety over speed** - Take time to ensure backwards compatibility
- **Test frequently** - Run tests after each extraction step
- **Commit atomically** - Each step should be a separate, reviewable commit
- **Document thoroughly** - Future developers need to understand the structure
- **Measure improvements** - Quantify the benefits (complexity, testability, etc.)
- **Get team review** - Large refactorings need peer validation
- **Monitor in production** - Watch for any unexpected issues after deployment
- **Adapt to conventions** - Follow your language/framework's idiomatic patterns

---

**Version:** 2.0
**Last Updated:** 2025-11-26
**Type:** Universal (Language-Agnostic)
