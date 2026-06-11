# Fused Graph Report (codegraph substrate + graphify overlay)

- nodes: 857  edges: 1908  communities: 27
- adapter stats: {'cg_nodes': 858, 'composite_nodes': 857, 'merges': 1, 'edges_in': 1694, 'edges_out': 1694, 'unmapped_edges': 0, 'kind_dist': {'class': 4, 'method': 11, 'function': 526, 'file': 56, 'import': 194, 'variable': 49, 'constant': 17}, 'pyast_call_edges': 382, 'pyast_ref_edges': 164, 'pyast_exports_stamped': 18}

## God nodes

- **main** (degree 19) `cg:4b1559b6f6e0f7ea`
- **resolve** (degree 17) `cg:75637ed541aa7ba9`
- **AdaptResult** (degree 13) `cg:85c9d5757530c188`
- **build_repo** (degree 12) `cg:164a13d5b9250633`
- **health** (degree 12) `cg:fe3f8dd8bc1ea820`
- **_init** (degree 10) `cg:e088c0baf177a262`
- **materialize** (degree 9) `cg:663c5cfd8b221c7b`
- **visit** (degree 8) `cg:0e178b2e6dfd5890`
- **analyze** (degree 8) `cg:e313e80a80f808d4`
- **build_digraph** (degree 7) `cg:ab8e704b83711a21`
- **_semantic_merge** (degree 7) `cg:ace5dbd5b16b7cee`
- **_adapt_repo** (degree 7) `cg:b8342ab2a94d09a7`
- **_query_cmd** (degree 7) `cg:c38cfe22f0d77c40`
- **compute_status** (degree 7) `cg:e7a781fb1be06490`
- **_traverse** (degree 7) `cg:f4c94ff00d911c15`

## Surprising connections

- _label_index ↔ AdaptResult
- _traverse ↔ build_digraph
- build_fused ↔ adapt
- build_fused ↔ fold_singleton_communities
- build_fused ↔ prune_orphans
- curated_nodes ↔ AdaptResult
- dispatch_candidates ↔ dead_code
- health ↔ analyze
- merge_payloads ↔ AdaptResult
- merge_semantic ↔ AdaptResult
