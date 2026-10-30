# GitHub created this environment (with no branch policy) when the scheduled ingest first ran
# before apply. Adopt it so the plan updates it to main-only instead of failing on "exists".
import {
  to = github_repository_environment.ingest
  id = "${var.github_repository}:ingest"
}

resource "github_repository_environment" "ingest" {
  repository  = var.github_repository
  environment = "ingest"
  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "main" {
  repository     = var.github_repository
  environment    = github_repository_environment.ingest.environment
  branch_pattern = "main"
}

# Not secrets, but kept out of the public workflow file.
resource "github_actions_environment_variable" "ingest" {
  for_each = {
    AWS_ROLE_ARN = aws_iam_role.ingest.arn
    AWS_REGION   = data.aws_region.current.region
    LAKE_URI     = "s3://${aws_s3_bucket.lake.bucket}/${local.lake_prefix}"
  }
  repository    = var.github_repository
  environment   = github_repository_environment.ingest.environment
  variable_name = each.key
  value         = each.value
}
