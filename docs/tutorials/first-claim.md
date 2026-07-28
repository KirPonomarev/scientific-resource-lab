# Your first ScientificObjectEnvelope

A `ScientificObjectEnvelope/v1` is the base container for every SRL scientific
object. It carries identity (`object_id`), provenance (`created_utc`,
`parents`), a typed payload, and two safety consts (`canonical_writes=0`,
`grants_authority=false`). This tutorial mints an envelope around a synthetic
claim from `fixtures/public/`.

## 1. Load a synthetic claim

The synthetic claim fixtures are ordinary canonical JSON files. Load one as a
Python dict:

```python
from pathlib import Path
import json

claim = json.loads(Path("fixtures/public/claim-00.json").read_text())
```

## 2. Validate the claim payload

Before minting an envelope, validate the claim against both the JSON Schema
and the Python epistemic-invariant layer. This is defense in depth: the schema
checks structure, and `srl.semantic.claims` checks the SRL-specific rules such
as "a candidate hypothesis cannot declare itself supported without support."

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from srl.contracts.schema import validate as schema_validate
from srl.semantic.claims import validate as claim_validate

claim = json.loads(Path("fixtures/public/claim-00.json").read_text())
schema_validate(claim, "ScientificClaim")
claim_validate(claim)
print("claim payload is structurally valid and epistemically consistent")
PY
```

## 3. Mint the envelope

Use `srl.semantic.fabric.mint_object` to wrap the validated claim. The fabric
computes the content-addressed `object_id` over the canonical encoding of the
envelope *without* the id field, which avoids the self-hash problem.

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from srl.contracts.schema import validate as schema_validate
from srl.semantic.claims import validate as claim_validate
from srl.semantic.fabric import mint_object

claim = json.loads(Path("fixtures/public/claim-00.json").read_text())
schema_validate(claim, "ScientificClaim")
claim_validate(claim)

envelope = mint_object(
    object_type="claim",
    payload=claim,
    parents=[],
    created_utc="2026-07-28T00:00:00Z",
)

print(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
print("object_id:", envelope["object_id"])
PY
```

The printed object is a `ScientificObjectEnvelope/v1` with a real, computed
`object_id`. Because the input is a synthetic fixture, the result is safe to
share in logs, tests, and documentation.

## 4. Save and inspect the envelope

You can write the envelope to a file for later use:

```python
import json
from pathlib import Path

out = Path("synthetic-envelope-claim-00.json")
out.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n")
print(f"wrote {out}")
```

If you run the script twice, the `object_id` is identical because the input
claim and envelope fields are deterministic.

## 5. What the envelope proves

- **Admission, not truth**: a valid envelope means the object is well-formed
  and content-addressed. It does **not** mean the claim is scientifically true.
- **No authority**: `grants_authority` is always `false` for a scientific
  object.
- **Synthetic provenance**: the payload came from `fixtures/public/`, so no real
  data or human subject information is involved.

## Next steps

- Return to the [`quickstart.md`](quickstart.md) to validate the other fixtures.
- Read [`boundaries.md`](boundaries.md) to learn what must never enter the
  public repository.
