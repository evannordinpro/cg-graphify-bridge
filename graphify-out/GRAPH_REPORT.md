# Fused Graph Report (codegraph substrate + graphify overlay)

- nodes: 807  edges: 1671  communities: 28
- adapter stats: {'cg_nodes': 808, 'composite_nodes': 807, 'merges': 1, 'edges_in': 1569, 'edges_out': 1569, 'unmapped_edges': 0, 'kind_dist': {'class': 4, 'method': 6, 'function': 504, 'file': 53, 'import': 178, 'variable': 45, 'constant': 17}, 'pyast_call_edges': 391}

## God nodes

- **resolve** (degree 17) `cg:75637ed541aa7ba9`
- **build_repo** (degree 12) `cg:164a13d5b9250633`
- **health** (degree 10) `cg:fe3f8dd8bc1ea820`
- **materialize** (degree 9) `cg:663c5cfd8b221c7b`
- **_init** (degree 9) `cg:e088c0baf177a262`
- **visit** (degree 8) `cg:0e178b2e6dfd5890`
- **analyze** (degree 8) `cg:e313e80a80f808d4`
- **build_digraph** (degree 7) `cg:ab8e704b83711a21`
- **_adapt_repo** (degree 7) `cg:b8342ab2a94d09a7`
- **compute_status** (degree 7) `cg:e7a781fb1be06490`
- **_traverse** (degree 7) `cg:f4c94ff00d911c15`
- **benchmark** (degree 6) `cg:8561c5dad12527dd`
- **build_fused** (degree 6) `cg:aad5f15d80bae04e`
- **_semantic_merge** (degree 6) `cg:ace5dbd5b16b7cee`
- **AdaptResult** (degree 5) `cg:85c9d5757530c188`

## Surprising connections

- _build ↔ resolve
- _materialize ↔ materialize
- _serve ↔ materialize
- benchmark ↔ read_layer
- build_fused ↔ analysis_view
- build_fused ↔ fold_singleton_communities
- build_fused ↔ prune_orphans
- build_repo ↔ check_engine_compat
- build_repo ↔ check_substrate_drift
- health ↔ analyze
