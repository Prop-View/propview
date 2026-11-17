variable "project_id" {
  description = "GCP project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Region for Cloud SQL, Memorystore, Cloud Run, and the worker MIG."
  type        = string
  default     = "us-central1"
}

variable "network_name" {
  description = "Existing VPC network used by the services and the SIP firewall rule."
  type        = string
  default     = "default"
}

variable "subnetwork_name" {
  description = "Existing regional subnet for the private call-worker instances."
  type        = string
  default     = "default"
}

variable "telephony_provider_cidrs" {
  description = "Required IPv4 CIDRs published by the configured telephony provider for SIP/RTP ingress. Never use 0.0.0.0/0."
  type        = list(string)

  validation {
    condition = length(var.telephony_provider_cidrs) > 0 && alltrue([
      for cidr in var.telephony_provider_cidrs :
      can(cidrhost(cidr, 0)) && !strcontains(cidr, ":") && cidr != "0.0.0.0/0"
    ])
    error_message = "Provide one or more valid IPv4 telephony-provider CIDRs; 0.0.0.0/0 and IPv6 ranges are not allowed."
  }
}

variable "sip_network_tag" {
  description = "Network tag applied to the SIP gateway VM. The existing provision_vm.sh script uses livekit-sip."
  type        = string
  default     = "livekit-sip"
}

variable "worker_image" {
  description = "Call-worker container image, referenced by immutable sha256 digest."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be pinned to an immutable sha256 digest."
  }
}

variable "dashboard_image" {
  description = "Dashboard container image, referenced by immutable sha256 digest."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@sha256:[0-9a-f]{64}$", var.dashboard_image))
    error_message = "dashboard_image must be pinned to an immutable sha256 digest."
  }
}

variable "worker_boot_disk_image" {
  description = "Fully qualified, versioned Compute Engine image (not an image family) for call-worker VMs."
  type        = string

  validation {
    condition     = can(regex("^projects/[^/]+/global/images/[^/]+$", var.worker_boot_disk_image))
    error_message = "worker_boot_disk_image must identify a specific image, for example projects/ubuntu-os-cloud/global/images/ubuntu-2204-jammy-v20240415."
  }
}

variable "worker_command" {
  description = "Command and arguments passed to the call-worker image."
  type        = list(string)
  default     = ["python", "worker_entrypoint.py", "start"]

  validation {
    condition     = length(var.worker_command) > 0
    error_message = "worker_command must contain at least one command."
  }
}

variable "worker_environment" {
  description = "Non-secret environment values passed to the call-worker container. Put credentials in Secret Manager instead."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for env_name in keys(var.worker_environment) :
      can(regex("^[A-Z_][A-Z0-9_]*$", env_name))
    ])
    error_message = "worker_environment keys must be valid uppercase environment variable names."
  }
}

variable "worker_secret_ids" {
  description = "Environment-variable name to Secret Manager secret ID mapping. Terraform creates secret containers only, never secret versions or credential values."
  type        = map(string)
  default = {
    DATABASE_URL           = "database-url"
    ENCRYPTION_KEY         = "encryption-key"
    GEMINI_API_KEY         = "gemini-api-key"
    INTERNAL_SERVICE_TOKEN = "internal-service-token"
    LIVEKIT_API_KEY        = "livekit-api-key"
    LIVEKIT_API_SECRET     = "livekit-api-secret"
    REDIS_URL              = "redis-url"
  }

  validation {
    condition = length(var.worker_secret_ids) > 0 && alltrue([
      for env_name, secret_id in var.worker_secret_ids :
      can(regex("^[A-Z_][A-Z0-9_]*$", env_name)) &&
      can(regex("^[A-Za-z0-9_-]+$", secret_id))
    ])
    error_message = "worker_secret_ids must map valid environment variable names to Secret Manager IDs containing only letters, digits, underscores, and hyphens."
  }
}

variable "admin_api_image" {
  description = "Admin API container image pinned to an immutable sha256 digest."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@sha256:[0-9a-f]{64}$", var.admin_api_image))
    error_message = "admin_api_image must be pinned to an immutable sha256 digest."
  }
}

variable "admin_api_service_name" {
  description = "Cloud Run service name for the tenant Admin API."
  type        = string
  default     = "propview-admin-api"
}

variable "admin_api_max_instances" {
  description = "Maximum Cloud Run instances for the Admin API."
  type        = number
  default     = 10
}

variable "admin_api_environment" {
  description = "Non-secret environment values for the Admin API."
  type        = map(string)
  default     = {}
}

variable "admin_api_secret_ids" {
  description = "Environment-variable names mapped to Secret Manager secret IDs for the Admin API."
  type        = map(string)
  default = {
    DATABASE_URL            = "database-url"
    ENCRYPTION_KEY          = "encryption-key"
    INTERNAL_SERVICE_TOKEN  = "internal-service-token"
    PLATFORM_OPERATOR_TOKEN = "platform-operator-token"
    REDIS_URL               = "redis-url"
  }
}

variable "tool_router_image" {
  description = "Tool Router container image pinned to an immutable sha256 digest."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@sha256:[0-9a-f]{64}$", var.tool_router_image))
    error_message = "tool_router_image must be pinned to an immutable sha256 digest."
  }
}

variable "tool_router_service_name" {
  description = "Cloud Run service name for the Tool Router."
  type        = string
  default     = "propview-tool-router"
}

variable "tool_router_max_instances" {
  description = "Maximum Cloud Run instances for the Tool Router."
  type        = number
  default     = 20
}

variable "tool_router_environment" {
  description = "Non-secret environment values for the Tool Router."
  type        = map(string)
  default     = {}
}

variable "tool_router_secret_ids" {
  description = "Environment-variable names mapped to Secret Manager secret IDs for the Tool Router."
  type        = map(string)
  default = {
    DATABASE_URL           = "database-url"
    ENCRYPTION_KEY         = "encryption-key"
    INTERNAL_SERVICE_TOKEN = "internal-service-token"
    REDIS_URL              = "redis-url"
  }
}

variable "serverless_connector_cidr" {
  description = "Unused /28 range reserved for the Serverless VPC Access connector."
  type        = string
  default     = "10.8.0.0/28"

  validation {
    condition     = can(cidrhost(var.serverless_connector_cidr, 0)) && can(regex("/28$", var.serverless_connector_cidr))
    error_message = "serverless_connector_cidr must be a valid IPv4 /28 CIDR that does not overlap existing subnet ranges."
  }
}

variable "worker_machine_type" {
  description = "Compute Engine machine type for each call-worker instance."
  type        = string
  default     = "e2-standard-2"
}

variable "worker_min_replicas" {
  description = "Minimum number of call-worker instances."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_min_replicas >= 0
    error_message = "worker_min_replicas must be zero or greater."
  }
}

variable "worker_max_replicas" {
  description = "Maximum number of call-worker instances."
  type        = number
  default     = 10

  validation {
    condition     = var.worker_max_replicas >= 1
    error_message = "worker_max_replicas must be at least one."
  }
}

variable "active_calls_per_worker" {
  description = "Target custom active-call metric value per worker instance for the MIG autoscaler."
  type        = number
  default     = 5

  validation {
    condition     = var.active_calls_per_worker > 0
    error_message = "active_calls_per_worker must be greater than zero."
  }
}

variable "sql_instance_name" {
  description = "Cloud SQL PostgreSQL instance name."
  type        = string
  default     = "propview-postgres"
}

variable "sql_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-custom-2-7680"
}

variable "sql_deletion_protection" {
  description = "Protect the Cloud SQL instance from Terraform deletion."
  type        = bool
  default     = true
}

variable "redis_instance_name" {
  description = "Memorystore for Redis instance name."
  type        = string
  default     = "propview-redis"
}

variable "redis_memory_size_gb" {
  description = "Memorystore Redis memory in GiB."
  type        = number
  default     = 1

  validation {
    condition     = var.redis_memory_size_gb >= 1
    error_message = "redis_memory_size_gb must be at least 1."
  }
}

variable "dashboard_service_name" {
  description = "Cloud Run service name for the authenticated dashboard container."
  type        = string
  default     = "propview-dashboard"
}

variable "dashboard_max_instances" {
  description = "Maximum Cloud Run dashboard instances."
  type        = number
  default     = 3

  validation {
    condition     = var.dashboard_max_instances >= 1
    error_message = "dashboard_max_instances must be at least one."
  }
}
