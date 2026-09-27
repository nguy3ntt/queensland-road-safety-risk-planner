# Milestone 4 Graph Construction and Validation

## Construction contract

The road graph is the Milestone 2 topology for network
`qrt_state_controlled_2026_09_26`. A node is one official state-controlled road segment. An
undirected edge exists only when two segment geometries share a projected endpoint after the
configured 1 m EPSG:9473 endpoint clustering rule. No crash outcome, future label or model score is
used to create an edge.

For modelling, every undirected pair is expanded into two message directions. Each segment receives
the mean of its available one-hop neighbours' causal temporal, exposure and static fields. Isolated
or unavailable neighbours contribute zeros plus an explicit neighbour-count and coverage field.

## Saved graph audit

| Check | Observed |
|---|---:|
| Nodes | 48,759 |
| Undirected edges | 59,756 |
| Directed message edges | 119,512 |
| Connected components | 24 |
| Isolated segments | 16 |
| Mean degree | 2.451 |
| Maximum degree | 8 |
| Self-loops | 0 |
| Duplicate undirected pairs | 0 |
| Unknown segment references | 0 |
| Saved-degree mismatches | 0 |

## Leakage controls

- Message fields are allow-listed in configuration; any field containing `next_1q` is rejected.
- Feature timestamps are checked against the prediction cutoff before aggregation.
- Train, calibration and test graph summaries are built separately.
- The Brisbane transfer fold removes held-out nodes from fitting and calibration messages.
- Test messages are also restricted to the held-out Brisbane subgraph; 69 topology edges crossing
  the Brisbane boundary do not pass information across the split.
- Preprocessing is fitted on training rows only. Calibration is fitted on the later calibration
  block and never on test outcomes.

## Important limitations

The topology is a current road snapshot used retrospectively. It does not prove that every endpoint
or segment existed unchanged in earlier years. Endpoint adjacency is also a coarse proxy for travel
interaction: it does not encode turn legality, direction, lane connectivity or traffic flow. The
one-hop mean treats all retained neighbours equally. Milestone 4 tests the value of this bounded,
auditable graph representation; it does not validate richer transport-network semantics.
