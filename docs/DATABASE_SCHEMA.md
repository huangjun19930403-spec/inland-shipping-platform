# Database Schema

## Migration Policy

The active migration chain has one baseline:

```text
alembic/versions/001_initial_schema.py
```

It creates the full current schema directly. Historical patch migrations were removed from the active chain. New production work should update the model and create intentional future migrations only after this rebuilt baseline is accepted.

## Schema Scale

The current local schema has 138 business tables plus `alembic_version`. Tables are grouped by domain rather than by old backend menu.

## Foundation Data

- `std_dict`, `std_dict_item`
- `code_sequence`
- `admin_region`, `admin_region_boundary`
- `region`, `region_city_relation`, `region_boundary_version`
- `water_system`, `water_system_boundary`
- `transport_node`, `node_alias`, `transport_node_profile`
- `transport_node_business_category`, `transport_node_handling_mode`, `transport_node_packaging_form`
- `transport_node_contact`, `transport_node_photo`
- `navigation_constraint_point`, `navigation_constraint_profile`

These tables are production seed data. They are not demo-only data.

## Commodity Master Data

- `commodity_category`, `commodity_type`, `commodity_standard`
- `commodity_alias`, `commodity_attribute_definition`, `commodity_standard_attribute`
- `commodity_packaging_form`, `commodity_transport_mode`
- `commodity_node_type_rule`, `commodity_handling_mode_rule`, `commodity_ship_type_rule`
- `commodity_standard_image`

Commodity data supports standardized cargo naming, handling rules, node compatibility and downstream analysis buckets.

## Freight Lifecycle And Shipping Opportunity

- `freight_batch_task`
- `freight_tms_inbound`
- `freight_clue`
- `freight_candidate`
- `freight_candidate_manual_feedback`
- `freight`
- `freight_contact`
- `freight_source_attachment`
- `freight_tag_relation`
- `freight_normalization_task`
- `freight_normalization_suggestion`

`freight` is the durable business record. The product-facing list is the shipping opportunity read model built from `freight` plus route, capacity, pricing, quality and lineage evidence.

## Vessel Capacity And Trust

- `vessel_identity`, `vessel_profile`, `vessel_registration_info`
- `vessel_capacity_dimension`, `vessel_build_info`
- `vessel_identifier_history`, `vessel_name_history`, `vessel_identity_link`
- `vessel_owner_period`, `vessel_operator_period`, `vessel_contact`, `vessel_crew_assignment`
- `vessel_owner_document`, `vessel_person_certificate`, `vessel_certificate`
- `vessel_certificate_file`, `vessel_person_certificate_file`
- `vessel_latest_position_snapshot`, `vessel_ais_snapshot`, `vessel_ais_city_snapshot_item`
- `vessel_spatial_observation_snapshot`, `vessel_node_observation_item`, `vessel_node_observation_vessel`
- `vessel_route_segment_observation_item`, `vessel_route_segment_match_sample`
- `vessel_data_quality_issue`, `vessel_profile_summary`
- `vessel_certificate_requirement_rule`, `vessel_risk_signal`, `vessel_risk_review`
- `vessel_blacklist_signal`
- `vessel_governance_task`, `vessel_governance_sync_batch`
- `vessel_controller_evidence`, `vessel_controller_conclusion`
- `vessel_affiliation_evidence`, `vessel_affiliation_conclusion`
- `vessel_relation_evidence_attachment`
- `vessel_certificate_image_recognition`, `vessel_owner_document_image_recognition`, `vessel_person_certificate_image_recognition`
- `vessel_recognition_field_diff`, `vessel_recognition_adoption_record`
- `vessel_candidate_analysis`, `vessel_candidate_analysis_item`, `vessel_candidate_analysis_annotation`
- `vessel_navigation_constraint_evidence`

This group supports the运力中心: capacity, availability, contacts, compliance, risk and candidate-fit.

## Route And Geometry

- `shipping_route`
- `shipping_route_plan`
- `shipping_route_line`
- `shipping_route_line_node`
- `shipping_route_line_segment`
- `shipping_route_line_track`

Route tracks must represent real provider geometry. Blank, pending, failed and not-computable states are represented explicitly by API response state, not by drawing fallback geometry.

## Analysis Facts

- `analysis_bucket_definition`
- `analysis_indicator_definition`
- `analysis_job_definition`
- `analysis_job_run`
- `analysis_snapshot`
- `fact_freight_daily`, `fact_freight_flow_daily`, `fact_freight_city_daily`, `fact_freight_node_daily`
- `fact_freight_commodity_daily`, `fact_freight_price_daily`
- `fact_ship_daily`, `fact_ship_city_daily`, `fact_ship_flow_daily`
- `fact_region_daily`, `fact_region_supply_demand_daily`
- `fact_vessel_asset_daily`, `fact_vessel_ais_freshness_daily`
- `fact_vessel_node_daily`, `fact_vessel_route_segment_daily`, `fact_vessel_trajectory_daily`
- `fact_vessel_quality_daily`, `fact_vessel_risk_daily`
- `fact_candidate_fit_daily`

Fact tables must be interpreted with their data version, sample size, coverage and confidence. Local demo facts are not production evidence.

## Pricing Decisions

- `pricing_decision_record`

This table stores both known-price quote decisions (`QUOTE_DECISION`) and unknown-market-rate estimates (`RATE_ESTIMATE`). Each row persists the request context, advanced quote configuration, route evidence, sample evidence, result metrics, coverage, confidence, lineage, not-computable reasons and recommended actions. It is an audit trail for pricing analysis, not a replacement for freight source evidence.

The baseline migration keeps this table in the single `001_initial_schema`. Its primary key uses the normal large-integer model type in production databases and an SQLite `INTEGER PRIMARY KEY` variant locally, so quote and rate estimate records autoincrement correctly during local-demo testing.

## Audit, System And Storage

- `audit_task`, `audit_task_snapshot`, `audit_record`
- `sys_user`, `sys_role`, `sys_permission`, `sys_menu`
- `sys_user_role`, `sys_role_permission`, `sys_role_menu`, `sys_role_data_scope`
- `sys_data_scope`, `sys_login_log`, `sys_user_status_log`
- `system_config`
- `storage_file`

Menus are production seed data and define the business information architecture consumed by the frontend after login.

## Removed Legacy Direction

- Old multi-step Alembic patch chain is not active.
- Old `ship_*` and early vessel placeholder tables are not part of the current production schema.
- Legacy freight list endpoint is removed from the business API surface.
- Historical audit and phase documents have been deleted and consolidated into the current documentation pack.
