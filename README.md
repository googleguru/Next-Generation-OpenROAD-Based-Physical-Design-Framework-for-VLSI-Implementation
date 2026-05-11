# Next-Generation Physical Design Framework for VLSI Implementation

A production-grade, modular RTL-to-GDSII physical design framework with
adaptive flow control, cross-stage QoR feedback, intelligent failure diagnostics,
structured experiment management, and publication-ready reporting.

---

## What Is New vs. a Standard EDA Flow

| Capability | Standard Flow | This Framework |
|---|---|---|
| **Adaptive parameter tuning** | Fixed scripts | Rule-based + optional Bayesian tuner |
| **Cross-stage QoR feedback** | None | Signals flow from placement → CTS → routing |
| **Failure diagnostics** | Manual log inspection | Automatic classification + root-cause + remediation |
| **Rollback policy** | Re-run from scratch | Stage-level snapshot + targeted rollback |
| **Experiment management** | Ad-hoc shell scripts | YAML-driven, seeded, structured CSV/Parquet output |
| **Benchmark ingestion** | Manual file wiring | IPSD manifest loader + ISCAS synthesis prep |
| **Reporting** | Fragmented logs | Auto-updated README + REPORT.md + publication-ready figures |
| **Programmatic API** | Tcl-only | Full Python API for every stage |

---

## Architecture

```
pdflow CLI (main.py)
│
├── FlowController           — orchestrates all stages, wires modules together
│   ├── StageRunner          — per-stage execution with retry/rollback
│   ├── ArtifactRegistry     — manages all inter-stage file artifacts
│   └── DesignState          — immutable snapshot of design progress
│
├── EDA Adapter (src/openroad_adapter/)
│   ├── EDARunner            — renders Jinja2 Tcl templates + invokes EDA binary
│   ├── MetricsExtractor     — parses logs/reports → structured metric dicts
│   └── tcl_templates/       — parameterized per-stage Tcl scripts
│       ├── floorplan.tcl
│       ├── pdn.tcl
│       ├── global_place.tcl
│       ├── detail_place.tcl
│       ├── cts.tcl
│       ├── global_route.tcl
│       ├── detail_route.tcl
│       └── finish.tcl
│
├── QoR Engine (src/qor/)
│   ├── MetricSchema         — typed metric specs with alarm thresholds
│   ├── CrossStageFeedback   — passes placement/timing signals downstream
│   └── RollbackPolicy       — decides: proceed / retry / rollback / abort
│
├── Adaptive Tuner (src/tuning/)
│   ├── RuleBasedTuner       — deterministic, fully auditable rule engine
│   ├── BayesianTuner        — UCB Gaussian-process optimiser (no ext. ML deps)
│   └── SearchSpace          — typed parameter ranges from YAML
│
├── Diagnostics (src/diagnostics/)
│   ├── FailureClassifier    — pattern-match → FailureClass enum
│   ├── RootCauseAnalyzer    — stage + metric + history → narrative report
│   └── RemediationEngine    — FailureClass → actionable fix suggestions
│
├── Benchmark Layer (src/benchmarks/)
│   ├── IPSDLoader           — YAML manifest → IPSDBenchmark objects
│   ├── ISCASPrep            — Yosys synthesis + SDC generation for ISCAS
│   ├── CollateralValidator  — pre-flight file existence + sanity checks
│   └── DatasetNormalizer    — heterogeneous inputs → unified config dict
│
├── Synthesis (src/synth/)
│   ├── SynthesisRunner      — Yosys RTL-to-gate for ISCAS/custom designs
│   └── LibertyHandler       — Liberty .lib parser + cell inventory
│
├── Storage (src/storage/)
│   ├── RunLogger            — CSV/JSON/Parquet structured run logging
│   └── RunManifest          — deterministic run metadata + git SHA
│
├── Visualization (src/viz/)    — all white background, constrained layout
│   ├── PlotEngine           — base style + save utilities
│   ├── QoRPlotter           — WNS/TNS trends, runtime breakdowns
│   ├── CongestionPlotter    — overflow trends, congestion vs timing scatter
│   └── ComparisonPlotter    — ablation bars, benchmark tables, multi-seed boxes
│
└── Reporting (src/report/)
    ├── ExperimentSummary    — aggregates multi-run JSON → flat rows
    ├── MarkdownReporter     — generates REPORT.md
    └── READMEUpdater        — in-place README section updates
```

---

## Quick Start

### Native (Python >= 3.10)

```bash
# 1. Install dependencies
make install

# 2. Place PDK collateral in pdks/<pdk_name>/
# 3. Place benchmark netlists in benchmarks/ipsd/<design>/

# 4. Validate collateral
make validate

# 5. Run a single design (full flow with all modules)
make run DESIGN=gcd SEED=42

# 6. Run the baseline (no adaptive modules)
make baseline DESIGN=gcd

# 7. Sweep all benchmarks over multiple seeds
make sweep SEEDS="42 123 7"

# 8. Run ablation study
make ablation

# 9. Generate report + figures + update README
make report
```

### Docker (fully reproducible)

```bash
# Build image
make docker-build

# Baseline run
docker-compose -f docker/docker-compose.yml run --rm baseline

# Full flow
docker-compose -f docker/docker-compose.yml run --rm run DESIGN=gcd SEED=42

# Sweep
docker-compose -f docker/docker-compose.yml run --rm sweep

# Report
docker-compose -f docker/docker-compose.yml run --rm report
```

Mount benchmarks and PDK collateral:

```yaml
volumes:
  - ./benchmarks:/workspace/benchmarks
  - ./pdks:/workspace/pdks
  - ./outputs:/workspace/outputs
```

---

## Flow Stages

```
RTL/Netlist
     │
     ▼
[synthesis_handoff]  ─ validates and copies synthesis outputs
     │
     ▼
[floorplan]          ─ die/core sizing, I/O placement
     │
     ▼
[pdn]                ─ power distribution network generation
     │
     ▼
[global_place]       ─ global placement (timing+routability-driven)
     │         <─── QoR signal: overflow, HPWL
     ▼
[detail_place]       ─ legalization, timing repair, buffer insertion
     │         <─── QoR signal: WNS, TNS
     ▼
[cts]                ─ clock tree synthesis, post-CTS hold repair
     │         <─── QoR signal: skew, WNS
     ▼
[global_route]       ─ global routing with overflow management
     │         <─── QoR signal: overflow, WNS
     ▼
[detail_route]       ─ detailed routing, DRC targeting
     │         <─── QoR signal: DRC count
     ▼
[finish]             ─ DRC/antenna check, power, GDSII export
```

---

## Benchmark Preparation

### IPSD Benchmarks

1. Edit [configs/benchmarks/ipsd_manifest.yaml](configs/benchmarks/ipsd_manifest.yaml)
2. Set `base_dir` and confirm all file paths
3. Run `make validate`

### ISCAS Benchmarks

ISCAS-85 combinational circuits (`c`-prefix) are **automatically skipped** —
no clock domain exists for physical implementation.

ISCAS-89 sequential circuits (`s`-prefix) are synthesized with Yosys:

```bash
python main.py sweep --manifest configs/benchmarks/iscas_manifest.yaml
```

---

## Configuration

### Base config ([configs/base.yaml](configs/base.yaml))

```yaml
flow:
  max_retries: 2
  tuner_mode: "rule"      # "rule" | "bayesian" | "none"
  rollback_enabled: true
  seed: 42
```

### PDK profiles ([configs/pdk.yaml](configs/pdk.yaml))

Pre-configured for `nangate45`, `sky130hd`, `asap7`.

---

## Adaptive Flow Controller

| Stage | Condition | Action |
|---|---|---|
| Global place | overflow > 20% | Reduce `target_density` by 0.05 |
| Global place | WNS < -1 ns | Enable timing-driven repair |
| CTS | skew > 300 ps | Reduce cluster size + buffer spacing |
| Global route | overflow > 10% | Increase iteration limit by 25 |
| Detail route | DRC > 0 | Increase `droute_end_iter` by 32 |

---

## Failure Diagnostics

When a stage fails, the diagnostics module automatically produces:

```
=== Failure Diagnosis ===
Design : aes
Stage  : global_place
Class  : placement_overflow  (confidence=85%)

Root cause: Placement overflow too high — RUDY overflow exceeds 20%.

Remediation suggestions:
  1. Reduce target_density from 0.70 to 0.65 (or lower).
  2. Enable routability_driven=true in global placement.
  3. Increase die area or remove constraining blockages.
```

---

## Makefile Targets

| Target | Action |
|---|---|
| `make build` | Install Python dependencies |
| `make docker-build` | Build Docker image |
| `make baseline` | Flow without adaptive modules |
| `make run` | Full flow with all modules |
| `make sweep` | Benchmark sweep over multiple seeds |
| `make ablation` | Ablation study |
| `make report` | Generate REPORT.md + figures + update README |
| `make validate` | Validate benchmark collateral |
| `make clean` | Remove generated outputs |

---

## Known Limitations

- PDK collateral and benchmark netlists are **not included** — place in `pdks/` and `benchmarks/`.
- ISCAS-85 combinational circuits are always skipped.
- Timing values are estimates; sign-off requires full RC extraction.
- GDSII export disabled by default (`write_gds: false`).
- No results are fabricated — run `make sweep` with valid collateral to populate.

---

<!-- RESULTS_START -->
## ISCAS-89 Physical Design Results

Five sequential ISCAS-89 benchmark circuits (s27, s298, s344, s386, s526) were run through
a complete Python-native PD flow: **Partitioning → Floorplanning → Placement → STA → Layout → Compaction → RC Extraction → GDS II**.
All figures were saved with white backgrounds at 180 DPI.

### Circuit Statistics

| Circuit | Primary Inputs | Flip-Flops | Gates | Description |
|---------|---------------|-----------|-------|-------------|
| s27     | 7             | 3         | 17    | Simple sequential FSM |
| s298    | 3             | 14        | 123   | Lock controller FSM |
| s344    | 9             | 15        | 163   | BCD incrementer |
| s386    | 7             | 6         | 160   | Viterbi decoder FSM |
| s526    | 3             | 24        | 197   | Arbiter / priority encoder |

### QoR Summary

| Circuit | HPWL | WNS (ps) | TNS (ps) | Depth | Violations | Die W×H | Area Red. | Wire (μm) | Elmore Max (ps) |
|---------|------|----------|----------|-------|------------|---------|-----------|-----------|-----------------|
| s27     | 33.0 | 0.0      | 0.0      | 13    | 0          | 5.5×4.4 | 46.2%     | 13.4      | 4.2 |
| s298    | 803.1 | 3919.0  | 0.0      | 3     | 0          | 14.3×11.0| 15.9%    | 258.9     | 4.7 |
| s344    | 1001.3 | 2801.0 | 0.0      | 9     | 0          | 16.5×12.1| 12.4%    | 365.7     | 4.8 |
| s386    | 1120.3 | -413.0 | -4348.0  | 57    | 20         | 16.5×12.1| 12.4%    | 366.6     | 5.0 |
| s526    | 1389.3 | 3306.0 | 0.0      | 5     | 0          | 18.7×13.2| 9.6%     | 426.2     | 4.9 |

> s386 has 20 timing violations (WNS = −413 ps) due to its 57-stage combinational depth.

### GDS II Files

Binary GDS II files written to `outputs/gds/`:

| File | Size |
|------|------|
| [s27.gds](outputs/gds/s27.gds) | 4.8 KB |
| [s298.gds](outputs/gds/s298.gds) | 32 KB |
| [s344.gds](outputs/gds/s344.gds) | 42 KB |
| [s386.gds](outputs/gds/s386.gds) | 43 KB |
| [s526.gds](outputs/gds/s526.gds) | 52 KB |

Layers: `0` = combinational gates, `1` = wire paths, `2` = flip-flops, `4` = primary inputs, `5` = labels, `10` = die outline.

---

### Visualizations

#### Summary — All Circuits

| Multi-Circuit Comparison | Results Table |
|:---:|:---:|
| ![Multi-circuit comparison](outputs/figures/iscas89/iscas89_summary.png) | ![Results table](outputs/figures/iscas89/iscas89_table.png) |

---

#### s27 — Simple Sequential FSM (17 gates, 3 FFs)

| Partitioning | Floorplan | Placement |
|:---:|:---:|:---:|
| ![s27 partition](outputs/figures/iscas89/s27/s27_partition.png) | ![s27 floorplan](outputs/figures/iscas89/s27/s27_floorplan.png) | ![s27 placement](outputs/figures/iscas89/s27/s27_placement.png) |

| STA | Critical Path | Layout |
|:---:|:---:|:---:|
| ![s27 sta](outputs/figures/iscas89/s27/s27_sta.png) | ![s27 critical path](outputs/figures/iscas89/s27/s27_critical_path.png) | ![s27 layout](outputs/figures/iscas89/s27/s27_layout.png) |

| Compaction | RC Extraction | GDS Preview |
|:---:|:---:|:---:|
| ![s27 compaction](outputs/figures/iscas89/s27/s27_compaction.png) | ![s27 rc](outputs/figures/iscas89/s27/s27_rc_extraction.png) | ![s27 gds](outputs/figures/iscas89/s27/s27_gds_preview.png) |

---

#### s298 — Lock Controller FSM (123 gates, 14 FFs)

| Partitioning | Floorplan | Placement |
|:---:|:---:|:---:|
| ![s298 partition](outputs/figures/iscas89/s298/s298_partition.png) | ![s298 floorplan](outputs/figures/iscas89/s298/s298_floorplan.png) | ![s298 placement](outputs/figures/iscas89/s298/s298_placement.png) |

| STA | Critical Path | Layout |
|:---:|:---:|:---:|
| ![s298 sta](outputs/figures/iscas89/s298/s298_sta.png) | ![s298 critical path](outputs/figures/iscas89/s298/s298_critical_path.png) | ![s298 layout](outputs/figures/iscas89/s298/s298_layout.png) |

| Compaction | RC Extraction | GDS Preview |
|:---:|:---:|:---:|
| ![s298 compaction](outputs/figures/iscas89/s298/s298_compaction.png) | ![s298 rc](outputs/figures/iscas89/s298/s298_rc_extraction.png) | ![s298 gds](outputs/figures/iscas89/s298/s298_gds_preview.png) |

---

#### s344 — BCD Incrementer (163 gates, 15 FFs)

| Partitioning | Floorplan | Placement |
|:---:|:---:|:---:|
| ![s344 partition](outputs/figures/iscas89/s344/s344_partition.png) | ![s344 floorplan](outputs/figures/iscas89/s344/s344_floorplan.png) | ![s344 placement](outputs/figures/iscas89/s344/s344_placement.png) |

| STA | Critical Path | Layout |
|:---:|:---:|:---:|
| ![s344 sta](outputs/figures/iscas89/s344/s344_sta.png) | ![s344 critical path](outputs/figures/iscas89/s344/s344_critical_path.png) | ![s344 layout](outputs/figures/iscas89/s344/s344_layout.png) |

| Compaction | RC Extraction | GDS Preview |
|:---:|:---:|:---:|
| ![s344 compaction](outputs/figures/iscas89/s344/s344_compaction.png) | ![s344 rc](outputs/figures/iscas89/s344/s344_rc_extraction.png) | ![s344 gds](outputs/figures/iscas89/s344/s344_gds_preview.png) |

---

#### s386 — Viterbi Decoder FSM (160 gates, 6 FFs)

> **Note:** 20 timing violations, WNS = −413 ps, TNS = −4348 ps (57-stage combinational depth).

| Partitioning | Floorplan | Placement |
|:---:|:---:|:---:|
| ![s386 partition](outputs/figures/iscas89/s386/s386_partition.png) | ![s386 floorplan](outputs/figures/iscas89/s386/s386_floorplan.png) | ![s386 placement](outputs/figures/iscas89/s386/s386_placement.png) |

| STA | Critical Path | Layout |
|:---:|:---:|:---:|
| ![s386 sta](outputs/figures/iscas89/s386/s386_sta.png) | ![s386 critical path](outputs/figures/iscas89/s386/s386_critical_path.png) | ![s386 layout](outputs/figures/iscas89/s386/s386_layout.png) |

| Compaction | RC Extraction | GDS Preview |
|:---:|:---:|:---:|
| ![s386 compaction](outputs/figures/iscas89/s386/s386_compaction.png) | ![s386 rc](outputs/figures/iscas89/s386/s386_rc_extraction.png) | ![s386 gds](outputs/figures/iscas89/s386/s386_gds_preview.png) |

---

#### s526 — Arbiter / Priority Encoder (197 gates, 24 FFs)

| Partitioning | Floorplan | Placement |
|:---:|:---:|:---:|
| ![s526 partition](outputs/figures/iscas89/s526/s526_partition.png) | ![s526 floorplan](outputs/figures/iscas89/s526/s526_floorplan.png) | ![s526 placement](outputs/figures/iscas89/s526/s526_placement.png) |

| STA | Critical Path | Layout |
|:---:|:---:|:---:|
| ![s526 sta](outputs/figures/iscas89/s526/s526_sta.png) | ![s526 critical path](outputs/figures/iscas89/s526/s526_critical_path.png) | ![s526 layout](outputs/figures/iscas89/s526/s526_layout.png) |

| Compaction | RC Extraction | GDS Preview |
|:---:|:---:|:---:|
| ![s526 compaction](outputs/figures/iscas89/s526/s526_compaction.png) | ![s526 rc](outputs/figures/iscas89/s526/s526_rc_extraction.png) | ![s526 gds](outputs/figures/iscas89/s526/s526_gds_preview.png) |

<!-- RESULTS_END -->

<!-- AUTO_UPDATED --> *Last updated: 2026-05-11*
