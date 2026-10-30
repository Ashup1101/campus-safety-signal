import json

from campus_safety.lambdas import bronze_router


def s3_event(*keys: str) -> str:
    return json.dumps({"Records": [{"s3": {"object": {"key": key}}} for key in keys]})


def test_counts_new_manifests_per_source() -> None:
    event = {
        "Records": [
            {
                "messageId": "1",
                "body": s3_event(
                    "lake/bronze/news_ipm/ingest_date%3D2026-10-30/20261030T110000Z_r1.manifest.json",
                    "lake/bronze/news_ipm/ingest_date%3D2026-10-30/20261030T120000Z_r2.manifest.json",
                ),
            },
            {"messageId": "2", "body": json.dumps({"Event": "s3:TestEvent"})},
        ]
    }
    assert bronze_router.handler(event, None) == {"batchItemFailures": []}
    assert bronze_router.sources(event["Records"][0]["body"]) == ["news_ipm", "news_ipm"]


def test_malformed_messages_are_reported_for_retry() -> None:
    event = {
        "Records": [
            {"messageId": "bad-json", "body": "{not json"},
            {"messageId": "not-bronze", "body": s3_event("lake/silver/incidents.parquet")},
            {"messageId": "ok", "body": s3_event("lake/bronze/iu_crime_log/x/y.manifest.json")},
        ]
    }
    failures = bronze_router.handler(event, None)["batchItemFailures"]
    assert failures == [{"itemIdentifier": "bad-json"}, {"itemIdentifier": "not-bronze"}]
