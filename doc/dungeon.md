# Dungeon project structure for MSS

The release repository uses the SKLT-only structural mode of [Dungeon System](https://github.com/paulgreenbox-beep/dungeon-system). Each module has one structural declaration. The [structure audit](../proof/documentation-audit/STRUCTURE_AUDIT.md) maps the declarations to the release source.

- Preserve `object_id` across source moves and Git revisions. Runtime App IDs, PIDs and window identities are separate.
- `depends_on` refers to existing logical object IDs. The preview retains historical logical edges. Use the Cargo manifests and source entry points to establish compile-time and runtime dependencies.
- `git_scope: main` is the declared common-history boundary. The release branch and exact commit identify the audited preview.
- `isolation: BOUNDED` describes architectural separation. OS security requires separate evidence.
- `state: SKLT` records the document type. Descriptions identify implementation status. Source, tests and runtime observations establish evidence.
- Managed adoption and derived-artifact refresh require separate authorization. The preview has no managed Dungeon indexes or GLIF/GLYF projections.
- Preserve existing Cronica entries as historical records.

See [Dungeon module policy](https://github.com/paulgreenbox-beep/dungeon-system/blob/main/docs/module-isolation-git-scope.md).
