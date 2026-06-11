# Fused Graph Report (codegraph substrate + graphify overlay)

- nodes: 893  edges: 2013  communities: 26
- adapter stats: {'cg_nodes': 894, 'composite_nodes': 893, 'merges': 1, 'edges_in': 1770, 'edges_out': 1770, 'unmapped_edges': 0, 'kind_dist': {'class': 4, 'method': 11, 'function': 551, 'file': 58, 'import': 201, 'variable': 51, 'constant': 17}, 'pyast_call_edges': 411, 'pyast_ref_edges': 171, 'pyast_exports_stamped': 18}

## God nodes

- **main** (degree 23) `cg:4b1559b6f6e0f7ea`
- **resolve** (degree 22) `cg:75637ed541aa7ba9`
- **AdaptResult** (degree 13) `cg:85c9d5757530c188`
- **health** (degree 13) `cg:fe3f8dd8bc1ea820`
- **build_repo** (degree 12) `cg:164a13d5b9250633`
- **_init** (degree 10) `cg:e088c0baf177a262`
- **materialize** (degree 9) `cg:663c5cfd8b221c7b`
- **visit** (degree 8) `cg:0e178b2e6dfd5890`
- **build_digraph** (degree 8) `cg:ab8e704b83711a21`
- **analyze** (degree 8) `cg:e313e80a80f808d4`
- **_hook_stop** (degree 7) `cg:a135ab201a903149`
- **_semantic_merge** (degree 7) `cg:ace5dbd5b16b7cee`
- **_adapt_repo** (degree 7) `cg:b8342ab2a94d09a7`
- **_query_cmd** (degree 7) `cg:c38cfe22f0d77c40`
- **_load_structural** (degree 7) `cg:efb02b5771958f3a`

## Surprising connections

- _label_index ↔ AdaptResult
- _load_structural ↔ from_structural
- build_fused ↔ fold_singleton_communities
- build_fused ↔ prune_orphans
- curated_nodes ↔ AdaptResult
- feature_map ↔ build_digraph
- health ↔ analyze
- merge_payloads ↔ AdaptResult
- merge_semantic ↔ AdaptResult
- prep_tasks ↔ AdaptResult
