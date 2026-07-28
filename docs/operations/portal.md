# Static Evidence Portal (WP-F52)

The static evidence portal turns a directory of SRL JSON objects into a small,
self-contained static website. It is designed for two very different audiences:
private local inspection and a public demo that may only show synthetic data.

## Modes

The portal is built by calling `build_portal(objects_dir, out_dir, mode)` with
one of two modes:

- `PortalMode.private_local` — renders every object that can be parsed. Use this
  on a trusted workstation to browse the full object graph, including objects
  that contain local paths or credentials. No demo watermark is added.
- `PortalMode.public_demo` — renders **only** objects that can be proven to
  derive from `fixtures/public/`, and **refuses** any object that contains an
  absolute local filesystem path or a credential-like pattern.

## Public-demo boundary rules

`public_demo` enforces two machine-checked rules on every input object:

1. **Leak detection.** Any string that matches an absolute local path
   (`/Users/...`, `/home/...`, `/etc/...`, Windows drive letters, etc.) or a
   credential keyword (`password`, `secret`, `token`, `api_key`, `private_key`,
   `bearer`, AWS key ids, `-----BEGIN`, etc.) causes the entire build to fail
   with a typed `PUBLIC_LEAK_DETECTED` refusal.
2. **Synthetic-only admission.** After leak scanning, only objects that carry
   a public provenance marker are accepted. Acceptable markers are:
   - a `"synthetic": true` field,
   - a `"license": "CC0-1.0"` field, or
   - any string value containing `fixtures/public/`.

Private-local mode performs neither check.

## Generated views

The generator emits the following HTML pages:

| Page | Purpose |
|------|---------|
| `index.html` | Capability/catalog index with links to every object |
| `obj_<id>.html` | Object detail (payload + parent links) |
| `lineage.html` | Transformation lineage with visible lossiness notes |
| `evidence.html` | 11-axis evidence matrix for assessments |
| `resources.html` | Run/engine resource usage |
| `interfaces.html` | Model interfaces; integration authority is always `none` |

## Watermark

Every page generated in `public_demo` mode contains a banner at the top:

```
DEMO — synthetic public data only
```

Private-local pages have no banner.

## Implementation constraints

- The generator uses only the Python standard library.
- Templates live in `portal/templates/` and are rendered with
  `string.Template`.
- All inserted text is escaped with a hand-rolled HTML escaper; a `<script>`
  payload appears as `&lt;script&gt;...` in the output.
- Generated pages contain no external CSS, JavaScript, images, fonts, or
  other network resources. The only `<style>` block is inline in `base.html`.

## Running the gate

```bash
python3 scripts/checks/wp52-gate.py
```

The gate emits a `GateReceipt/v1` JSON line and exits non-zero on failure.
