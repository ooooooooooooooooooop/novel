# Foundation v0.1

## 1. Project Definition

### One-line Goal
Build a narrative system for novels that can represent, maintain, advance, and review fictional story state.

### Core Position
This is not primarily a text generator.
It is a narrative state system.

### First Principle
The first-class entity of the system is not prose.
It is narrative state.

---

## 2. Scope

### In Scope
The foundation should define:
- core concepts
- data structures
- state transition logic
- review logic
- workflow skeletons
- example-driven validation

### Out of Scope
The foundation does not yet define:
- implementation details
- model providers
- prompt engineering strategy
- infrastructure
- evaluation automation
- production interface
- final prose optimization

---

## 3. System View

The system should be understood as:

**a rule-constrained, character-driven, state-transition-based narrative system that can be recorded and reviewed**

This means the system must support:
- representation of fictional facts
- tracking of runtime state
- modeling of character decisions
- controlled progression of plot
- review of consistency and progression quality

---

## 4. Core Objects

## 4.1 WorkSpec

### What it is
A top-level specification of what kind of work is being created.

### What it is not
It is not story content and not scene-level planning.

### It answers
What kind of novel is this supposed to become?

### Suggested contents
- genre
- subgenre
- audience
- theme
- tone
- pacing
- length target
- content constraints
- weight of romance / mystery / action / etc.

---

## 4.2 WorldModel

### What it is
A structured model of what is allowed, possible, costly, and forbidden in the fictional world.

### What it is not
It is not an encyclopedia of decorative lore.

### It answers
What can happen in this world, and at what cost?

### Suggested contents
- world facts
- social structure
- power system
- resource system
- geography
- factions
- time rules
- prohibitions
- consequence logic

---

## 4.3 CharacterModel

### What it is
A decision-capable model of a character.

### What it is not
It is not just a character bio.

### It answers
Given the current state, what would this character plausibly do?

### Suggested contents
- identity
- outer goal
- inner need
- fear
- flaw
- strength
- secret
- stance
- relationships
- growth stage
- knowledge state

---

## 4.4 NarrativeState

### What it is
The current runtime state of the story.

### What it is not
It is not a static setup file.

### It answers
Where is the story now?

### Suggested contents
- current time
- current location
- active characters
- current situation
- public information
- hidden information
- active suspense items
- active conflicts
- current goals

---

## 4.5 PlotUnit

### What it is
The minimal effective unit of narrative progression.

### What it is not
It is not just an event record or a paragraph of text.

### It answers
How does the story move from one state to another?

### Suggested contents
- level (book / arc / chapter / scene)
- goal
- participants
- conflict
- input state
- output state
- released information
- emotional shift
- hook
- consequences

### Validity rule
A PlotUnit is only considered effective if it changes state.

---

## 4.6 FactLedger

### What it is
A ledger of confirmed facts.

### What it is not
It is not interpretation or style.

### It answers
What has been established and cannot be casually contradicted?

### Suggested contents
- confirmed events
- confirmed relations
- confirmed rules
- confirmed objects / places / factions
- confirmed time order
- confirmed reveal status of secrets

---

## 4.7 ForeshadowGraph

### What it is
A structured tracker for promises, setups, mysteries, and payoffs.

### What it is not
It is not a loose note list.

### It answers
What narrative promises have been made, and what is their current status?

### Suggested contents
- setup point
- content
- visibility level
- expected payoff
- current status
- expiry risk
- transformed payoff status

---

## 4.8 ReviewIssue

### What it is
A record of narrative failure or concern detected during review.

### What it is not
It is not generic criticism.

### It answers
What is wrong, where, and how serious is it?

### Suggested contents
- issue type
- severity
- location
- scope of impact
- violated rule
- suggested fix
- resolution status

---

## 5. Object Relations

Recommended dependency order:

WorkSpec  
→ WorldModel + CharacterModel  
→ NarrativeState  
→ PlotUnit  
→ FactLedger + ForeshadowGraph  
→ ReviewIssue

### Meaning
- WorkSpec defines the direction.
- WorldModel and CharacterModel define the operating world.
- NarrativeState defines current runtime conditions.
- PlotUnit performs progression.
- FactLedger and ForeshadowGraph record what that progression established.
- ReviewIssue records where progression failed or weakened.

---

## 6. Information Layers

The system must distinguish three kinds of information.

## 6.1 Facts
Confirmed, stable, reviewable information.
Examples:
- age
- blood relation
- established rule
- event that already occurred

## 6.2 Inferences
Temporary or revisable interpretations derived from facts.
Examples:
- suspicion level
- emotional dependence
- probable hidden motive

## 6.3 Expression
The textual form used to present facts and inferences.
Examples:
- first-person narration
- restrained style
- indirect revelation by dialogue

### Rule
Facts are not the same as inference.
Inference is not the same as text.

---

## 7. State Transition Principle

The system should not treat novels as a simple sequence of events.

Instead, it should treat narrative as a chain of state transitions.

### Base formula
Input State + Character Decision + World Constraint + Conflict Pressure = Event = Output State

### Every PlotUnit should answer
1. What was the starting state?
2. Who made a decision?
3. What resistance or pressure was encountered?
4. What changed in the resulting state?

### Implication
If no meaningful state changes, progression is weak or invalid.

---

## 8. Legality

Narrative output should first be judged by legality before brilliance.

## 8.1 World Legality
Does the event violate world rules?

## 8.2 Character Legality
Does the behavior violate character logic without support?

## 8.3 Time Legality
Does it violate established temporal order?

## 8.4 Narrative Legality
Does it violate the rules of viewpoint or information release?

---

## 9. Memory Layers

The foundation should assume four memory categories.

## 9.1 Canon Memory
Stable, confirmed narrative facts.

## 9.2 Runtime State
Current situation and active pressures.

## 9.3 Summary Memory
Compressed history for long-range continuity.

## 9.4 Style Memory
Persistent narrative style and expression preferences.

---

## 10. Failure Types

The foundation should explicitly define failure.

## 10.1 Fact Conflict Failure
Contradiction with established facts.

## 10.2 Character Distortion Failure
Behavior inconsistent with character model.

## 10.3 World Violation Failure
Violation of world rules or consequence logic.

## 10.4 Weak Progression Failure
A unit does not create meaningful state change.

## 10.5 Promise Loss Failure
Foreshadowing, mystery, or narrative promise is forgotten.

## 10.6 Style Drift Failure
Expression drifts too far from intended narrative mode.

---

## 11. Review Priorities

Review should focus on five primary questions:

1. Did this content change state?
2. Is it consistent with the FactLedger?
3. Is it consistent with the CharacterModel?
4. Does it respect narrative promises and foreshadowing?
5. Does it serve the goal of the current narrative level?

---

## 12. Minimal Foundation Deliverables

The foundation phase is complete when the project has:

- a project brief
- a scope and boundaries file
- a glossary
- definitions for the 8 core objects
- field rules for hard / inferred / runtime data
- state transition rules
- review rules
- at least one mock case tying everything together

---

## 13. Summary

The foundation should define the novel system as:

**a maintainable, reviewable narrative operating system built on state, rules, transitions, and recorded commitments**

The goal of this phase is not to make the system write beautifully.
The goal is to make the system know what a valid story movement is.