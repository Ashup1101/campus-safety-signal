variable "github_owner" {
  type    = string
  default = "Ashup1101"
}

variable "github_repository" {
  type    = string
  default = "campus-safety-signal"
}

variable "create_github_oidc_provider" {
  description = "An account holds one GitHub OIDC provider; set false if it already exists."
  type        = bool
  default     = true
}

# The GitHub Actions ingest needs AWS's GitHub OIDC provider. This account's organization denies
# iam:CreateOpenIDConnectProvider, so the daily capture runs in AWS instead (daily_ingest.tf).
variable "enable_github_oidc" {
  type    = bool
  default = false
}
