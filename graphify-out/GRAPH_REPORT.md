# Fused Graph Report (codegraph substrate + graphify overlay)

- nodes: 680  edges: 1038  communities: 28
- adapter stats: {'cg_nodes': 681, 'composite_nodes': 680, 'merges': 1, 'edges_in': 1235, 'edges_out': 1235, 'unmapped_edges': 0, 'kind_dist': {'class': 3, 'method': 2, 'function': 416, 'file': 47, 'import': 158, 'variable': 37, 'constant': 17}}

## God nodes

- **visit** (degree 8) `cg:0e178b2e6dfd5890`
- **_init** (degree 8) `cg:e088c0baf177a262`
- **analyze** (degree 7) `cg:e313e80a80f808d4`
- **build_digraph** (degree 6) `cg:ab8e704b83711a21`
- **build_repo** (degree 5) `cg:164a13d5b9250633`
- **materialize** (degree 5) `cg:663c5cfd8b221c7b`
- **semantic_baseline** (degree 5) `cg:e14b91e4896b1cc2`
- **row** (degree 4) `cg:24fffb15b0ba6749`
- **abstractness_distance** (degree 4) `cg:41887d5560742e2d`
- **AdaptResult** (degree 4) `cg:85c9d5757530c188`
- **dead_code** (degree 4) `cg:989f896cddda2652`
- **_check_conflicts** (degree 4) `cg:9f1d9a9683b00885`
- **_adapt_repo** (degree 4) `cg:b8342ab2a94d09a7`
- **fan_distribution** (degree 4) `cg:ce550017ac803453`
- **_meta** (degree 4) `cg:fa883342975cae24`

## Surprising connections

- adapt_ts ↔ AdaptResult
- adapt_ts ↔ composite_id
- build_subagent_context ↔ linkable_subset
