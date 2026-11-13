"""SNS publish of incident.confirmed events, and the topic/queue layout the consumers expect.

Topic: campus-safety-signal-incident-confirmed. One SQS queue per channel subscribes with raw
message delivery, each with a DLQ (pubsub.md). `provision` builds the same layout in tests
(moto) so the fan-out path is exercised end to end; production is Terraform (infra/alerts.tf).
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from campus_safety.alerts.events import IncidentConfirmed

if TYPE_CHECKING:
    from types_boto3_sns import SNSClient
    from types_boto3_sqs import SQSClient

TOPIC = "campus-safety-signal-incident-confirmed"
CHANNELS = ("email", "web_push")
MAX_RECEIVES = 5


def queue_name(channel: str, dead: bool = False) -> str:
    return f"campus-safety-signal-alerts-{channel}{'-dlq' if dead else ''}"


@dataclass(frozen=True)
class Layout:
    topic_arn: str
    queue_urls: dict[str, str]  # channel -> URL
    dlq_urls: dict[str, str]


def publish(sns: "SNSClient", topic_arn: str, event: IncidentConfirmed) -> str:
    """Returns the SNS message id. Attributes let a queue filter by kind or severity later."""
    answer = sns.publish(
        TopicArn=topic_arn,
        Message=event.to_json(),
        MessageAttributes={
            "kind": {"DataType": "String", "StringValue": event.kind},
            "severity": {"DataType": "String", "StringValue": event.severity},
        },
    )
    return str(answer["MessageId"])


def provision(sns: "SNSClient", sqs: "SQSClient") -> Layout:
    topic_arn = str(sns.create_topic(Name=TOPIC)["TopicArn"])
    queues: dict[str, str] = {}
    dlqs: dict[str, str] = {}
    for channel in CHANNELS:
        dlq_url = str(sqs.create_queue(QueueName=queue_name(channel, dead=True))["QueueUrl"])
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        url = str(
            sqs.create_queue(
                QueueName=queue_name(channel),
                Attributes={
                    "RedrivePolicy": json.dumps(
                        {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": MAX_RECEIVES}
                    )
                },
            )["QueueUrl"]
        )
        arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"][
            "QueueArn"
        ]
        sns.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=arn,
            Attributes={"RawMessageDelivery": "true"},
        )
        queues[channel], dlqs[channel] = url, dlq_url
    return Layout(topic_arn, queues, dlqs)
