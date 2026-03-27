from __future__ import annotations

"""
B5 — React Tactic Library

A tactic is a named, documented refactoring recipe for a specific React code smell.
The planner node (B4) picks a tactic by name; the edit node follows its rules;
the verifier enforces its invariants.

Each tactic dict has the following fields:
    name                  Unique identifier used by planner and prompts.
    display_name          Human-readable name for reports.
    applies_to_smells     List of smell types this tactic can fix.
    preconditions         Conditions that must be true before applying.
    edit_shape            What the edit actually does (concrete description).
    invariants            Behaviours that must not change after the edit.
    risks                 low | medium | high
    abort_if              Conditions under which the edit node must stop.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Tactic definitions
# ---------------------------------------------------------------------------

TACTICS: list[dict[str, Any]] = [

    # ── Large Component ──────────────────────────────────────────────────────

    {
        "name": "extract_component",
        "display_name": "Extract Component",
        "applies_to_smells": ["Large Component"],
        "preconditions": [
            "Component has a clearly separable JSX block with its own local concerns",
            "The block does not depend on more than 2-3 variables from the parent scope",
            "Extracted component can be rendered with explicit props (no implicit shared state)",
        ],
        "edit_shape": (
            "Identify one self-contained JSX block inside the large component. "
            "Move it into a new named component declared in the same file. "
            "Pass any required values as explicit props. "
            "Replace the original block with the new component usage."
        ),
        "invariants": [
            "Exported component name and its props API are unchanged",
            "Rendered output is identical",
            "No new files are created — new component lives in the same file",
        ],
        "risks": "medium",
        "abort_if": [
            "No clearly separable block exists",
            "The candidate block shares mutable state with sibling blocks",
            "Extraction would require passing more than 5 props to the new component",
        ],
    },

    {
        "name": "extract_logic_to_custom_hook",
        "display_name": "Extract Logic to Custom Hook",
        "applies_to_smells": ["Large Component"],
        "preconditions": [
            "Component contains useState/useEffect/useCallback logic not directly tied to JSX",
            "The logic group is cohesive and can be named meaningfully (e.g. useFormState)",
        ],
        "edit_shape": (
            "Move the cohesive stateful logic (useState, useEffect, handlers) into a "
            "custom hook declared in the same file. "
            "Return the values the component needs. "
            "Replace the inline logic in the component with a single hook call."
        ),
        "invariants": [
            "Exported component name and its props API are unchanged",
            "Component behaviour and side effects are identical",
            "Hook is declared in the same file (no new files)",
        ],
        "risks": "low",
        "abort_if": [
            "Logic is tightly coupled to JSX refs or DOM nodes",
            "Moving logic would require circular dependency between hook and component",
        ],
    },

    {
        "name": "split_component",
        "display_name": "Split Component",
        "applies_to_smells": ["Large Component", "Too Many Props"],
        "preconditions": [
            "Component has two or more distinct responsibilities with separate prop groups",
            "Each responsibility can be rendered independently",
        ],
        "edit_shape": (
            "Identify two distinct responsibility groups within the component. "
            "Create a focused sub-component for each group in the same file. "
            "The original component becomes a thin coordinator that composes them."
        ),
        "invariants": [
            "Exported component name and its props API are unchanged",
            "Rendered output is identical",
            "Sub-components are not exported (internal implementation detail)",
        ],
        "risks": "medium",
        "abort_if": [
            "Responsibilities share too much state to separate cleanly",
            "Split would result in more than 5 props being drilled through the coordinator",
            "Component is already at or below 80 lines",
        ],
    },

    # ── Uncontrolled Component ───────────────────────────────────────────────

    {
        "name": "add_controlled_state",
        "display_name": "Add Controlled State",
        "applies_to_smells": ["Uncontrolled Component"],
        "preconditions": [
            "Component contains <input>, <textarea>, or <select> without value + onChange",
            "The component owns (or can own) the input value in its own state",
        ],
        "edit_shape": (
            "Add a useState hook for each uncontrolled input's value. "
            "Add value={state} and onChange={e => setState(e.target.value)} to each input. "
            "If the form submits via e.target.value, replace with the state variable."
        ),
        "invariants": [
            "Form submission behaviour is preserved",
            "Props API of the component is unchanged",
            "No existing onChange handlers are removed",
        ],
        "risks": "low",
        "abort_if": [
            "Input value is intentionally read only on submit and controlling it would add unnecessary re-renders in a performance-critical form",
            "Input is inside a third-party form library that manages its own state",
        ],
    },

    # ── Duplicated Code ──────────────────────────────────────────────────────

    {
        "name": "extract_duplicated_logic_to_hook",
        "display_name": "Extract Duplicated Logic to Custom Hook",
        "applies_to_smells": ["Duplicated Code"],
        "preconditions": [
            "The same stateful logic pattern appears more than once in the file",
            "The duplicated logic is cohesive and can be abstracted with parameters",
        ],
        "edit_shape": (
            "Create a custom hook in the same file that accepts parameters for the "
            "varying parts. Replace each duplicated block with a call to the hook."
        ),
        "invariants": [
            "Behaviour of each usage site is identical to before",
            "No logic is silently dropped during extraction",
        ],
        "risks": "low",
        "abort_if": [
            "Duplicated blocks differ in too many details to share a hook signature",
            "Extraction would require more than 4 parameters",
        ],
    },

    {
        "name": "extract_duplicated_jsx_to_component",
        "display_name": "Extract Duplicated JSX to Component",
        "applies_to_smells": ["Duplicated Code"],
        "preconditions": [
            "The same JSX structure is repeated more than once",
            "The varying parts can be expressed as props",
        ],
        "edit_shape": (
            "Create a small shared component in the same file. "
            "Parameterise the varying parts as props. "
            "Replace each duplicate with the new component."
        ),
        "invariants": [
            "Rendered output is identical at each usage site",
            "Exported component API is unchanged",
        ],
        "risks": "low",
        "abort_if": [
            "Duplication is intentional for readability or differs enough that a shared component would be harder to read",
        ],
    },

    # ── Poor Names ───────────────────────────────────────────────────────────

    {
        "name": "rename_symbol",
        "display_name": "Rename Component / Prop / State",
        "applies_to_smells": ["Poor Names"],
        "preconditions": [
            "The symbol name is vague, misleading, or does not match its responsibility",
            "The rename is contained within the allowed file scope",
        ],
        "edit_shape": (
            "Rename the symbol to a clear, intention-revealing name. "
            "Update all references within the allowed files. "
            "Do not rename exported symbols if they are part of the public API."
        ),
        "invariants": [
            "Exported names that are part of the public API are unchanged",
            "Behaviour is unchanged — rename only",
        ],
        "risks": "low",
        "abort_if": [
            "The symbol is exported and used outside the allowed file scope",
            "Renaming would require changes in files outside the allowed scope",
        ],
    },

    # ── Dead Code ────────────────────────────────────────────────────────────

    {
        "name": "remove_unused_props",
        "display_name": "Remove Unused Props",
        "applies_to_smells": ["Dead Code", "Too Many Props"],
        "preconditions": [
            "One or more props are declared but never read inside the component",
            "The prop is not part of a spread (...rest) that is forwarded",
        ],
        "edit_shape": (
            "Remove each unused prop from the component's props destructuring. "
            "Remove its type annotation if present. "
            "Do not touch the call sites — callers passing extra props is harmless in React."
        ),
        "invariants": [
            "Component behaviour is unchanged",
            "Rendered output is identical",
            "No used props are accidentally removed",
        ],
        "risks": "low",
        "abort_if": [
            "Prop appears unused but is accessed via props spread or rest forwarding",
            "Prop is referenced in a dynamic key expression",
        ],
    },

    {
        "name": "remove_unused_state",
        "display_name": "Remove Unused State",
        "applies_to_smells": ["Dead Code"],
        "preconditions": [
            "A useState variable is declared but never read in JSX or logic",
            "The setter is not passed to children",
        ],
        "edit_shape": (
            "Remove the useState declaration for the unused variable. "
            "Remove any setter calls that only set the unused state."
        ),
        "invariants": [
            "Component behaviour is unchanged",
            "No side effects are removed accidentally",
        ],
        "risks": "low",
        "abort_if": [
            "State setter is passed as a prop to a child component",
            "State variable is referenced via a dynamic expression",
        ],
    },

    # ── Feature Envy ─────────────────────────────────────────────────────────

    {
        "name": "move_method_to_owner",
        "display_name": "Move Method to Owning Component",
        "applies_to_smells": ["Feature Envy"],
        "preconditions": [
            "A function inside the component primarily operates on data from a sibling or parent",
            "The function can be moved without creating circular dependencies",
        ],
        "edit_shape": (
            "Move the function to the component that owns the data it operates on. "
            "Pass any results back via props or callbacks as needed."
        ),
        "invariants": [
            "Behaviour is unchanged",
            "The receiving component's public API changes minimally",
        ],
        "risks": "medium",
        "abort_if": [
            "Moving the function requires changes outside the allowed file scope",
            "The function has complex dependencies on the current component's state",
        ],
    },

    # ── Poor Performance ─────────────────────────────────────────────────────

    {
        "name": "memoize_component",
        "display_name": "Memoize Component",
        "applies_to_smells": ["Poor Performance"],
        "preconditions": [
            "Component re-renders frequently with identical props",
            "Component is a function component (not a class component)",
        ],
        "edit_shape": (
            "Wrap the component export with React.memo(). "
            "Add useCallback to any handler functions passed as props to prevent "
            "reference inequality triggering child re-renders."
        ),
        "invariants": [
            "Component behaviour is identical",
            "Props API is unchanged",
        ],
        "risks": "low",
        "abort_if": [
            "Component relies on context values that change frequently (memo would not help)",
            "Component intentionally re-renders on every parent render",
        ],
    },

    {
        "name": "migrate_class_to_function",
        "display_name": "Migrate Class Component to Function Component",
        "applies_to_smells": ["Poor Performance"],
        "preconditions": [
            "Component is written as a class (extends React.Component or PureComponent)",
            "No lifecycle methods that have no hook equivalent are used",
        ],
        "edit_shape": (
            "Convert the class component to a function component. "
            "Replace this.state with useState hooks. "
            "Replace componentDidMount/componentDidUpdate with useEffect. "
            "Replace this.props references with function parameters."
        ),
        "invariants": [
            "Exported component name is unchanged",
            "Props API is unchanged",
            "Lifecycle behaviour is equivalent",
        ],
        "risks": "high",
        "abort_if": [
            "Component uses getSnapshotBeforeUpdate or componentDidCatch with no hook equivalent",
            "Component is subclassed elsewhere",
            "Component uses this.refs",
        ],
    },

    # ── Props in Initial State ───────────────────────────────────────────────

    {
        "name": "remove_props_in_initial_state",
        "display_name": "Remove Props in Initial State",
        "applies_to_smells": ["Props in Initial State"],
        "preconditions": [
            "A useState initialiser copies a prop value directly",
            "The component does not intentionally snapshot the prop at mount time",
        ],
        "edit_shape": (
            "Replace the useState with direct usage of the prop. "
            "If the component needs to track changes, derive the value from the prop "
            "using useMemo or use the prop directly in render."
        ),
        "invariants": [
            "Component reflects prop changes correctly",
            "Props API is unchanged",
        ],
        "risks": "medium",
        "abort_if": [
            "The component intentionally snapshots the prop at mount (e.g. an initial draft value)",
            "The state is mutated locally and must diverge from the prop",
        ],
    },

    # ── Direct DOM Manipulation ──────────────────────────────────────────────

    {
        "name": "remove_direct_dom",
        "display_name": "Remove Direct DOM Manipulation",
        "applies_to_smells": ["Direct DOM Manipulation"],
        "preconditions": [
            "Component uses document.getElementById, document.querySelector, or direct style mutation",
            "The manipulation can be replaced with a React ref or state-driven styling",
        ],
        "edit_shape": (
            "Replace document.getElementById / querySelector with a useRef attached to the element. "
            "Replace direct style mutation with state-driven className or inline style. "
            "Remove the imperative DOM call."
        ),
        "invariants": [
            "Visual and interactive behaviour is identical",
            "No accessibility attributes are lost",
        ],
        "risks": "medium",
        "abort_if": [
            "The DOM manipulation targets an element outside the component's render tree",
            "The manipulation is inside a third-party library callback that requires a raw DOM node",
        ],
    },

    # ── Force Update ─────────────────────────────────────────────────────────

    {
        "name": "remove_force_update",
        "display_name": "Remove forceUpdate / location.reload",
        "applies_to_smells": ["Force Update"],
        "preconditions": [
            "Component calls this.forceUpdate(), location.reload(), or router.reload()",
            "The re-render can be triggered by updating state instead",
        ],
        "edit_shape": (
            "Replace forceUpdate() with a setState call that triggers the needed re-render. "
            "Replace location.reload() / router.reload() with state or context updates "
            "that cause the affected components to re-render naturally."
        ),
        "invariants": [
            "The UI updates correctly after the triggering event",
            "No data is lost that the reload was preserving",
        ],
        "risks": "medium",
        "abort_if": [
            "The reload is required to re-initialise third-party scripts that cannot be reset via state",
            "The forceUpdate is inside a library integration that expects it",
        ],
    },

    # ── Inheritance Instead of Composition ───────────────────────────────────

    {
        "name": "use_composition",
        "display_name": "Use Composition Instead of Inheritance",
        "applies_to_smells": ["Inheritance Instead of Composition"],
        "preconditions": [
            "A React component class extends another custom component class",
            "The parent class is not a third-party base class (e.g. React.Component itself is fine to extend)",
        ],
        "edit_shape": (
            "Convert the parent class to a component that accepts children or a render prop. "
            "Replace the subclass with a component that composes the parent component "
            "and passes its additions via props or children."
        ),
        "invariants": [
            "Rendered output is identical",
            "Exported component names are unchanged",
        ],
        "risks": "high",
        "abort_if": [
            "The inheritance chain is more than 2 levels deep",
            "The parent class is from a third-party library",
            "Multiple components extend the same base — all would need to change",
        ],
    },

    # ── JSX Outside the Render Method ────────────────────────────────────────

    {
        "name": "extract_jsx_to_component",
        "display_name": "Extract JSX Outside Render to Component",
        "applies_to_smells": ["JSX Outside the Render Method"],
        "preconditions": [
            "JSX is returned from a regular method or function rather than the component body",
            "The JSX block is self-contained or can be passed data via arguments",
        ],
        "edit_shape": (
            "Move the JSX-returning method into a named sub-component declared in the same file. "
            "Pass required data as props. "
            "Call the sub-component in the render/return instead of the method."
        ),
        "invariants": [
            "Rendered output is identical",
            "Hooks rules are satisfied (no hooks inside non-component functions)",
        ],
        "risks": "low",
        "abort_if": [
            "The method is called conditionally with arguments that would make prop-passing complex",
            "The JSX block uses hooks — it must become a proper component, not just be moved",
        ],
    },

    # ── Conditional Rendering ────────────────────────────────────────────────

    {
        "name": "extract_conditional_render",
        "display_name": "Extract Conditional Render",
        "applies_to_smells": ["Conditional Rendering"],
        "preconditions": [
            "Component contains a complex conditional (nested ternaries or long && chains) in JSX",
            "The conditional block is large enough to obscure the surrounding render logic",
        ],
        "edit_shape": (
            "Extract the conditional block into a named sub-component or a clearly named "
            "const variable declared just above the return statement. "
            "The variable or component receives the condition and relevant data as inputs."
        ),
        "invariants": [
            "All conditional branches render identically to before",
            "Exported component API is unchanged",
        ],
        "risks": "low",
        "abort_if": [
            "The conditional is simple enough (single ternary) that extraction adds no clarity",
        ],
    },

    # ── No Access State in setState ──────────────────────────────────────────

    {
        "name": "use_functional_set_state",
        "display_name": "Replace setState with Functional Updater",
        "applies_to_smells": ["No Access State in setState()"],
        "preconditions": [
            "Component calls setState(value) where value is derived from the previous state",
            "This causes a stale closure or race condition risk",
        ],
        "edit_shape": (
            "Replace setState(derivedValue) with setState(prev => newValueFromPrev). "
            "Ensure the updater function is pure and derives only from prev state."
        ),
        "invariants": [
            "State transitions are semantically identical",
            "No other logic is changed",
        ],
        "risks": "low",
        "abort_if": [
            "The new value does not depend on previous state (no updater needed)",
        ],
    },

    # ── Direct Mutation of State ─────────────────────────────────────────────

    {
        "name": "replace_direct_state_mutation",
        "display_name": "Replace Direct State Mutation with setState",
        "applies_to_smells": ["Direct Mutation of State"],
        "preconditions": [
            "Component mutates state directly (e.g. this.state.x = value or array.push on state)",
            "The mutation can be replaced with an immutable update pattern",
        ],
        "edit_shape": (
            "Replace direct mutation with an immutable update: "
            "use spread for objects, concat/filter/map for arrays, "
            "then call setState / the state setter with the new value."
        ),
        "invariants": [
            "State transitions produce identical results",
            "React re-renders are correctly triggered",
        ],
        "risks": "low",
        "abort_if": [
            "The state object is deeply nested and immutable update would be excessively complex",
        ],
    },

    # ── Dependency Smell ─────────────────────────────────────────────────────

    {
        "name": "replace_third_party_with_own",
        "display_name": "Replace Third-Party Component with Own Implementation",
        "applies_to_smells": ["Dependency Smell"],
        "preconditions": [
            "A third-party component is used for a simple UI pattern the team can own",
            "The replacement is within the allowed file scope",
        ],
        "edit_shape": (
            "Implement the simple UI pattern inline or as a local component. "
            "Remove the third-party import. "
            "Ensure the replacement is visually and behaviourally equivalent."
        ),
        "invariants": [
            "Visual output is identical",
            "Accessibility attributes are preserved",
        ],
        "risks": "high",
        "abort_if": [
            "The third-party component provides complex accessibility or keyboard behaviour",
            "Replacement would require significant new code beyond the allowed scope",
        ],
    },

    # ── Low Cohesion ─────────────────────────────────────────────────────────

    {
        "name": "extract_cohesive_component",
        "display_name": "Extract Cohesive Component",
        "applies_to_smells": ["Low Cohesion"],
        "preconditions": [
            "Component handles multiple unrelated responsibilities in the same render",
            "One responsibility can be fully encapsulated with its own props",
        ],
        "edit_shape": (
            "Identify the least cohesive section of the component. "
            "Extract it into a focused named component in the same file. "
            "The original component delegates to the extracted one via props."
        ),
        "invariants": [
            "Exported component name and props API are unchanged",
            "Rendered output is identical",
        ],
        "risks": "medium",
        "abort_if": [
            "All sections share the same state and cannot be separated without lifting state",
            "Component is already small (under 60 lines)",
        ],
    },

    # ── Prop Drilling ────────────────────────────────────────────────────────

    {
        "name": "extract_to_context",
        "display_name": "Extract Prop Drilling to Context",
        "applies_to_smells": ["Prop Drilling"],
        "preconditions": [
            "A prop is passed through 2+ intermediate components that do not use it",
            "The prop represents shared state relevant to a subtree",
        ],
        "edit_shape": (
            "Create a React context in the same file. "
            "Provide the value at the top of the subtree. "
            "Replace the prop drilling chain with useContext calls in the consuming components."
        ),
        "invariants": [
            "Consuming components receive the same value as before",
            "The provider wraps the same component subtree",
        ],
        "risks": "medium",
        "abort_if": [
            "The intermediate components are outside the allowed file scope",
            "The prop changes frequently and context would cause excessive re-renders",
        ],
    },

]

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# Index by tactic name for O(1) lookup
_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in TACTICS}

# Index by smell type for quick planner lookup
_BY_SMELL: dict[str, list[dict[str, Any]]] = {}
for _tactic in TACTICS:
    for _smell in _tactic["applies_to_smells"]:
        _BY_SMELL.setdefault(_smell, []).append(_tactic)


def get_tactic(name: str) -> dict[str, Any] | None:
    """Return the tactic dict for a given name, or None if not found."""
    return _BY_NAME.get(name)


def get_tactics_for_smell(smell_type: str) -> list[dict[str, Any]]:
    """Return all tactics that apply to a given smell type (may be empty)."""
    return _BY_SMELL.get(smell_type, [])


def tactic_names_for_smell(smell_type: str) -> list[str]:
    """Return just the tactic names for a smell type — useful for prompts."""
    return [t["name"] for t in get_tactics_for_smell(smell_type)]


def all_covered_smell_types() -> list[str]:
    """Return all smell types that have at least one tactic defined."""
    return sorted(_BY_SMELL.keys())
