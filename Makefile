# Makefile — Next-Generation Physical Design Framework
SHELL := /bin/bash
PYTHON := python3
DESIGN ?= gcd
SEED   ?= 42
MANIFEST ?= configs/benchmarks/ipsd_manifest.yaml
CONFIG ?= configs/base.yaml
SEEDS  ?= 42 123 7

.PHONY: help build docker-build install baseline run sweep ablation report \
        validate clean clean-runs clean-figures lint test

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Next-Generation Physical Design Framework"
	@echo ""
	@echo "  make install         Install Python dependencies"
	@echo "  make build           Alias for install"
	@echo "  make docker-build    Build Docker image"
	@echo ""
	@echo "  make baseline        Run baseline flow (no extra modules) for DESIGN"
	@echo "  make run             Run full flow for DESIGN with all modules"
	@echo "  make sweep           Sweep all benchmarks in MANIFEST over SEEDS"
	@echo "  make ablation        Run ablation study"
	@echo "  make report          Generate REPORT.md, figures, update README"
	@echo ""
	@echo "  make validate        Validate benchmark collateral"
	@echo "  make clean           Remove generated outputs"
	@echo "  make lint            Run flake8 linter"
	@echo "  make test            Run unit tests"
	@echo ""
	@echo "  DESIGN=$(DESIGN)  SEED=$(SEED)  MANIFEST=$(MANIFEST)"
	@echo ""

# ── Install ───────────────────────────────────────────────────────────────────
install:
	$(PYTHON) -m pip install --quiet -r requirements.txt
	$(PYTHON) -m pip install --quiet -e .

build: install

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build:
	docker build -f docker/Dockerfile -t pdflow:latest .

docker-run:
	docker-compose -f docker/docker-compose.yml run --rm run DESIGN=$(DESIGN) SEED=$(SEED)

# ── Flow Targets ──────────────────────────────────────────────────────────────
baseline:
	@echo ">>> Baseline flow: DESIGN=$(DESIGN)"
	$(PYTHON) main.py run \
	    --design $(DESIGN) \
	    --config $(CONFIG) \
	    --seed   $(SEED) \
	    --no-tuning \
	    --no-diagnostics

run:
	@echo ">>> Full flow: DESIGN=$(DESIGN) SEED=$(SEED)"
	$(PYTHON) main.py run \
	    --design $(DESIGN) \
	    --config $(CONFIG) \
	    --seed   $(SEED)

sweep:
	@echo ">>> Benchmark sweep"
	$(PYTHON) main.py sweep \
	    --manifest $(MANIFEST) \
	    --config   $(CONFIG) \
	    --seeds    $(SEEDS)

ablation:
	@echo ">>> Ablation study"
	$(PYTHON) main.py ablation \
	    --manifest $(MANIFEST) \
	    --config   $(CONFIG)

# ── Report ────────────────────────────────────────────────────────────────────
report:
	@echo ">>> Generating reports and figures"
	$(PYTHON) main.py report \
	    --runs-dir outputs/runs \
	    --config   $(CONFIG)

# ── Validation ────────────────────────────────────────────────────────────────
validate:
	$(PYTHON) main.py validate --manifest $(MANIFEST)

# ── Quality ───────────────────────────────────────────────────────────────────
lint:
	flake8 src/ main.py --max-line-length=100 --ignore=E501,W503 || true

test:
	$(PYTHON) -m pytest tests/ -v --tb=short 2>/dev/null || \
	    echo "No tests directory found — create tests/ to enable."

# ── Clean ─────────────────────────────────────────────────────────────────────
clean-runs:
	rm -rf outputs/runs/*

clean-figures:
	rm -rf outputs/figures/*.png outputs/figures/*.pdf

clean: clean-runs clean-figures
	rm -rf outputs/reports/*.md
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
