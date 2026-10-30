# Phase 2a: a new bronze manifest -> S3 event -> SQS (DLQ + redrive) -> Lambda. Off by default:
# plan it with -var enable_bronze_events=true; the first apply stays the 1.0 foundation.
variable "enable_bronze_events" {
  type    = bool
  default = false
}

locals {
  events = var.enable_bronze_events ? 1 : 0
  router = "campus-safety-signal-bronze-router"
}

data "archive_file" "bronze_router" {
  count       = local.events
  type        = "zip"
  source_file = "${path.module}/../src/campus_safety/lambdas/bronze_router.py"
  output_path = "${path.module}/.build/bronze_router.zip"
}

resource "aws_sqs_queue" "bronze_events_dlq" {
  count                     = local.events
  name                      = "campus-safety-signal-bronze-events-dlq"
  message_retention_seconds = 1209600 # 14 days to inspect failures
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "bronze_events" {
  count                      = local.events
  name                       = "campus-safety-signal-bronze-events"
  visibility_timeout_seconds = 180 # 6x the Lambda timeout
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.bronze_events_dlq[0].arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "bronze_events_queue" {
  count = local.events
  statement {
    sid       = "S3SendsOnlyForThisBucket"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.bronze_events[0].arn]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.lake.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "bronze_events" {
  count     = local.events
  queue_url = aws_sqs_queue.bronze_events[0].id
  policy    = data.aws_iam_policy_document.bronze_events_queue[0].json
}

# Manifests are written after their raw object, so a manifest event means the pair is complete.
resource "aws_s3_bucket_notification" "lake" {
  count  = local.events
  bucket = aws_s3_bucket.lake.id
  queue {
    queue_arn     = aws_sqs_queue.bronze_events[0].arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "${local.lake_prefix}/bronze/"
    filter_suffix = ".manifest.json"
  }
  depends_on = [aws_sqs_queue_policy.bronze_events]
}

resource "aws_cloudwatch_log_group" "bronze_router" {
  count             = local.events
  name              = "/aws/lambda/${local.router}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "lambda_trust" {
  count = local.events
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "bronze_router" {
  count = local.events
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bronze_router[0].arn}:*"]
  }
  statement {
    sid = "ConsumeQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.bronze_events[0].arn]
  }
}

resource "aws_iam_role" "bronze_router" {
  count              = local.events
  name               = local.router
  assume_role_policy = data.aws_iam_policy_document.lambda_trust[0].json
}

resource "aws_iam_role_policy" "bronze_router" {
  count  = local.events
  name   = "consume-bronze-events"
  role   = aws_iam_role.bronze_router[0].id
  policy = data.aws_iam_policy_document.bronze_router[0].json
}

resource "aws_lambda_function" "bronze_router" {
  count                          = local.events
  function_name                  = local.router
  role                           = aws_iam_role.bronze_router[0].arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "bronze_router.handler"
  filename                       = data.archive_file.bronze_router[0].output_path
  source_code_hash               = data.archive_file.bronze_router[0].output_base64sha256
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 2 # caps cost and fan-out
  depends_on                     = [aws_cloudwatch_log_group.bronze_router]
}

resource "aws_lambda_event_source_mapping" "bronze_events" {
  count                   = local.events
  event_source_arn        = aws_sqs_queue.bronze_events[0].arn
  function_name           = aws_lambda_function.bronze_router[0].arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_cloudwatch_metric_alarm" "bronze_events_dlq" {
  count               = local.events
  alarm_name          = "campus-safety-signal-bronze-events-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.bronze_events_dlq[0].name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
}
