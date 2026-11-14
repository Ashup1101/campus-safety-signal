# The daily capture runs in AWS: EventBridge Scheduler (14:17 UTC) -> Lambda -> bronze. Used
# when the GitHub OIDC provider cannot be created (enable_github_oidc = false); costs fall in
# the free tier (one ~30 s invocation a day).
variable "enable_daily_ingest" {
  type    = bool
  default = true
}

locals {
  daily      = var.enable_daily_ingest ? 1 : 0
  daily_name = "campus-safety-signal-daily-ingest"
}

# The package is src/campus_safety plus certifi (make lambda-package, run by make infra-plan):
# the capture path needs only the standard library, boto3 (in the runtime) and certifi.
data "archive_file" "daily_ingest" {
  count       = local.daily
  type        = "zip"
  source_dir  = "${path.module}/.build/package"
  output_path = "${path.module}/.build/daily_ingest.zip"
}

resource "aws_cloudwatch_log_group" "daily_ingest" {
  count             = local.daily
  name              = "/aws/lambda/${local.daily_name}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "daily_ingest_trust" {
  count = local.daily
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "daily_ingest" {
  count = local.daily
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.daily_ingest[0].arn}:*"]
  }
  statement {
    sid       = "WriteAndReadBronze"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = [local.bronze_arn]
  }
  # The 12-hour guard and the collectors' unchanged check list bronze manifests.
  statement {
    sid       = "ListBronze"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.lake.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.lake_prefix}/bronze/*"]
    }
  }
}

resource "aws_iam_role" "daily_ingest" {
  count              = local.daily
  name               = local.daily_name
  assume_role_policy = data.aws_iam_policy_document.daily_ingest_trust[0].json
}

resource "aws_iam_role_policy" "daily_ingest" {
  count  = local.daily
  name   = "capture-to-bronze"
  role   = aws_iam_role.daily_ingest[0].id
  policy = data.aws_iam_policy_document.daily_ingest[0].json
}

resource "aws_lambda_function" "daily_ingest" {
  count            = local.daily
  function_name    = local.daily_name
  role             = aws_iam_role.daily_ingest[0].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "campus_safety.lambdas.daily_ingest.handler"
  filename         = data.archive_file.daily_ingest[0].output_path
  source_code_hash = data.archive_file.daily_ingest[0].output_base64sha256
  timeout          = 180
  memory_size      = 256
  environment {
    variables = {
      LAKE_URI = "s3://${aws_s3_bucket.lake.bucket}/${local.lake_prefix}"
    }
  }
  depends_on = [aws_cloudwatch_log_group.daily_ingest]
}

data "aws_iam_policy_document" "scheduler_trust" {
  count = local.daily
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "daily_ingest_scheduler" {
  count              = local.daily
  name               = "${local.daily_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust[0].json
}

resource "aws_iam_role_policy" "daily_ingest_scheduler" {
  count = local.daily
  name  = "invoke-daily-ingest"
  role  = aws_iam_role.daily_ingest_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.daily_ingest[0].arn
    }]
  })
}

resource "aws_scheduler_schedule" "daily_ingest" {
  count                        = local.daily
  name                         = local.daily_name
  schedule_expression          = "cron(17 14 * * ? *)"
  schedule_expression_timezone = "UTC"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.daily_ingest[0].arn
    role_arn = aws_iam_role.daily_ingest_scheduler[0].arn
    retry_policy {
      maximum_retry_attempts       = 1
      maximum_event_age_in_seconds = 3600
    }
  }
}

output "daily_ingest_function" {
  value = var.enable_daily_ingest ? aws_lambda_function.daily_ingest[0].function_name : null
}
