# test-cases/ — the authored test tier

Two kinds of test case live here, and the split is what makes them navigable.

```
test-cases/
  global/     the fixed 22 checks, run against every endpoint on every run
  endpoint/   per-endpoint cases, run only when that endpoint runs
```

`global/` is populated in **Phase 4**, by splitting
`tests/global_contract/test_global_api_contract.py` into one file per check. It is
empty until then.

`endpoint/<slug>/` exists now: 41 directories, one per endpoint, each with a README
naming what covers that endpoint today and where it currently lives.

## What must never write here

Nothing. Every file here is hand-authored. Generated tests live in
`tests/auto_generated/`, which is regenerated wholesale and must never hold authored
content — a regeneration would destroy it.

## Adding an endpoint-specific case

One Python file per case, `<NN>_<case_title>.py`, in the endpoint's directory. Number
it after the highest existing file.

The 22 global checks already run against every endpoint. Add a case here only for
behaviour specific to *this* endpoint — a business rule, a workflow dependency, an
edge case the contract tier cannot express.

State in the docstring what the case asserts and which result state it emits on
failure. The seven-state model is load-bearing: a request that ran but asserted
nothing must report `NOT_ASSERTED`, never `PASS`.

## The honest gap

After Phase 4, endpoint-specific **business-rule** tests still live in the Postman
collections under `collections/`, not here. Migrating them is Phase 5, which is
explicitly out of scope for this window — it depends on redesigning token-chaining
and would break the harness auth-provider filter in the same change.

Each `endpoint/<slug>/README.md` names where that endpoint's Newman coverage lives, so
the gap is visible rather than papered over.
