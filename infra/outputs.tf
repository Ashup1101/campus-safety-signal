output "lake_uri" {
  value = "s3://${aws_s3_bucket.lake.bucket}/${local.lake_prefix}"
}

output "local_role_arn" {
  value = aws_iam_role.local.arn
}

output "ingest_role_arn" {
  value = aws_iam_role.ingest.arn
}
