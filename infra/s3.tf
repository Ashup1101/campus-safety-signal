data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  bucket      = "campus-safety-signal-lake-${data.aws_caller_identity.current.account_id}"
  lake_prefix = "lake"
  bronze_arn  = "${aws_s3_bucket.lake.arn}/${local.lake_prefix}/bronze/*"
}

resource "aws_s3_bucket" "lake" {
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs off
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Bronze never gets a noncurrent-version rule: nothing there may expire.
resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket     = aws_s3_bucket.lake.id
  depends_on = [aws_s3_bucket_versioning.lake]

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = ["silver", "gold"]
    content {
      id     = "expire-noncurrent-${rule.value}"
      status = "Enabled"
      filter {
        prefix = "${local.lake_prefix}/${rule.value}/"
      }
      noncurrent_version_expiration {
        noncurrent_days = 30
      }
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyBronzeDeletes"
    effect    = "Deny"
    actions   = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = [local.bronze_arn]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  # Bronze writes must send If-None-Match: * so an existing key can never be replaced.
  # s3:ObjectCreationOperation is true only for PutObject and CompleteMultipartUpload, which
  # keeps the multipart part uploads (no conditional headers) working.
  statement {
    sid       = "DenyBronzeUnconditionalWrites"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = [local.bronze_arn]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["true"]
    }
    condition {
      test     = "Bool"
      variable = "s3:ObjectCreationOperation"
      values   = ["true"]
    }
  }
}

resource "aws_s3_bucket_policy" "lake" {
  bucket     = aws_s3_bucket.lake.id
  policy     = data.aws_iam_policy_document.bucket.json
  depends_on = [aws_s3_bucket_public_access_block.lake]
}
