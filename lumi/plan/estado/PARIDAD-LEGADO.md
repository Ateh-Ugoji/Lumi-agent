# Paridad con los tests legados

Generado por `python -m apps.core.tests.legacy_parity --write`. No se edita a mano.
Un test (`test_legacy_parity.py`) falla si este archivo se desvía del mapa.

El mapa se hizo por comportamiento y se comprobó por nombre de test y lectura de muestras,
no aserción por aserción. `covered` y `replaced` dicen que existe un test nuevo que cubre
la misma conducta, no que sea equivalente línea a línea.

## Resumen

| Estado | Tests legados | Parte |
| --- | ---: | ---: |
| covered | 337 | 80.6 % |
| replaced | 45 | 10.8 % |
| deviation | 0 | 0.0 % |
| gap | 36 | 8.6 % |
| **Total** | **418** | 100 % |

## Por archivo legado

| Archivo | Total | covered | replaced | deviation | gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| `test_agent_claim_gate` | 15 | 15 | 0 | 0 | 0 |
| `test_agent_context` | 8 | 2 | 6 | 0 | 0 |
| `test_agent_tool_errors` | 6 | 6 | 0 | 0 | 0 |
| `test_context_budget` | 11 | 11 | 0 | 0 | 0 |
| `test_coverage_gate` | 12 | 12 | 0 | 0 | 0 |
| `test_enforcement` | 7 | 7 | 0 | 0 | 0 |
| `test_framework_corpus` | 8 | 0 | 8 | 0 | 0 |
| `test_handle_db` | 12 | 5 | 1 | 0 | 6 |
| `test_handle_search_mvp` | 29 | 29 | 0 | 0 | 0 |
| `test_handle_search_platforms` | 14 | 12 | 2 | 0 | 0 |
| `test_handles_router` | 7 | 0 | 7 | 0 | 0 |
| `test_jev_layer` | 21 | 18 | 3 | 0 | 0 |
| `test_loop_gates` | 7 | 7 | 0 | 0 | 0 |
| `test_mcp` | 20 | 20 | 0 | 0 | 0 |
| `test_mcp_google_router` | 9 | 9 | 0 | 0 | 0 |
| `test_memory` | 11 | 0 | 11 | 0 | 0 |
| `test_metrics` | 7 | 0 | 0 | 0 | 7 |
| `test_niche_schemas` | 11 | 0 | 0 | 0 | 11 |
| `test_peer_extract` | 13 | 13 | 0 | 0 | 0 |
| `test_peer_pipeline_wiring` | 2 | 2 | 0 | 0 | 0 |
| `test_peer_schemas` | 8 | 8 | 0 | 0 | 0 |
| `test_peer_store` | 7 | 7 | 0 | 0 | 0 |
| `test_peer_synthesize` | 8 | 8 | 0 | 0 | 0 |
| `test_peer_winners` | 12 | 12 | 0 | 0 | 0 |
| `test_post_filter` | 7 | 5 | 2 | 0 | 0 |
| `test_profile_extract_fixes` | 27 | 15 | 0 | 0 | 12 |
| `test_prompt5_acceptance` | 8 | 8 | 0 | 0 | 0 |
| `test_provider_fallback` | 10 | 10 | 0 | 0 | 0 |
| `test_registry` | 4 | 4 | 0 | 0 | 0 |
| `test_repurpose` | 11 | 11 | 0 | 0 | 0 |
| `test_repurpose_endpoint` | 17 | 17 | 0 | 0 | 0 |
| `test_tool_tiers` | 18 | 18 | 0 | 0 | 0 |
| `test_turn_class` | 21 | 20 | 1 | 0 | 0 |
| `test_user_request_tool` | 6 | 6 | 0 | 0 | 0 |
| `test_voice` | 5 | 5 | 0 | 0 | 0 |
| `test_voice_corpus` | 5 | 3 | 2 | 0 | 0 |
| `test_voice_index_sqlite` | 3 | 1 | 2 | 0 | 0 |
| `test_voice_routes` | 4 | 4 | 0 | 0 | 0 |
| `test_xpoz` | 1 | 1 | 0 | 0 | 0 |
| `test_xpoz_resilience` | 6 | 6 | 0 | 0 | 0 |

## Huecos

### ARCHITECT: 19 tests

- `test_metrics::test_detect_spike_below_floor`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_detect_spike_no_baseline_uses_floor`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_detect_spike_no_spike_when_growth_is_steady`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_detect_spike_relative_to_baseline`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_velocity_needs_at_least_two_snapshots`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_velocity_with_three_snapshots_computes_both`: Velocidad y detección de picos de likes por hora sin portar.
- `test_metrics::test_velocity_with_two_snapshots_has_no_baseline`: Velocidad y detección de picos de likes por hora sin portar.
- `test_profile_extract_fixes::test_final_metrics_picks_nearest_72h`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_finalize_ingest_pass_two_miss_flow`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_infer_timezone_needs_minimum_posts`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_maybe_update_timezone_sets_inferred`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_milestone_bucket_counts_targets`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_pass_reached_window`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_rethread_numbers_by_publish_time_not_arrival`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_second_miss_bracket_and_window_guards`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_second_miss_requires_two_complete_misses`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_snapshot_skip_matrix`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_truncation_flag_is_sticky_on_refetch`: Política de la pasada de ingesta que el código nuevo aún no tiene.
- `test_profile_extract_fixes::test_user_confirmed_timezone_always_wins`: Política de la pasada de ingesta que el código nuevo aún no tiene.

### CONNECT: 6 tests

- `test_handle_db::test_check_niche_trends_persists_every_user_it_searches`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.
- `test_handle_db::test_check_niche_trends_survives_handle_db_failure`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.
- `test_handle_db::test_frameworks_search_persists_every_author`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.
- `test_handle_db::test_scanned_handles_enrich_only_unknown_within_cap`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.
- `test_handle_db::test_scanned_handles_no_enrichment_when_store_is_down`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.
- `test_handle_db::test_scanned_handles_zero_limit_saves_handles_only`: Guardar en la tabla de handles los autores que descubre un escaneo de nicho (tendencias, frameworks, enriquecimiento con tope) no tiene test ni uso en el código nuevo.

### INTELLIGENCE: 11 tests

- `test_niche_schemas::test_comment_sample_defaults`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_config_bands_and_weights`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_geo_signal_requires_evidence`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_global_relevance_needs_no_geo_query`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_hour_histogram_must_be_24`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_local_first_requires_geo_query`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_niche_profile_failed_status_constructs_without_fabrication`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_peer_candidate_defaults_never_guess_geo`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_query_validation_fields_default_to_unvalidated`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_retweet_context_carries_original`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.
- `test_niche_schemas::test_scored_keyword_weight_bounds`: El esquema de nicho con geografía, consultas y vetado de pares del código legado no se portó. Hace falta decidir: portarlo o retirarlo.

## Reemplazos y desviaciones

- `test_agent_context` (replaced): El profile_id ya no se inyecta si falta: el turno lo fija y el modelo no puede cambiarlo.
- `test_framework_corpus` (replaced): Chroma local pasa a un puerto de vectores con filas en PostgreSQL.
- `test_handle_db` (replaced): El almacén de handles ya no depende de Chroma ni de Firestore: vive en PostgreSQL.
- `test_handle_search_platforms` (replaced): La cuota de lectura y recorte de Firestore no existe en PostgreSQL.
- `test_handles_router` (replaced): Los routers de FastAPI pasan a vistas DRF; se prueban por HTTP y por montaje de rutas.
- `test_jev_layer` (replaced): El consejo ordena por relevancia vectorial (campo relevance) y ya no filtra con el juez.
- `test_memory` (replaced): memory.md y Chroma pasan a notas y resumen en PostgreSQL con vectores detrás de un puerto.
- `test_post_filter` (replaced): El filtro de captions contaminadas vive en los mapeadores de ingesta, no en el upsert.
- `test_turn_class` (replaced): Ya no hay reexportación desde el bucle; la lista de saludos se prueba en su módulo.
- `test_voice_corpus` (replaced): Chroma local pasa a un puerto de vectores con filas en PostgreSQL.
- `test_voice_index_sqlite` (replaced): El índice parcial de SQLite pasa a una restricción única parcial de PostgreSQL.
