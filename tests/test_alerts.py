"""Phase 7 alert engine: rules, templates, events, ledger, SNS/SQS fan-out with moto, Lambda
consumer idempotency, CLI. All accounts and incidents are made up."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import duckdb
import pytest
from moto import mock_aws

from campus_safety.alerts import directory, events, publish, snapshots
from campus_safety.alerts.channels import ChannelError, LogChannel, ResendEmail
from campus_safety.alerts.cli import main
from campus_safety.alerts.ledger import LakeLedger, MemoryLedger, delivery_key
from campus_safety.alerts.rules import CLOSING, Incident, Subscriber, decide, recipients, render
from campus_safety.lake.storage import FileLake, S3Lake
from campus_safety.lambdas import alert_fanout

NOW = datetime(2026, 11, 1, 6, 45, tzinfo=UTC)
SHOOTING = Incident(
    "inc-1", "official", True, "high", "SHOOTING", "400 block of E Kirkwood Ave",
    ("kirkwood_400",), datetime(2026, 11, 1, 1, 31), False, 7, NOW - timedelta(minutes=5),
)  # fmt: skip
MOM = Subscriber("parent_mom", "parent", ("kirkwood_400",), ("email",), test_account=True)
SAM = Subscriber("student_sam", "student", ("kirkwood_400", "campus"), ("email", "web_push"))
FAR = Subscriber("parent_far", "parent", ("campus",), ("email",))
DIGEST = Subscriber("digest_only", "parent", ("kirkwood_400",), ("email",), digest_only=True)
ENTRIES = [
    directory.Entry(MOM, {"email": "mom@example.test"}),
    directory.Entry(SAM, {"email": "sam@example.test", "web_push": "push-1"}),
    directory.Entry(FAR, {"email": "far@example.test"}),
    directory.Entry(DIGEST, {"email": "digest@example.test"}),
]


def test_rules_follow_the_alert_policy() -> None:
    assert decide(SHOOTING).route == "alert"
    news_two = Incident("n1", "news", True, "medium", "ROBBERY", "Walnut", ("z",), None, False)
    news_one = Incident("n2", "news", False, "high", "SHOOTING", "Walnut", ("z",), None, False)
    assert decide(news_two).route == "alert" and decide(news_one).route == "none"
    sensitive = Incident("s1", "official", True, "high", "RAPE", "X", ("z",), None, True)
    assert decide(sensitive).route == "none" and "sensitive" in decide(sensitive).reason
    synthetic = Incident("y1", "synthetic", True, "high", "ROBBERY", "X", ("z",), None, False)
    assert decide(synthetic).route == "none"
    low = Incident("l1", "official", True, "low", "ILLEGAL CONSUMPTION", "X", ("z",), None, False)
    assert decide(low).route == "digest"


def test_recipients_need_a_shared_zone_and_never_a_blast() -> None:
    assert [s.subscriber_id for s in recipients(SHOOTING, [MOM, SAM, FAR, DIGEST])] == [
        "parent_mom",
        "student_sam",
    ]
    no_zone = Incident("z0", "official", True, "high", "SHOOTING", None, (), None, False)
    assert recipients(no_zone, [MOM, SAM, FAR]) == []


def test_templates_use_fields_only_and_the_static_closing_line() -> None:
    draft = render(SHOOTING)
    assert draft.title == "Shooting near 400 block of E Kirkwood Ave"
    assert draft.body.startswith("Shooting near 400 block of E Kirkwood Ave, Sun Nov 1, 1:31 AM")
    assert "7 injured" in draft.body and draft.body.endswith(CLOSING)
    assert render(SHOOTING, "all_clear").title.startswith("All clear:")
    assert (
        "two local news outlets"
        in render(
            Incident("n", "news", True, "medium", "ROBBERY", "Walnut St", ("z",), None, False),
            "correction",
        ).body
    )


def test_event_round_trip_and_strict_parsing() -> None:
    event = events.IncidentConfirmed(
        "inc-1", "alert", "high", ("kirkwood_400",), "official", ("k",), NOW, NOW
    )
    assert events.parse(event.to_json()) == event
    assert event.dedupe_key == "inc-1|alert"
    body = json.loads(event.to_json())
    for bad in (
        {**body, "extra": 1},
        {**body, "kind": "spam"},
        {**body, "version": 2},
        {**body, "zone_ids": "kirkwood_400"},
        {**body, "confirmed_at": "2026-11-01T06:45:00"},
        {**body, "source": "synthetic"},
    ):
        with pytest.raises(events.EventError):
            events.parse(json.dumps(bad))
    with pytest.raises(events.EventError):
        events.parse("{not json")


def test_ledger_claims_once(tmp_path: Path) -> None:
    for ledger in (MemoryLedger(), LakeLedger(FileLake(tmp_path / "lake"))):
        key = delivery_key("inc-1", "alert", "parent_mom", "email")
        assert ledger.claim(key, NOW, NOW - timedelta(seconds=30))
        assert not ledger.claim(key, NOW)
        assert ledger.claims("delivered/inc-1") == [key]


def test_deliver_once_per_subscriber_and_channel() -> None:
    event = events.IncidentConfirmed(
        "inc-1", "alert", "high", ("kirkwood_400",), "official", ("k",), NOW
    )
    email, ledger = LogChannel("email"), MemoryLedger()
    first = alert_fanout.deliver(event, SHOOTING, ENTRIES, email, ledger, lambda: NOW)
    assert (first.delivered, first.already, first.skipped) == (2, 0, 0)
    assert [address for address, _ in email.sent] == ["mom@example.test", "sam@example.test"]
    again = alert_fanout.deliver(event, SHOOTING, ENTRIES, email, ledger, lambda: NOW)
    assert (again.delivered, again.already) == (0, 2) and len(email.sent) == 2
    push = LogChannel("web_push")
    pushed = alert_fanout.deliver(event, SHOOTING, ENTRIES, push, ledger, lambda: NOW)
    assert (pushed.delivered, pushed.skipped) == (1, 1)  # Mom has no push address


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


def test_sns_fans_out_to_every_channel_queue_and_the_lambda_is_idempotent(
    aws: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sns, sqs = (
        boto3.client("sns", region_name="us-east-2"),
        boto3.client("sqs", region_name="us-east-2"),
    )
    layout = publish.provision(sns, sqs)
    s3 = boto3.client("s3", region_name="us-east-2")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    lake = S3Lake("lake", "lake", s3)
    snapshots.store_incident(lake, SHOOTING)
    snapshots.store_directory(lake, ENTRIES)
    event = events.IncidentConfirmed(
        "inc-1", "alert", "high", ("kirkwood_400",), "official", ("k",), NOW, NOW
    )
    assert publish.publish(sns, layout.topic_arn, event)
    monkeypatch.setenv(alert_fanout.CHANNEL_VAR, "web_push")
    for channel, url in layout.queue_urls.items():
        messages = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
        assert len(messages) == 1, channel
        assert events.parse(messages[0]["Body"]) == event  # raw delivery, no SNS envelope
        records = {"Records": [{"messageId": m["MessageId"], "body": m["Body"]} for m in messages]}
        assert alert_fanout.handler(records, None, lake) == {"batchItemFailures": []}
    assert sorted(LakeLedger(lake).claims("delivered/")) == [
        "delivered/inc-1/alert/student_sam/web_push"
    ]
    assert alert_fanout.handler(records, None, lake) == {"batchItemFailures": []}
    assert len(LakeLedger(lake).claims("delivered/")) == 1
    bad = {
        "Records": [
            {"messageId": "x", "body": "{}"},
            {"messageId": "y", "body": event.to_json().replace("inc-1", "nope")},
        ]
    }
    assert alert_fanout.handler(bad, None, lake) == {
        "batchItemFailures": [{"itemIdentifier": "x"}, {"itemIdentifier": "y"}]
    }


def test_resend_channel_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.request

    seen: dict[str, object] = {}

    class Response(io.BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    def urlopen(request: urllib.request.Request, timeout: float) -> Response:
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(bytes(request.data) if isinstance(request.data, bytes) else b"{}")
        return Response(b'{"id": "re_1"}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(ChannelError):
        ResendEmail()
    channel = ResendEmail("key", "alerts@example.test")
    assert channel.send("mom@example.test", render(SHOOTING)) == "re_1"
    assert seen["url"] == "https://api.resend.com/emails" and seen["auth"] == "Bearer key"
    body = seen["body"]
    assert isinstance(body, dict) and body["to"] == ["mom@example.test"]
    assert "Unsubscribe" in body["text"]


def test_directory_loads_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "subscribers.yaml"
    path.write_text(
        "subscribers:\n  - subscriber_id: parent_mom\n    role: parent\n"
        "    zone_ids: [kirkwood_400]\n"
        "    channels: {email: mom@example.test}\n    test_account: true\n"
    )
    (entry,) = directory.load(path)
    assert entry.subscriber.channels == ("email",) and entry.addresses == {
        "email": "mom@example.test"
    }
    path.write_text(
        "subscribers:\n  - subscriber_id: x\n    role: parent\n    channels: {fax: 1}\n"
    )
    with pytest.raises(directory.DirectoryError):
        directory.load(path)
    assert directory.load(tmp_path / "missing.yaml") == []


def warehouse(path: Path) -> Path:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA gold; CREATE SCHEMA silver")
        con.execute(
            "CREATE TABLE gold.incidents_real (incident_id VARCHAR, source VARCHAR,"
            " source_record_id VARCHAR,"
            " severity_tier VARCHAR, incident_type VARCHAR, location_text VARCHAR, zone_id VARCHAR,"
            " occurred_from TIMESTAMP, is_sensitive BOOLEAN, injuries INTEGER, date_reported DATE)"
        )
        con.execute("CREATE TABLE silver.news_incidents (cluster_id VARCHAR, confirmed BOOLEAN)")
        con.executemany(
            "INSERT INTO gold.incidents_real VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "o1",
                    "official",
                    "c1",
                    "high",
                    "ROBBERY",
                    "KIRKWOOD AVE",
                    None,
                    NOW.replace(tzinfo=None),
                    False,
                    None,
                    NOW.date(),
                ),
                (
                    "o2",
                    "official",
                    "c2",
                    "low",
                    "ALCOHOL",
                    "TETER QUAD",
                    None,
                    NOW.replace(tzinfo=None),
                    False,
                    None,
                    NOW.date(),
                ),
                (
                    "o3",
                    "official",
                    "c3",
                    "high",
                    "RAPE",
                    "X",
                    None,
                    NOW.replace(tzinfo=None),
                    True,
                    None,
                    NOW.date(),
                ),
                (
                    "n1",
                    "news",
                    "cl1",
                    "medium",
                    "assault",
                    "Dunn Meadow",
                    None,
                    NOW.replace(tzinfo=None),
                    False,
                    1,
                    NOW.date(),
                ),
                (
                    "n2",
                    "news",
                    "cl2",
                    "high",
                    "shooting",
                    "Walnut",
                    None,
                    NOW.replace(tzinfo=None),
                    False,
                    2,
                    NOW.date(),
                ),
            ],
        )
        con.executemany(
            "INSERT INTO silver.news_incidents VALUES (?, ?)", [("cl1", True), ("cl2", False)]
        )
    return path


def test_cli_decide_publish_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lake = FileLake(tmp_path / "lake")
    monkeypatch.setenv("LAKE_URI", lake.uri)
    monkeypatch.delenv("ALERTS_TOPIC_ARN", raising=False)
    caplog.set_level(logging.INFO)
    db = warehouse(tmp_path / "w.duckdb")
    base = ["--warehouse", str(db), "--since", "2026-10-01"]
    assert main([*base, "decide"]) == 0
    assert "5 incidents since 2026-10-01: {'alert': 2, 'digest': 1, 'none': 2}" in caplog.text
    assert main([*base, "publish"]) == 0
    assert "2 events published to the lake outbox" in caplog.text
    assert main([*base, "publish"]) == 0
    assert "0 events published" in caplog.text  # ledger: once per incident
    assert sorted(lake.keys("alerts/outbox/")) == [
        "alerts/outbox/n1/alert.json",
        "alerts/outbox/o1/alert.json",
    ]
    assert snapshots.load_incident(lake, "o1") is not None
    path = tmp_path / "subscribers.yaml"
    path.write_text(
        "subscribers:\n  - subscriber_id: m\n    role: parent\n    zone_ids: [KIRKWOOD AVE]\n"
        "    channels: {web_push: endpoint-1}\n"
    )
    assert main([*base, "sync-directory", "--path", str(path)]) == 0
    assert len(snapshots.load_directory(lake)) == 1
    outbox = json.loads(lake.get("alerts/outbox/o1/alert.json"))
    records = {"Records": [{"messageId": "1", "body": json.dumps(outbox)}]}
    monkeypatch.setenv(alert_fanout.CHANNEL_VAR, "web_push")
    assert alert_fanout.handler(records, None, lake) == {"batchItemFailures": []}
    assert main([*base, "report"]) == 0
    assert "2 incidents published, 1 deliveries {'web_push': 1}" in caplog.text
    assert main(["--warehouse", str(tmp_path / "missing.duckdb"), "decide"]) == 1
