# revier.zip source data

Put the source Shapefile archive at:

```bash
scripts/source_data/navigation/revier.zip
```

The archive must contain the original layer files as Shapefile component sets:

- `rx.shp/.shx/.dbf/.prj/.cpg`
- `一级水系.shp/.shx/.dbf/.prj/.cpg`
- `二级水系.shp/.shx/.dbf/.prj/.cpg`
- `三级水系.shp/.shx/.dbf/.prj/.cpg`
- `四级水系.shp/.shx/.dbf/.prj/.cpg`
- `五级水系.shp/.shx/.dbf/.prj/.cpg`
- `六级水系.shp/.shx/.dbf/.prj/.cpg`
- `七级水系.shp/.shx/.dbf/.prj/.cpg`
- `rx8.shp/.shx/.dbf/.prj/.cpg`

Build curated seed:

```bash
python -m scripts.navigation.build_revier_production_seed \
  --source-zip scripts/source_data/navigation/revier.zip \
  --output-dir runtime/navigation-production \
  --export-seed \
  --self-feedback \
  --use-qwen-if-available \
  --use-es-if-available \
  --max-feedback-rounds 3
```

Load production seed:

```bash
python -m scripts.seeds.cli --profile production
```

Validate routing with existing transport nodes:

```bash
python -m scripts.navigation.validate_revier_routing_with_transport_nodes \
  --graph-version-code NAV_GRAPH_REVIER_PROD_V1 \
  --min-success-count 5 \
  --sample-count 10 \
  --use-es-if-available
```

Final acceptance:

```bash
python -m scripts.navigation.navigation_production_acceptance \
  --graph-version-code NAV_GRAPH_REVIER_PROD_V1
```

The raw `revier.zip` is source input only and must not be committed as production seed.

