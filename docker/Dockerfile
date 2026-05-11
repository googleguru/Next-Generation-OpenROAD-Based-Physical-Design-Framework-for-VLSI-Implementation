FROM ubuntu:22.04

LABEL maintainer="R.Pavithra Guru"
LABEL description="Next-Generation Physical Design Framework"

ARG DEBIAN_FRONTEND=noninteractive
ARG PYTHON_VERSION=3.11

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    git \
    build-essential \
    tcl \
    tcl-dev \
    swig \
    bison \
    flex \
    libreadline-dev \
    gawk \
    graphviz \
    xdot \
    pkg-config \
    python3 \
    python3-pip \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libeigen3-dev \
    libboost-all-dev \
    libspdlog-dev \
    cmake \
    ninja-build \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python packages ─────────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ── OpenROAD binary ──────────────────────────────────────────────────────────
# Install from pre-built binary if available; otherwise build from source.
# Set EDA_BINARY env var to override the default 'openroad' command.
RUN if command -v openroad &>/dev/null; then \
        echo "openroad found in base image"; \
    else \
        echo "OpenROAD not found — install manually or mount via volume."; \
        echo "See: https://github.com/The-OpenROAD-Project/OpenROAD"; \
    fi

# ── Yosys (synthesis) ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends yosys \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    || echo "Yosys not available via apt — skipping"

# ── Framework source ─────────────────────────────────────────────────────────
WORKDIR /workspace
COPY . /workspace/

RUN pip3 install --no-cache-dir -e .

# ── Output directories ───────────────────────────────────────────────────────
RUN mkdir -p \
    outputs/runs \
    outputs/figures \
    outputs/tables \
    outputs/logs \
    outputs/reports \
    benchmarks/ipsd \
    benchmarks/iscas \
    pdks

# ── Entrypoint ───────────────────────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/workspace/benchmarks", "/workspace/pdks", "/workspace/outputs"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
