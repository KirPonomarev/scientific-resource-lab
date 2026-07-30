# Market Integration

S20 implements only the SRF-side inactive Market bridge. It maps public-safe SRF
requests into C3 proposal intake envelopes and maps Market observation packets
back into `ScientificResultEnvelope/v1` without activating Market execution.

Boundaries:

- `activation_state=INACTIVE`
- `market_writes=0`
- `live_actions=0`
- `trading_allowed=false`
- `central_projector_required=true`
- `native_admission_required=true`

The bridge rejects trading/order language, private paths, D2/D3 material,
credentials, authority claims, duplicate observation imports and stale Market
HEAD bindings.

A19 adds the native closeout import projection. With no native Market closeout
present, SRF records `WAIT_NATIVE_CHILD_CLOSEOUT` and `WAIT_SRF` rather than
claiming global health. Current Market runtime health remains
`WAIT_RUNTIME_HEALTH:ORGANISM_RED` at native gate `F5/refresh_adapter`; this
parks Market activation and does not authorize trading, provider start, deploy,
restart, or any parent write into Market.
