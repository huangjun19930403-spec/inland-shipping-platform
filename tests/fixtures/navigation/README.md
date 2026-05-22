# Navigation Fixture Set

These tiny fixtures are intentionally synthetic. They validate table shape, import contracts, graph edge boundaries, and route failure/success cases without reading the full `revier.zip` dataset.

Do not replace these with the 48,192-row `rx` layer. Real river data belongs in import/integration checks and local production demonstration, while these fixtures must remain test-only and must not be written into production seed, page defaults, or the active navigation graph.
