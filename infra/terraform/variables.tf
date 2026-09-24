variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "db_password" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.db_password) >= 12
    error_message = "db_password must contain at least 12 characters."
  }
}

variable "redis_auth_token" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.redis_auth_token) >= 16 && length(var.redis_auth_token) <= 128
    error_message = "redis_auth_token must contain 16 to 128 characters."
  }
}
