output "cloud_sql_private_ip" {
  description = "Private IP address of the Cloud SQL PostgreSQL instance."
  value       = google_sql_database_instance.postgres.private_ip_address
}

output "cloud_sql_database" {
  description = "Application database name."
  value       = google_sql_database.application.name
}

output "redis_host" {
  description = "Private IP address of the Memorystore Redis instance."
  value       = google_redis_instance.cache.host
}

output "dashboard_uri" {
  description = "Cloud Run dashboard URL. The service requires Google-authenticated invocation."
  value       = google_cloud_run_v2_service.dashboard.uri
}

output "admin_api_uri" {
  description = "Public Admin API Cloud Run URL; application endpoints enforce account or machine authentication."
  value       = google_cloud_run_v2_service.admin_api.uri
}

output "tool_router_uri" {
  description = "Internal-only Tool Router Cloud Run URL used by the call workers."
  value       = google_cloud_run_v2_service.tool_router.uri
}

output "worker_instance_group" {
  description = "Instance group managed by the active-call metric autoscaler."
  value       = google_compute_region_instance_group_manager.workers.instance_group
}

output "active_call_metric_name" {
  description = "Custom Cloud Monitoring metric workers must publish per VM for autoscaling."
  value       = "custom.googleapis.com/propview/active_calls"
}
