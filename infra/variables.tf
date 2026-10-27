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
