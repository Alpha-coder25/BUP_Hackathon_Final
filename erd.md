# Entity-Relationship Diagram: Fuel Supply Intelligence & Resilience Platform

Key legend: **PK** primary key, **FK** foreign key, **UK** unique key. Table and column names are the physical PostgreSQL names.

## Entities

### World mirror (from the simulator)

**`regions`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | string | PK |  |
| `name` | string |  |  |
| `demand_factor` | float |  |  |

**`depots`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | string | PK |  |
| `region_id` | string | FK |  |
| `name` | string |  |  |
| `status` | string |  | OPEN or CONSTRAINED |
| `dispatch_capacity_per_tick` | int |  |  |
| `capacity` | jsonb |  | per fuel |

**`stations`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | string | PK |  |
| `region_id` | string | FK |  |
| `name` | string |  |  |
| `demand_profile` | string |  |  |
| `status` | string |  | OPEN or OUTAGE |
| `demand_multiplier` | float |  |  |
| `capacity` | jsonb |  | per fuel |

**`routes`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | string | PK |  |
| `source_depot_id` | string | FK |  |
| `destination_station_id` | string | FK |  |
| `transit_ticks` | int |  |  |
| `max_shipment` | int |  |  |
| `status` | string |  | AVAILABLE or DISRUPTED |

**`depot_inventory_snapshots`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `depot_id` | string | FK |  |
| `tick` | int |  |  |
| `sim_time` | timestamp |  |  |
| `fuel_type` | string |  |  |
| `quantity` | float |  |  |

**`station_inventory_snapshots`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `station_id` | string | FK |  |
| `tick` | int |  |  |
| `sim_time` | timestamp |  |  |
| `fuel_type` | string |  |  |
| `quantity` | float |  |  |

**`demand_observations`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `station_id` | string | FK |  |
| `fuel_type` | string |  |  |
| `tick` | int |  |  |
| `demand_liters` | float |  |  |
| `served_liters` | float |  |  |
| `unmet_liters` | float |  |  |

**`supply_arrivals`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | string | PK |  |
| `depot_id` | string | FK |  |
| `fuel_type` | string |  |  |
| `quantity` | float |  |  |
| `planned_tick` | int |  |  |
| `actual_tick` | int |  |  |
| `status` | string |  | SCHEDULED DELAYED ARRIVED |

**`sim_events`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | int | PK |  |
| `type` | string |  |  |
| `start_tick` | int |  |  |
| `end_tick` | int |  |  |
| `status` | string |  | SCHEDULED ACTIVE RESOLVED |
| `parameters` | jsonb |  |  |

### Intelligence

**`model_versions`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | int | PK |  |
| `name` | string |  |  |
| `kind` | string |  | forecast or anomaly or planner |
| `version` | string |  |  |
| `params` | jsonb |  |  |
| `backtest_mape` | float |  |  |
| `is_active` | boolean |  |  |
| `created_at` | timestamp |  |  |

**`forecasts`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `station_id` | string | FK |  |
| `model_version_id` | int | FK |  |
| `fuel_type` | string |  |  |
| `generated_at_tick` | int |  |  |
| `target_tick` | int |  |  |
| `predicted_liters` | float |  |  |
| `lower_bound` | float |  |  |
| `upper_bound` | float |  |  |

**`risk_assessments`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `station_id` | string | FK |  |
| `model_version_id` | int | FK |  |
| `fuel_type` | string |  |  |
| `tick` | int |  |  |
| `hours_to_stockout` | float |  |  |
| `stockout_probability` | float |  |  |
| `severity` | string |  | LOW MEDIUM HIGH CRITICAL |
| `confidence` | float |  |  |
| `signals` | jsonb |  |  |

**`alerts`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `risk_assessment_id` | bigint | FK |  |
| `type` | string |  | shortage anomaly disruption system |
| `severity` | string |  |  |
| `station_id` | string | FK |  |
| `fuel_type` | string |  |  |
| `message` | string |  |  |
| `status` | string |  | OPEN ACKED RESOLVED |
| `created_tick` | int |  |  |
| `acknowledged_by` | int | FK |  |
| `resolved_at` | timestamp |  |  |

### Decisions

**`recommendations`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `risk_assessment_id` | bigint | FK |  |
| `policy` | string |  | heuristic or optimizer or fallback |
| `tick` | int |  |  |
| `status` | string |  | PROPOSED APPROVED REJECTED EXPIRED |
| `confidence` | float |  |  |
| `risk_before` | float |  |  |
| `risk_after` | float |  |  |
| `explanation` | jsonb |  |  |
| `alternatives` | jsonb |  |  |
| `expires_tick` | int |  |  |

**`recommendation_items`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `recommendation_id` | bigint | FK |  |
| `depot_id` | string | FK |  |
| `station_id` | string | FK |  |
| `route_id` | string | FK |  |
| `fuel_type` | string |  |  |
| `quantity` | float |  |  |

**`operators`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | int | PK |  |
| `name` | string |  |  |
| `role` | string |  | viewer or operator or admin |
| `password_hash` | string |  |  |

**`decisions`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `recommendation_id` | bigint | FK |  |
| `operator_id` | int | FK |  |
| `action` | string |  | APPROVED REJECTED MODIFIED AUTO |
| `note` | string |  |  |
| `decided_at` | timestamp |  |  |

**`allocations`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `sim_allocation_id` | int |  | simulator id |
| `idempotency_key` | string | UK |  |
| `recommendation_item_id` | bigint | FK |  |
| `depot_id` | string | FK |  |
| `station_id` | string | FK |  |
| `route_id` | string | FK |  |
| `fuel_type` | string |  |  |
| `quantity` | float |  |  |
| `status` | string |  | PENDING IN_TRANSIT ARRIVED FAILED CANCELLED |
| `created_tick` | int |  |  |
| `departure_tick` | int |  |  |
| `expected_arrival_tick` | int |  |  |
| `actual_arrival_tick` | int |  |  |
| `failure_reason` | string |  |  |

### Operations

**`service_health_checks`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `component` | string |  | backend db simulator forecaster planner |
| `status` | string |  | HEALTHY DEGRADED DOWN |
| `latency_ms` | int |  |  |
| `detail` | string |  |  |
| `checked_at` | timestamp |  |  |

**`fallback_events`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `component` | string |  |  |
| `reason` | string |  |  |
| `fallback_policy` | string |  |  |
| `started_at` | timestamp |  |  |
| `ended_at` | timestamp |  |  |

**`benchmark_runs`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | int | PK |  |
| `policy` | string |  |  |
| `seed` | int |  |  |
| `scenario` | string |  |  |
| `ticks` | int |  |  |
| `service_level` | float |  |  |
| `unmet_liters` | float |  |  |
| `allocation_failures` | int |  |  |
| `started_at` | timestamp |  |  |

**`audit_log`**

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK |  |
| `operator_id` | int | FK |  |
| `action` | string |  |  |
| `entity_type` | string |  |  |
| `entity_id` | string |  |  |
| `payload` | jsonb |  |  |
| `created_at` | timestamp |  |  |

## Relationships

| Parent | Cardinality | Child | Relationship |
|---|---|---|---|
| `regions` | One to many | `depots` | contains |
| `regions` | One to many | `stations` | contains |
| `depots` | One to many | `routes` | source |
| `stations` | One to many | `routes` | destination |
| `depots` | One to many | `depot_inventory_snapshots` | tracked by |
| `stations` | One to many | `station_inventory_snapshots` | tracked by |
| `stations` | One to many | `demand_observations` | observes |
| `depots` | One to many | `supply_arrivals` | receives |
| `stations` | One to many | `forecasts` | forecasted for |
| `model_versions` | One to many | `forecasts` | produced |
| `model_versions` | One to many | `risk_assessments` | used by |
| `stations` | One to many | `risk_assessments` | assessed |
| `risk_assessments` | One to many | `alerts` | raises |
| `risk_assessments` | One to many | `recommendations` | triggers |
| `recommendations` | One to many (at least one) | `recommendation_items` | contains |
| `recommendations` | One to many | `decisions` | reviewed in |
| `operators` | One to many | `decisions` | makes |
| `operators` | One to many | `alerts` | acknowledges |
| `operators` | One to many | `audit_log` | performs |
| `recommendation_items` | One to zero-or-one | `allocations` | executed as |
| `depots` | One to many | `allocations` | ships |
| `stations` | One to many | `allocations` | receives |
| `routes` | One to many | `allocations` | carries |

**Notes**

- `allocations.recommendation_item_id` is nullable so allocations can exist without a recommendation (for example auto-mode).
- `allocations.idempotency_key` is unique and never reused, matching the simulator's rule that keys stay occupied after cancel.
- `allocations.sim_allocation_id` stores the simulator's own allocation id.
- Inventory is stored as per-tick snapshots (one table per depot and station) for history and forecasting.
