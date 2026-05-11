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
### Latest Results

*No runs completed yet. Run `make sweep` after placing benchmark collateral.*
<!-- RESULTS_END -->

<!-- AUTO_UPDATED --> *Last updated: 2026-05-11*
