# Fused Graph Report (codegraph substrate + graphify overlay)

- nodes: 507  edges: 701  communities: 23
- adapter stats: {'cg_nodes': 508, 'composite_nodes': 507, 'merges': 1, 'edges_in': 821, 'edges_out': 821, 'unmapped_edges': 0, 'kind_dist': {'class': 3, 'method': 2, 'function': 283, 'file': 39, 'import': 131, 'variable': 32, 'constant': 17}}

## God nodes

- **_init** (degree 8) `cg:e088c0baf177a262`
- **visit** (degree 6) `cg:0e178b2e6dfd5890`
- **materialize** (degree 5) `cg:663c5cfd8b221c7b`
- **semantic_baseline** (degree 5) `cg:e14b91e4896b1cc2`
- **write_structural** (degree 4) `cg:13dc2f72e26c825e`
- **build_repo** (degree 4) `cg:164a13d5b9250633`
- **_refresh_cmds** (degree 4) `cg:1667e4445b9afd01`
- **_label_index** (degree 4) `cg:20071d980a7de331`
- **_norm** (degree 4) `cg:36bde4dbca0de9e3`
- **AdaptResult** (degree 4) `cg:85c9d5757530c188`
- **source_hash** (degree 4) `cg:9779ddbba3d406d0`
- **_adapt_repo** (degree 4) `cg:b8342ab2a94d09a7`
- **adapt** (degree 3) `cg:52ed65910189769a`
- **_hook_sessionstart** (degree 3) `cg:8aaf8e1ba47784ae`
- **_hook_stop** (degree 3) `cg:a135ab201a903149`

## Surprising connections

- adapt_ts ↔ AdaptResult
- adapt_ts ↔ composite_id
- build_subagent_context ↔ linkable_subset
