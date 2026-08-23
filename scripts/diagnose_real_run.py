import json
from src.object_state.observed_author_signature import ObservedDecisionEventV1
from src.workflow_action.observed_author_signature import _build_action_counts, _predict_author, _evaluate_selective

with open(".workspace_local/observed_events.json", "r", encoding="utf-8") as f:
    d = json.load(f)

events = [ObservedDecisionEventV1(**e) for e in d["events"]]
supp = [e for e in events if e.split == "support"]
hold = [e for e in events if e.split == "holdout"]

print(f"Loaded: supp={len(supp)}, hold={len(hold)}, authors={len({e.author_id for e in events})}")

author_counts = {}
for a in {e.author_id for e in events}:
    a_events = [e for e in supp if e.author_id == a]
    author_counts[a] = _build_action_counts(a_events)

supp_preds = [(e, *_predict_author(author_counts, e, 0.5)) for e in supp]
for cov in [0.6, 0.7, 0.8, 0.9, 1.0]:
    sel = _evaluate_selective(supp_preds, cov)
    print(f"cov={cov}: acc={sel['accuracy']:.4f}, risk={sel['selective_risk']:.4f}")

# Check action distribution
from collections import Counter
print("Support gold action distribution:", Counter(e.gold_action for e in supp))
print("Holdout gold action distribution:", Counter(e.gold_action for e in hold))
