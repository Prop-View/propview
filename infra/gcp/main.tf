locals {
  managed_secret_ids = toset(concat(
    values(var.worker_secret_ids),
    values(var.admin_api_secret_ids),
    values(var.tool_router_secret_ids),
  ))
  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

data "google_compute_network" "selected" {
  name    = var.network_name
  project = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "admin_api" {
  name                = var.admin_api_service_name
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  template {
    service_account = google_service_account.admin_api.email

    scaling {
      max_instance_count = var.admin_api_max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.services.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.admin_api_image

      ports {
        container_port = 8001
      }

      dynamic "env" {
        for_each = var.admin_api_secret_ids
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.worker[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = merge(var.admin_api_environment, {
          CORS_ORIGINS = google_cloud_run_v2_service.dashboard.uri
        })
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.admin_api,
    google_vpc_access_connector.services,
  ]
}

resource "google_cloud_run_v2_service" "tool_router" {
  name                = var.tool_router_service_name
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = true

  template {
    service_account = google_service_account.tool_router.email

    scaling {
      max_instance_count = var.tool_router_max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.services.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.tool_router_image

      ports {
        container_port = 8000
      }

      dynamic "env" {
        for_each = var.tool_router_secret_ids
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.worker[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.tool_router_environment
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.tool_router,
    google_vpc_access_connector.services,
  ]
}

data "google_compute_subnetwork" "workers" {
  name    = var.subnetwork_name
  project = var.project_id
  region  = var.region

  depends_on = [google_project_service.required]
}

resource "google_compute_global_address" "private_services" {
  name          = "propview-private-services"
  project       = var.project_id
  address_type  = "INTERNAL"
  purpose       = "VPC_PEERING"
  prefix_length = 16
  network       = data.google_compute_network.selected.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = data.google_compute_network.selected.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [google_project_service.required]
}

resource "google_compute_firewall" "sip_ingress" {
  name      = "propview-sip-ingress"
  project   = var.project_id
  network   = data.google_compute_network.selected.name
  direction = "INGRESS"
  priority  = 1000

  source_ranges = var.telephony_provider_cidrs
  target_tags   = [var.sip_network_tag]

  allow {
    protocol = "udp"
    ports    = ["5060", "10000-20000"]
  }

  description = "SIP signaling and RTP, restricted to configured telephony-provider CIDRs."
}

resource "google_compute_router" "workers" {
  name    = "propview-workers-router"
  project = var.project_id
  region  = var.region
  network = data.google_compute_network.selected.id
}

resource "google_compute_router_nat" "workers" {
  name                               = "propview-workers-nat"
  project                            = var.project_id
  router                             = google_compute_router.workers.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = data.google_compute_subnetwork.workers.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_sql_database_instance" "postgres" {
  name                = var.sql_instance_name
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.sql_deletion_protection

  settings {
    tier              = var.sql_tier
    availability_type = "REGIONAL"
    disk_type         = "PD_SSD"
    disk_size         = 20
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = data.google_compute_network.selected.id
    }
  }

  depends_on = [
    google_project_service.required,
    google_service_networking_connection.private_services,
  ]
}

resource "google_sql_database" "application" {
  name     = "propview"
  project  = var.project_id
  instance = google_sql_database_instance.postgres.name
}

resource "google_redis_instance" "cache" {
  name               = var.redis_instance_name
  project            = var.project_id
  region             = var.region
  tier               = "BASIC"
  memory_size_gb     = var.redis_memory_size_gb
  redis_version      = "REDIS_7_2"
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  authorized_network = data.google_compute_network.selected.id

  depends_on = [
    google_project_service.required,
    google_service_networking_connection.private_services,
  ]
}

resource "google_service_account" "workers" {
  project      = var.project_id
  account_id   = "propview-call-workers"
  display_name = "Propview call worker instances"
}

resource "google_project_iam_member" "worker_monitoring" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.workers.email}"
}

resource "google_project_iam_member" "worker_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.workers.email}"
}

resource "google_secret_manager_secret" "worker" {
  for_each = local.managed_secret_ids

  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "worker" {
  for_each = toset(values(var.worker_secret_ids))

  project   = var.project_id
  secret_id = google_secret_manager_secret.worker[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workers.email}"
}

resource "google_compute_instance_template" "workers" {
  name_prefix  = "propview-call-worker-"
  project      = var.project_id
  machine_type = var.worker_machine_type
  tags         = ["propview-call-worker"]

  disk {
    source_image = var.worker_boot_disk_image
    auto_delete  = true
    boot         = true
    disk_size_gb = 30
    disk_type    = "pd-balanced"
  }

  network_interface {
    network    = data.google_compute_network.selected.id
    subnetwork = data.google_compute_subnetwork.workers.id
  }

  service_account {
    email  = google_service_account.workers.email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = templatefile("${path.module}/worker-startup-script.tftpl", {
    project_id        = var.project_id
    worker_image      = var.worker_image
    worker_secret_ids = var.worker_secret_ids
    worker_environment = merge(var.worker_environment, {
      TOOL_ROUTER_URL = google_cloud_run_v2_service.tool_router.uri
    })
    worker_command = var.worker_command
  })

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    google_secret_manager_secret_iam_member.worker,
    google_project_iam_member.worker_monitoring,
    google_project_iam_member.worker_artifact_reader,
  ]
}

resource "google_compute_region_instance_group_manager" "workers" {
  name               = "propview-call-workers"
  project            = var.project_id
  region             = var.region
  base_instance_name = "propview-call-worker"

  version {
    instance_template = google_compute_instance_template.workers.id
  }

  depends_on = [google_compute_router_nat.workers]
}

resource "google_monitoring_metric_descriptor" "active_calls" {
  project      = var.project_id
  type         = "custom.googleapis.com/propview/active_calls"
  metric_kind  = "GAUGE"
  value_type   = "INT64"
  unit         = "1"
  display_name = "Propview active calls per worker"
  description  = "Current active call sessions on each Propview worker VM."

  depends_on = [google_project_service.required]
}

resource "google_compute_region_autoscaler" "workers" {
  name    = "propview-call-workers"
  project = var.project_id
  region  = var.region
  target  = google_compute_region_instance_group_manager.workers.id

  autoscaling_policy {
    min_replicas    = var.worker_min_replicas
    max_replicas    = var.worker_max_replicas
    cooldown_period = 120

    metric {
      name   = "custom.googleapis.com/propview/active_calls"
      filter = "resource.type = \"gce_instance\""
      target = var.active_calls_per_worker
      type   = "GAUGE"
    }
  }

  depends_on = [google_monitoring_metric_descriptor.active_calls]
}

resource "google_service_account" "dashboard" {
  project      = var.project_id
  account_id   = "propview-dashboard"
  display_name = "Propview dashboard Cloud Run service"
}

resource "google_service_account" "admin_api" {
  project      = var.project_id
  account_id   = "propview-admin-api"
  display_name = "Propview Admin API Cloud Run service"
}

resource "google_service_account" "tool_router" {
  project      = var.project_id
  account_id   = "propview-tool-router"
  display_name = "Propview Tool Router Cloud Run service"
}

resource "google_vpc_access_connector" "services" {
  name          = "propview-services"
  project       = var.project_id
  region        = var.region
  network       = data.google_compute_network.selected.name
  ip_cidr_range = var.serverless_connector_cidr
  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "admin_api" {
  for_each = toset(values(var.admin_api_secret_ids))

  project   = var.project_id
  secret_id = google_secret_manager_secret.worker[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.admin_api.email}"
}

resource "google_secret_manager_secret_iam_member" "tool_router" {
  for_each = toset(values(var.tool_router_secret_ids))

  project   = var.project_id
  secret_id = google_secret_manager_secret.worker[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.tool_router.email}"
}

resource "google_cloud_run_v2_service_iam_member" "admin_api_public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.admin_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "tool_router_internal_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.tool_router.name
  role     = "roles/run.invoker"
  # Cloud Run's internal ingress restriction is the network boundary. The
  # service still enforces INTERNAL_SERVICE_TOKEN at the application layer.
  member = "allUsers"
}

resource "google_cloud_run_v2_service" "dashboard" {
  name                = var.dashboard_service_name
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  template {
    service_account = google_service_account.dashboard.email

    scaling {
      max_instance_count = var.dashboard_max_instances
    }

    containers {
      image = var.dashboard_image

      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [google_project_service.required]
}
