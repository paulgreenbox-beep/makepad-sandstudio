# Dungeon project structure for MSS

Reference: [Dungeon System](https://github.com/paulgreenbox-beep/dungeon-system). This is a source-first structural layer, not a runner or an execution certificate.

- One SKLT structural declaration per MSS module, under its own directory.
- Stable `object_id` values, independent from filesystem path, process/window IDs, or Git revision.
- `depends_on` is explicit and refers to logical object IDs; do not infer transitive source closure.
- `isolation: BOUNDED` means architectural separation, **not** OS sandbox isolation.
- `git_scope: main` is the current common repository history boundary.
- GLIF/GLYF visual projection deliberately deferred. No implicit UI descriptions.
- SKLT records declarations. Runtime code + tests + evidence independently establish implementation and verification.
- Do not invent `VERIFIED` from SKLT, self-reported status, or a screenshot.
- Do not generate managed Dungeon indexes/projections/grades until an explicit, validated adoption is requested.
- Meaningful changes should have a Cronica entry with affected modules and tested source identity.

See [Dungeon module policy](https://github.com/paulgreenbox-beep/dungeon-system/blob/main/docs/module-isolation-git-scope.md).
