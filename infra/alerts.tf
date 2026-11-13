# Phase 7: incident.confirmed -> SNS -> one SQS queue per channel (DLQ + redrive) -> fan-out
# Lambda per channel. Off by default: plan it with -var enable_alerts=true.
variable "enable_alerts" {
  type    = bool
  default = false
}

locals {
  alerts         = var.enable_alerts ? 1 : 0
  alert_channels = var.enable_alerts ? toset(["email", "web_push"]) : toset([])
  alerts_prefix  = "campus-safety-signal-alerts"
}

resource "aws_sns_topic" "incident_confirmed" {
  count             = local.alerts
  name              = "campus-safety-signal-incident-confirmed"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sqs_queue" "alerts_dlq" {
  for_each                  = local.alert_channels
  name                      = "${local.alerts_prefix}-${each.key}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "alerts" {
  for_each                   = local.alert_channels
  name                       = "${local.alerts_prefix}-${each.key}"
  visibility_timeout_seconds = 180
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.alerts_dlq[each.key].arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "alerts_queue" {
  for_each = local.alert_channels
  statement {
    sid       = "TopicSendsOnly"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alerts[each.key].arn]
    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.incident_confirmed[0].arn]
    }
  }
}

resource "aws_sqs_queue_policy" "alerts" {
  for_each  = local.alert_channels
  queue_url = aws_sqs_queue.alerts[each.key].id
  policy    = data.aws_iam_policy_document.alerts_queue[each.key].json
}

resource "aws_sns_topic_subscription" "alerts" {
  for_each             = local.alert_channels
  topic_arn            = aws_sns_topic.incident_confirmed[0].arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.alerts[each.key].arn
  raw_message_delivery = true
}

# Alarm on any message in a dead-letter queue (pubsub.md).
resource "aws_cloudwatch_metric_alarm" "alerts_dlq" {
  for_each            = local.alert_channels
  alarm_name          = "${local.alerts_prefix}-${each.key}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.alerts_dlq[each.key].name
  }
}

# The whole package: the fan-out imports campus_safety.alerts.* (stdlib + boto3 only).
data "archive_file" "alert_fanout" {
  count       = local.alerts
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/.build/alert_fanout.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "alert_fanout" {
  for_each          = local.alert_channels
  name              = "/aws/lambda/${local.alerts_prefix}-${each.key}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "alerts_lambda_trust" {
  count = local.alerts
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "alert_fanout" {
  for_each = local.alert_channels
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.alert_fanout[each.key].arn}:*"]
  }
  statement {
    sid = "ConsumeQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.alerts[each.key].arn]
  }
  statement {
    sid       = "ReadSnapshotsAndDirectory"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.lake.arn}/${local.lake_prefix}/alerts/*"]
  }
  statement {
    sid       = "ClaimDeliveriesWriteOnce"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.lake.arn}/${local.lake_prefix}/alerts/delivered/*"]
  }
  statement {
    sid       = "ListLedger"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.lake.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.lake_prefix}/alerts/*"]
    }
  }
}

resource "aws_iam_role" "alert_fanout" {
  for_each           = local.alert_channels
  name               = "${local.alerts_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.alerts_lambda_trust[0].json
}

resource "aws_iam_role_policy" "alert_fanout" {
  for_each = local.alert_channels
  name     = "fan-out-${each.key}"
  role     = aws_iam_role.alert_fanout[each.key].id
  policy   = data.aws_iam_policy_document.alert_fanout[each.key].json
}

resource "aws_lambda_function" "alert_fanout" {
  for_each                       = local.alert_channels
  function_name                  = "${local.alerts_prefix}-${each.key}"
  role                           = aws_iam_role.alert_fanout[each.key].arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "campus_safety.lambdas.alert_fanout.handler"
  filename                       = data.archive_file.alert_fanout[0].output_path
  source_code_hash               = data.archive_file.alert_fanout[0].output_base64sha256
  timeout                        = 30
  memory_size                    = 256
  reserved_concurrent_executions = 2
  environment {
    variables = {
      ALERT_CHANNEL = each.key
      LAKE_URI      = "s3://${aws_s3_bucket.lake.bucket}/${local.lake_prefix}"
      # RESEND_API_KEY and ALERTS_FROM come from SSM at deploy time, never from this file.
    }
  }
  depends_on = [aws_cloudwatch_log_group.alert_fanout]
}

resource "aws_lambda_event_source_mapping" "alert_fanout" {
  for_each                           = local.alert_channels
  event_source_arn                   = aws_sqs_queue.alerts[each.key].arn
  function_name                      = aws_lambda_function.alert_fanout[each.key].arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 1
  function_response_types            = ["ReportBatchItemFailures"]
}

output "incident_confirmed_topic_arn" {
  value = var.enable_alerts ? aws_sns_topic.incident_confirmed[0].arn : null
}
