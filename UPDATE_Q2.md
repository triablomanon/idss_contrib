**Updated files:** `idss_agent/workflows/interview.py`, `config/prompts/interview_system.j2`

## Summary
Refactored the Interview Agent to a state-aware, goal-oriented workflow. The system now utilizes a "gap analysis" to calculate missing requirements against a strict schema before generating queries. This eliminates redundant questioning.

## Core Architectural Changes

### 1. Gap Analysis Engine (`interview.py`)
Replaced arbitrary conversation flow with a check against required specifications.
- **Mechanism:** `Required Fields - Extracted Fields = Missing Info`
- **Implementation:** Introduced `REQUIRED_SPECS_MAP` to define strict necessity for each component type (e.g., GPU requires `resolution` + `psu_wattage`).
- **Result:** Agent only queries for `Null` fields in the state, ensuring zero redundancy.

### 2. Dynamic State Injection
Upgraded the prompt rendering pipeline to inject real-time state awareness directly into the context window.
- **Before:** Static system prompt relying on LLM to infer context from chat history.
- **After:** Dynamic injection of `{{ known_info_summary }}` and `{{ missing_critical_info }}` variables.
- **Guardrails:** The LLM is explicitly instructed to ignore fields present in `known_info_summary`.

### 3. Prompt Engineering Overhaul
Removed legacy "automotive" domain artifacts (references to fuel efficiency, commuting, etc.) from `interview_system.j2`.
- **Domain Alignment:** Rewrote instructions to focus strictly on PC hardware attributes (Resolution, FPS targets, VRAM).
- **Batching:** Enforced multi-questioning in a single turn to reduce conversation length.

## Modified:

- **`idss_agent/workflows/interview.py`**:
    - Added `REQUIRED_SPECS_MAP` heuristic.
    - Implemented `get_missing_requirements()` logic.
    - Removed old interview logic.
- **`config/prompts/interview_system.j2`**:
    - Complete rewrite for PC domain.
    - Added Jinja2 variable hooks for state injection.
- **`idss_agent/utils/prompts.py`**:
    - Updated `render_prompt` signature to accept `**kwargs` for dynamic context passing.