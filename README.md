# campus-safety-signal

Campus safety context for Indiana University Bloomington students and parents, built only from
public sources: the IU Police Department daily crime log, Bloomington Police calls for service,
official notices, and local news. The goal is confirmed, privacy-preserving alerts and a map of
real incidents, not tracking and not "danger scores". It is also an LLM security project: every
fetched document is treated as untrusted input.

Status: data platform (Phase 1). The website, alerts, and app come later.

## Architecture

```
public sources ──> bronze (raw, write-once) ──> silver (observations, conformed) ──> gold
 IU crime log        S3, gzipped + manifest       dbt-duckdb, contract on           coverage,
 Wayback archive     If-None-Match writes         silver.incidents                  audits,
 BPD calls (SODA)    deletes denied by policy     history derived, never mutated    calibration
 BPS packets, Clery
```

- **Bronze** keeps every response exactly as fetched, with url, fetch time, sha256, and run id.
  Keys are unique and writes are create-only, so raw data can't be overwritten.
- **Silver** stores one observation per incident per snapshot. Current state, first and last seen,
  and disposition history are derived from observations by dbt.
- **Gold** holds reports: which dates the history covers, a data audit of the city feed, and a
  check of the feed against the city's own published totals.
- **Ingest** runs daily in GitHub Actions with a short-lived AWS role (OIDC, no stored keys) that
  can only write new raw objects; a launchd job on a laptop is the backup.
- **Infrastructure** is Terraform in `infra/`: S3 bucket, policies, IAM roles, GitHub environment.

## Privacy rules

- No stored user location. No people's names beyond the raw layer. No victim details.
- Sexual, domestic, stalking, and similar offenses are flagged and never enter alerts or logs.
- Fetchers identify themselves, check robots.txt first, and keep a low request rate.

## Run it

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv installs it).

```sh
make install      # dependencies + git hooks
make check        # lint, types, tests, dependency audit, terraform validate

export LAKE_URI="file://$PWD/data/lake"   # a local lake; s3://<bucket>/lake after terraform apply
uv run iu-crime-log run                   # fetch today's IU crime log into bronze
uv run bpd-cfs pull                       # BPD calls for service
make transform                            # bronze -> silver -> gold
uv run lake coverage                      # which dates the history covers
```

`make infra-plan` and `make infra-apply` read `AWS_PROFILE` and `AWS_REGION` from `.env`.
Data, notes, and secrets stay local and are gitignored.
