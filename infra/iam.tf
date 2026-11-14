locals {
  oidc            = var.enable_github_oidc ? 1 : 0
  github_oidc_url = "https://token.actions.githubusercontent.com"
  github_oidc_arn = (
    !var.enable_github_oidc ? null
    : var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github[0].arn
  )
  ingest_subject = "repo:${var.github_owner}/${var.github_repository}:environment:ingest"
}

# Local work (transform, backups, imports) assumes this role from a profile in the account.
data "aws_iam_policy_document" "local" {
  statement {
    sid       = "ListLake"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.lake.arn]
  }

  statement {
    sid       = "ReadWriteLake"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.lake.arn}/*"]
  }

  statement {
    sid     = "DeleteDerivedOnly"
    actions = ["s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.lake.arn}/${local.lake_prefix}/silver/*",
      "${aws_s3_bucket.lake.arn}/${local.lake_prefix}/gold/*",
    ]
  }

  statement {
    sid       = "NeverDeleteBronze"
    effect    = "Deny"
    actions   = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = [local.bronze_arn]
  }
}

resource "aws_iam_policy" "local" {
  name   = "campus-safety-signal-local"
  policy = data.aws_iam_policy_document.local.json
}

data "aws_iam_policy_document" "local_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "local" {
  name               = "campus-safety-signal-local"
  assume_role_policy = data.aws_iam_policy_document.local_trust.json
}

resource "aws_iam_role_policy_attachment" "local" {
  role       = aws_iam_role.local.name
  policy_arn = aws_iam_policy.local.arn
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.enable_github_oidc && var.create_github_oidc_provider ? 1 : 0
  url            = local.github_oidc_url
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_oidc && !var.create_github_oidc_provider ? 1 : 0
  url   = local.github_oidc_url
}

# Only jobs that run in the "ingest" environment get this role, and that environment only
# deploys from main.
data "aws_iam_policy_document" "ingest_trust" {
  count = local.oidc
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.ingest_subject]
    }
  }
}

data "aws_iam_policy_document" "ingest" {
  count = local.oidc
  statement {
    sid       = "WriteCrimeLogBronze"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.lake.arn}/${local.lake_prefix}/bronze/iu_crime_log/*"]
  }
}

resource "aws_iam_role" "ingest" {
  count              = local.oidc
  name               = "campus-safety-signal-ingest"
  assume_role_policy = data.aws_iam_policy_document.ingest_trust[0].json
}

resource "aws_iam_role_policy" "ingest" {
  count  = local.oidc
  name   = "write-crime-log-bronze"
  role   = aws_iam_role.ingest[0].id
  policy = data.aws_iam_policy_document.ingest[0].json
}
