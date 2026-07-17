# R2-S1 D3 Retrieved-Content Guard Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a deterministic, bounded, fail-closed retrieved-content detector without connecting it to retrieval, Controller, generation, API routes, or live models.

**Architecture:** A strict Pydantic `GuardDecision` domain model prevents invalid ADMIT/QUARANTINE states. `RetrievedContentGuard.scan()` creates ephemeral bounded detection views, applies versioned rule families, performs at most one bounded Base64 decode per candidate, and returns content-free diagnostics. D4 will own Search/Open projection, same-document split aggregation, guarded execution types, and candidate top-up because those operations require ACL-visible retrieval context.

**Tech Stack:** Python 3.11, Pydantic 2, standard-library `base64`, `hashlib`, `re`, and `unicodedata`, pytest 9.

## Global Constraints

- Follow strict RED -> verify expected failure -> GREEN -> verify pass -> REFACTOR.
- Do not use an LLM detector or make any model/network call.
- Do not add third-party dependencies.
- Do not mutate original content or return original, normalized, or decoded text in `GuardDecision`.
- Scan at most 20,000 source characters: 14,000 prefix plus 6,000 suffix.
- Inspect at most 8 Base64 candidates, encoded length 16..4096, decoded bytes at most 3072, one decode level, printable threshold 0.70.
- Invalid Base64 is ordinary text; an unexpected detector exception is `RCG-GUARD-ERROR` and QUARANTINE.
- Rules are category/ID based and use signal combinations; never hardcode a complete test payload.
- Security-training quotes, role/API documentation, legitimate encoding, and ordinary business SOP language remain admitted in the D3 fixed benign controls.
- Do not modify R1 frozen data or the D2 raw baseline tests.
- Keep D2 integration failures red until D4; D3 does not claim enforcement.

---

### Task 1: GuardDecision Domain Contract

**Files:**
- Create: `app/domain/retrieved_security.py`
- Create: `tests/security/test_retrieved_content_guard.py`

**Interfaces:**
- Produces: `GuardDecision`, `GuardDisposition`, `GuardSeverity`, `RiskCategory`, `DETECTOR_VERSION`, and frozen resource constants.
- Consumed by: `app/security/retrieved_content.py` in Task 2.

- [x] **Step 1: Write failing schema tests**

Tests construct valid clean, observe, quarantine, and guard-error decisions and reject:

```python
GuardDecision(
    disposition="ADMIT",
    max_severity="quarantine",
    risk_categories=["instruction_override"],
    rule_ids=["RCG-INSTRUCTION-OVERRIDE-001"],
    detector_version=DETECTOR_VERSION,
    original_length=10,
    normalized_length=10,
    scanned_length=10,
    decoded_view_count=0,
    guard_error=False,
)
```

The suite also rejects duplicate/unsorted categories or IDs, missing QUARANTINE diagnostics, invalid guard-error combinations, and numeric values above frozen bounds.

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\security\test_retrieved_content_guard.py -k decision
```

Expected: collection/import failure because `app.domain.retrieved_security` does not exist.

- [x] **Step 3: Implement the minimal strict schema**

Use `extra="forbid"`, literal enums, field validators, and a model validator. Required invariants:

```text
ADMIT + none       => no categories/rules and guard_error=false
ADMIT + observe    => diagnostics allowed, guard_error=false
QUARANTINE         => severity quarantine/error plus categories/rules
guard_error=true   => exact guard_error category/rule, severity error
scanned_length     <= min(original_length, 20000)
normalized_length  <= 20000
decoded_view_count <= 8
```

- [x] **Step 4: Verify GREEN**

Run the Task 1 command. Expected: all selected decision tests pass.

### Task 2: Normalization and Atomic Rule Families

**Files:**
- Create: `app/security/retrieved_content.py`
- Modify: `app/security/__init__.py`
- Modify: `tests/security/test_retrieved_content_guard.py`

**Interfaces:**
- Produces: `RetrievedContentGuard.scan(content: object) -> GuardDecision` and `RULE_SET_SHA256`.
- Consumes: strict domain types and constants from Task 1.

- [x] **Step 1: Write failing attack and benign-control tests**

Attack cases cover:

```text
English/Chinese instruction override
forged SYSTEM/ASSISTANT role plus action
system-prompt/canary extraction
model-directed or sensitive-data egress
NFKC full-width bypass
zero-width directive bypass
bidi control
HTML/comment/code wrapper around a directive
```

Benign controls cover:

```text
quoted security-training attack example
SYSTEM/ASSISTANT API documentation without an instruction
legitimate hash/Base64 identifier
approved business upload URL SOP without model/secret targeting
Chinese quoted security-training example
```

Tests assert exact disposition, category, stable rule ID, lengths, version, and that serialized decisions contain no canary or attack text.

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\security\test_retrieved_content_guard.py -k "atomic or benign or unicode or markup"
```

Expected: import/attribute failures because `RetrievedContentGuard` is absent.

- [x] **Step 3: Implement bounded views and rules**

Implementation units:

```text
_bounded_window          source prefix/suffix and scanned count
_build_detection_view   NFKC, casefold, zero-width removal, limited confusables
_RuleMatch              static category/rule/severity/span only
_scan_non_encoded       pair/structure rules within bounded proximity
_is_descriptive_quote   suppress only framed quoted/code examples
_markup_signal          add wrapper rule only around an active risky match
_decision_from_matches  sorted content-free GuardDecision
```

Rule families use stable IDs under:

```text
RCG-INSTRUCTION-*
RCG-ROLE-*
RCG-SECRET-*
RCG-EGRESS-*
RCG-INVISIBLE-*
RCG-MARKUP-*
```

`RULE_SET_SHA256` hashes canonical detector version, resource constants, rule IDs, categories, severities, and regex sources. It is diagnostic provenance, not a content fingerprint.

- [x] **Step 4: Verify GREEN and refactor**

Run the Task 2 command, then the entire Guard test file. Expected: all implemented atomic and benign cases pass.

### Task 3: Bounded Base64, Resource Limits, and Fail-Closed

**Files:**
- Modify: `app/security/retrieved_content.py`
- Modify: `tests/security/test_retrieved_content_guard.py`

**Interfaces:**
- Extends: `RetrievedContentGuard.scan()` with bounded one-level decoded views and safe error decisions.

- [x] **Step 1: Write failing Base64 tests**

Tests require:

```text
encoded English directive quarantined
encoded Chinese directive quarantined
legitimate encoded identifier admitted
invalid candidate admitted unless another rule fires
nested encoding not recursively decoded
no more than 8 decoded views
decoded payload above the fixed limit not scanned
```

- [x] **Step 2: Verify Base64 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\security\test_retrieved_content_guard.py -k base64
```

Expected: encoded attack cases remain ADMIT or decoded counts are absent/wrong.

- [x] **Step 3: Implement minimal bounded decode**

Discover regex-delimited candidates in order, stop after 8, validate alphabet/padding with `base64.b64decode(..., validate=True)`, reject decoded size above 3072, apply the 0.70 printable threshold, scan decoded text with Base64 discovery disabled, and add `RCG-BASE64-DECODED-001` only when a decoded view has a quarantine signal.

- [x] **Step 4: Verify Base64 GREEN**

Run the Task 3 Base64 command. Expected: all Base64 tests pass with `decoded_view_count <= 8`.

- [x] **Step 5: Write failing resource/fail-closed tests**

Tests require:

```text
oversized text scans exactly 14000 prefix + 6000 suffix
suffix attack is detected
non-string content becomes content-free guard error
unexpected internal scanner exception becomes content-free guard error
input string remains byte-for-byte unchanged
```

- [x] **Step 6: Verify resource/fail-closed RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\security\test_retrieved_content_guard.py -k "resource or fail_closed or immutable"
```

Expected: at least the injected internal exception escapes or length accounting fails.

- [x] **Step 7: Implement fail-closed wrapper and verify GREEN**

`scan()` catches unexpected per-item failures and returns the exact `RCG-GUARD-ERROR` decision without exception text, content, type repr, or traceback. Run the entire Guard test file and expect zero failures.

### Task 4: D3 Regression and Evidence Closeout

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/security/r2_s1/05_results.md`
- Modify: `docs/roadmap/r2_s1_indirect_injection_implementation.md`

**Interfaces:**
- Records: exact D3 test counts, detector version/hash, limits, false-positive controls, remaining D2 integration failures, and D4 gate.

- [x] **Step 1: Run fresh verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\security\test_retrieved_content_guard.py
.\.venv\Scripts\python.exe -m pytest -q tests\security --ignore=tests\security\test_indirect_injection_red_baseline.py
.\.venv\Scripts\python.exe -m pytest -q tests\agent_v2 tests\retrieval --ignore=tests\retrieval\test_indirect_injection_red_baseline.py
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
```

Also re-run the D2 red files separately. Expected: the same five integration failures remain because D4 has not connected the Guard; the three existing boundaries remain green.

- [x] **Step 2: Recheck immutable scope**

Verify exact R1 hashes, `git diff --check`, no changes under `data/v2/eval`, no live model process started by D3, and no external-network command.

- [x] **Step 3: Update public evidence honestly**

State `Guard core unit-tested; enforcement integration NOT RUN`. Do not claim retrieved-content defense, OFF/ON metrics, full fixture-set results, or live-model resistance.

- [x] **Step 4: Commit exact D3 files locally**

Use the phase message:

```text
feat: add deterministic retrieved-content guard core
```

Do not stage `.superpowers/`, private raw outputs, R1 data, or unrelated files. Do not push. Stop for:

```text
批准D3，执行D4数据流接入与能力约束
```
