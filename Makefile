.PHONY: install lint format typecheck test audit check backup schedule unschedule \
	infra-check infra-plan infra-apply transform demo-seed demo-drill demo-all-clear demo-replay \
	demo-assets demo demo-stop demo-walk demo-walk-home apps-check

# One KEY=value from .env, read without sourcing it (values are never executed).
env = $(shell sed -n 's/^$(1)=//p' .env 2>/dev/null | tail -n 1 | tr -d "\"'")

# The lake: a file:// lake under data/ until .env sets LAKE_URI=s3://<bucket>/lake.
LAKE_URI := $(or $(call env,LAKE_URI),file://$(CURDIR)/data/lake)
AWS_ENV := $(if $(call env,AWS_PROFILE),AWS_PROFILE='$(call env,AWS_PROFILE)') \
	$(if $(call env,AWS_REGION),AWS_REGION='$(call env,AWS_REGION)')

# Pinned Terraform, checksum-verified, kept under .tools/ (gitignored); same binary as CI.
TF_VERSION := 1.16.5
TF_SHA256_darwin_arm64 := ecdef65e24193d627f27c39baeda31295f08c938d8a3d4764f442fb916d4b7dc
TF_SHA256_linux_amd64 := 2bc2fcfff033265c9e02ca0351f01794eb122f62a9b2a49a3294b9e49eaab5e4
TF_PLATFORM := $(shell uname -s | tr A-Z a-z)_$(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
TF := .tools/terraform-$(TF_VERSION)/terraform

install:
	uv sync --locked
	uv run pre-commit install --install-hooks

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

# Audit the locked set (dev tools included); uv venvs ship without pip, so skip it.
audit:
	uv export --locked --no-emit-project --format requirements-txt \
		| uv run pip-audit --require-hashes --disable-pip -r /dev/stdin

check: lint typecheck test audit infra-check

# Replay all of bronze into silver: parse, dbt build (tests + contract), publish.
# EXTRACTOR=llm_fallback adds cached T3-lite answers for snapshots the rules could not read.
EXTRACTOR ?= rules
transform:
	LAKE_URI='$(LAKE_URI)' $(AWS_ENV) uv run lake transform --extractor $(EXTRACTOR)

# Local-only notes (CLAUDE.md, .notes/) to s3://<bucket>/_private/notes/; S3 versioning keeps
# every earlier copy. The lake itself is already versioned in S3.
backup:
	LAKE_URI='$(LAKE_URI)' $(AWS_ENV) uv run lake backup-notes

# Daily LaunchAgent for `iu-crime-log run` (macOS).
schedule:
	uv run python scripts/launchd_job.py install

unschedule:
	uv run python scripts/launchd_job.py uninstall

$(TF):
	@hash='$(TF_SHA256_$(TF_PLATFORM))'; \
	test -n "$$hash" || { echo "no pinned terraform for $(TF_PLATFORM)" >&2; exit 1; }; \
	dir='$(dir $(TF))'; zip="$$dir/terraform.zip"; mkdir -p "$$dir"; \
	curl -sSfL -o "$$zip" \
		https://releases.hashicorp.com/terraform/$(TF_VERSION)/terraform_$(TF_VERSION)_$(TF_PLATFORM).zip; \
	echo "$$hash  $$zip" | shasum -a 256 -c - >/dev/null || { rm -f "$$zip"; exit 1; }; \
	unzip -q -o "$$zip" terraform -d "$$dir" && rm "$$zip"

# No credentials needed: formatting and schema validation only (also run in CI).
infra-check: $(TF)
	$(TF) -chdir=infra fmt -check -recursive
	$(TF) -chdir=infra init -backend=false -input=false -lockfile=readonly >/dev/null
	$(TF) -chdir=infra validate

# Plan with the AWS profile and region from .env and the gh CLI's token; review, then apply.
infra-plan: $(TF)
	@test -n '$(call env,AWS_PROFILE)' -a -n '$(call env,AWS_REGION)' \
		|| { echo "set AWS_PROFILE and AWS_REGION in .env" >&2; exit 1; }
	AWS_PROFILE='$(call env,AWS_PROFILE)' AWS_REGION='$(call env,AWS_REGION)' \
		GITHUB_TOKEN="$$(gh auth token)" sh -c \
		'$(TF) -chdir=infra init -input=false -lockfile=readonly && $(TF) -chdir=infra plan -input=false -out=tfplan'

# Applies exactly the reviewed plan file.
infra-apply: $(TF)
	AWS_PROFILE='$(call env,AWS_PROFILE)' AWS_REGION='$(call env,AWS_REGION)' \
		GITHUB_TOKEN="$$(gh auth token)" $(TF) -chdir=infra apply -input=false tfplan

# Local IUPD demo server (apps/server, 127.0.0.1 only). Drills and replays reach test accounts only.
DEMO := PYTHONPATH=apps/server nice -n 10 uv run python -m demo_server
demo-seed:
	$(DEMO) seed

demo-drill:
	$(DEMO) drill

demo-all-clear:
	$(DEMO) all-clear

# make demo-replay REPLAY=kirkwood_2026_11_01 (ids: data/manual/demo_incidents.yaml)
demo-replay:
	@test -n '$(REPLAY)' || { echo "usage: make demo-replay REPLAY=<id>" >&2; exit 1; }
	$(DEMO) replay '$(REPLAY)'

# Pinned pmtiles CLI (go-pmtiles, checksum-verified, macOS arm64) for the offline map extract.
PMTILES_VERSION := 1.31.2
PMTILES_SHA256 := 40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d
PMTILES := .tools/pmtiles-$(PMTILES_VERSION)/pmtiles

$(PMTILES):
	@test "$(TF_PLATFORM)" = darwin_arm64 || { echo "demo assets: macOS arm64 only" >&2; exit 1; }
	@dir='$(dir $(PMTILES))'; zip="$$dir/pmtiles.zip"; mkdir -p "$$dir"; \
	curl -sSfL -o "$$zip" \
		https://github.com/protomaps/go-pmtiles/releases/download/v$(PMTILES_VERSION)/go-pmtiles-$(PMTILES_VERSION)_Darwin_arm64.zip; \
	echo "$(PMTILES_SHA256)  $$zip" | shasum -a 256 -c - >/dev/null || { rm -f "$$zip"; exit 1; }; \
	unzip -q -o "$$zip" pmtiles -d "$$dir" && rm "$$zip"

# Offline map for the demo web app: Bloomington extract + fonts + sprites into data/demo/tiles/.
demo-assets: $(PMTILES)
	nice -n 10 uv run python scripts/fetch_demo_assets.py $(PMTILES)

# The whole local demo: server (127.0.0.1:8100), web (localhost:3100), iPhone app in one Simulator.
# Installs node packages only if missing. `make demo-stop` ends every demo process.
demo:
	uv run python scripts/demo.py start

demo-stop:
	uv run python scripts/demo.py stop

# Move the Simulator along Kirkwood into the 400 block, then home (Share until I'm home).
demo-walk:
	uv run python scripts/demo.py walk

demo-walk-home:
	uv run python scripts/demo.py walk-home

# TypeScript checks for both apps (also in CI). Installs node packages only if missing.
apps-check:
	cd apps/web && { test -d node_modules || npm ci --no-fund --no-audit; } && npm run typecheck && npm run lint
	cd apps/mobile && { test -d node_modules || npm ci --no-fund --no-audit; } && npm run typecheck
