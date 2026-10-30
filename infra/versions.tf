terraform {
  required_version = "~> 1.16.5"

  # State stays local and gitignored (infra/terraform.tfstate).
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.68.0"
    }
    github = {
      source  = "integrations/github"
      version = "6.13.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.8.1"
    }
  }
}

# Region and profile come from AWS_REGION / AWS_PROFILE (make infra-plan reads them from .env).
provider "aws" {
  default_tags {
    tags = {
      project = "campus-safety-signal"
    }
  }
}

# Token comes from GITHUB_TOKEN (make infra-plan uses `gh auth token`).
provider "github" {
  owner = var.github_owner
}
