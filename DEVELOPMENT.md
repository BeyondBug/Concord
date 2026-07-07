# Concord Development Guide

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Git
- Jash also needs: kubectl, kind/k3d, Terraform
- rj-karan also needs: Prometheus (for observability agent)

## Quick Start

    git clone https://github.com/BeyondBug/Concord.git
    cd Concord
    make setup
    make dev
    # API running at http://localhost:8000/health

## Branch Naming

    feature/jash/<name>      Infra and K8s agent work
    feature/m2/<name>        CI/CD and Observability agent work
    feature/common/<name>    Shared core work

## PR Process

1. Open PR against develop (never directly to main)
2. Other member reviews + Claude Code review
3. All unit tests pass (CI enforces this)
4. Friday: merge to develop, demo, then merge develop to main

## Friday Demo Rule

Every Friday: something runs end-to-end.
Run: pytest tests/integration/test_e2e.py -v
If it fails, it is the only priority for that week.
