# PROP-102 infra: GCP VM for LiveKit + SIP Gateway

Provisions the Compute Engine VM that hosts `livekit-server` and
`livekit-sip` (see `../livekit/`), with a static IP and the firewall rules
they need.

## Setup

```bash
# Install the gcloud SDK if you don't have it, then:
gcloud auth login
gcloud config set project <your-project-id>
gcloud services enable compute.googleapis.com

cd infra/gcp
cp .env.example .env
# fill in GCP_PROJECT_ID at minimum
set -a; source .env; set +a
./provision_vm.sh
```

The script reserves a static external IP, opens the ports LiveKit/SIP need
(`7880-7881/tcp`, `50000-60000/udp` for RTC, `5060/udp` + `10000-20000/udp`
for SIP), and boots an Ubuntu VM with Docker pre-installed via
`startup-script.sh`.

## Deploying LiveKit onto the VM

```bash
gcloud compute scp --recurse ../livekit <vm-name>:~/livekit --zone <zone>
gcloud compute ssh <vm-name> --zone <zone>
# on the VM:
cd ~/livekit
cp livekit.yaml.example livekit.yaml       # fill in api key/secret
cp sip-config.yaml.example sip-config.yaml # same key/secret
docker compose up -d
```

Then run `../livekit/setup_sip_routing.sh` (from your laptop, pointed at
`LIVEKIT_URL=ws://<static-ip>:7880`) to wire the Twilio DID to a room, and
update PROP-101's `LIVEKIT_SIP_ORIGINATION_URI` to `sip:<static-ip>:5060`.

## Definition of Done

- [ ] VM running with static IP, firewall rules applied.
- [ ] Docker + LiveKit stack deployed and reachable on that IP.
- [ ] End-to-end: Twilio DID → this VM's SIP port → LiveKit room created.

## Cost note

`e2-medium` + a static IP run continuously will incur ongoing GCP charges.
Tear down with `gcloud compute instances delete <vm-name>` and
`gcloud compute addresses delete <vm-name>-ip` when not needed.
