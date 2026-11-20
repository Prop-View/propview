# GCP infrastructure

This directory contains the existing Phase 2 VM scripts and the Phase 6
Terraform configuration. The Terraform stack is separate from those shell
scripts; it does not edit or invoke them.

## Phase 6 Terraform

Terraform provisions:

- Private-IP Cloud SQL for PostgreSQL 16, an application database, regional
  backups, and point-in-time recovery. Cloud SQL PostgreSQL supports
  `pgvector`; enable it in the application database with `CREATE EXTENSION
  vector;` before applying migrations that depend on it.
- Private Memorystore for Redis 7.2.
- A regional Compute Engine managed instance group running the call-worker
  container. Its autoscaler targets the per-instance Cloud Monitoring gauge
  `custom.googleapis.com/propview/active_calls`.
- An authenticated Cloud Run service for the dashboard.
- A public Admin API Cloud Run service protected by application authentication
  and an internal-only Tool Router Cloud Run service, both connected to private
  Postgres and Redis through Serverless VPC Access.
- Secret Manager secret containers and narrowly scoped access for the worker,
  Admin API, and Tool Router. Cloud Run injects secret values as environment
  variables; the VM startup script reads worker secrets from Secret Manager.
  Terraform never creates secret versions or stores credential values.
- A SIP/RTP ingress firewall rule for UDP 5060 and 10000–20000. Its source
  ranges come only from the required `telephony_provider_cidrs` input; empty
  input and `0.0.0.0/0` are rejected.
- Private Service Access, Cloud NAT for worker egress, required project APIs,
  service accounts, Artifact Registry read access for the worker image, and
  Cloud Monitoring metric-write permission.

### Required inputs

Set these variables in a local `terraform.tfvars` file (do not commit it):

| Variable | Purpose |
|---|---|
| `project_id` | GCP project with billing enabled. |
| `telephony_provider_cidrs` | Non-empty list of the configured provider's published IPv4 SIP/RTP CIDRs. No world-open fallback is allowed. |
| `worker_image` | Call-worker container image pinned with `@sha256:<64-hex-digest>`. |
| `dashboard_image` | Dashboard container image pinned with `@sha256:<64-hex-digest>`. |
| `admin_api_image` | Admin API image pinned with `@sha256:<64-hex-digest>`. |
| `tool_router_image` | Tool Router image pinned with `@sha256:<64-hex-digest>`. |
| `worker_boot_disk_image` | Immutable, versioned Compute Engine image name, not an image family. |

Other inputs are reusable variables in `variables.tf`, including region/network,
subnet, worker command and non-secret environment, secret-name mapping,
autoscaling bounds/target, SQL sizing, Redis sizing, and dashboard limits. The
default network and subnet are both `default`, matching the existing VM
provisioning script. The default worker secret mapping creates empty Secret
Manager containers for the database URL, Gemini key, internal service token,
encryption key, and LiveKit API credentials; override it if the deployment uses
different secret IDs.

### Deployment assumptions and remaining integration

- The project, billing account, configured VPC, and regional subnet already
  exist. The selected VPC must permit Private Service Access and must not
  already contain a conflicting `propview-private-services` range/peering.
- Supply only the actual telephony provider's currently published SIP/RTP
  source ranges. The firewall rule targets `livekit-sip`, the tag used by
  `provision_vm.sh`. If using a non-default VPC, the SIP gateway VM must also
  be attached to that VPC and retain that tag.
- The service container images and VM boot image are deployment inputs because
  this repository does not publish production images. The worker and dashboard
  images must be compatible with the configured commands/port (worker default
  `python worker.py start`; dashboard listens on port 8080). The worker service
  account can pull from Artifact Registry in this project; grant cross-project
  repository access separately if needed.
- Terraform creates Secret Manager secret containers only. Before a service
  starts, add a `latest` version to each secret ID in the worker, Admin API,
  and Tool Router secret maps. The worker reads secrets at boot and Cloud Run
  injects them into its service containers. Configure the database URL secret
  for the Cloud SQL private address and the application database/user. Set
  the service environment maps for non-secret settings. No credentials belong
  in Terraform variables, metadata, or source control.
- The MIG autoscaler reads the Cloud Monitoring `GAUGE` time series
  `custom.googleapis.com/propview/active_calls` for each `gce_instance`.
  `call_session.py` publishes the worker's active-call count when calls start
  and end, and the worker service account has metric-write permission. Confirm
  that the metric is arriving in the target project before relying on
  autoscaling.
- The dashboard Cloud Run URL is reachable but requires Google-authenticated
  invocation. No public `run.invoker` grant, custom domain, load balancer,
  migrations, worker image build, or secret version is provisioned here.
- Cloud SQL and Redis are private-only. Apply database migrations and confirm
  the app uses the `propview_app` database role with tenant context; Terraform
  does not create database credentials or change database contents.
- This directory's original `provision_vm.sh` and `startup-script.sh` remain
  the separate Phase 2 SIP/LiveKit deployment path. In particular, its
  existing firewall behavior is not changed by this Terraform stack.

### Format and validate

From the repository root, initialize the pinned provider and validate the
configuration without selecting a remote backend:

```bash
terraform -chdir=infra/gcp init -backend=false -input=false && terraform -chdir=infra/gcp validate
```

Format with:

```bash
terraform fmt -recursive infra/gcp
```

Neither command applies infrastructure. Review a plan separately before any
deployment; this task does not run `terraform apply` or make cloud changes.

## Existing Phase 2 VM scripts

The existing scripts continue to provision a Compute Engine VM hosting
LiveKit/SIP. They are intentionally unchanged. The `.env.example` and scripts
describe their existing `SIP_SOURCE_RANGES` behavior; use the Terraform
`telephony_provider_cidrs` input for the Phase 6 firewall, and never rely on
the legacy script's empty-range fallback for a deployed SIP gateway.

```bash
gcloud auth login
gcloud config set project <your-project-id>
gcloud services enable compute.googleapis.com

cd infra/gcp
cp .env.example .env
# Fill in GCP_PROJECT_ID and SIP_SOURCE_RANGES before using this legacy path.
set -a; source .env; set +a
./provision_vm.sh
```

### Phase 2 Definition of Done

- [ ] VM running with static IP and firewall rules applied.
- [ ] Docker + LiveKit stack deployed and reachable on that IP.
- [ ] End-to-end: Twilio DID → this VM's SIP port → LiveKit room created.

## Phase 6 Definition of Done

- [ ] Required application images, secret versions, and published telephony
  provider CIDRs supplied by the deployment owner.
- [ ] Worker emits the configured active-call Cloud Monitoring metric.
- [ ] Terraform configuration validated and a reviewed plan deployed by an
  authorized operator.
- [ ] Database migrations, pgvector extension, and private service connectivity
  verified in the target project.
