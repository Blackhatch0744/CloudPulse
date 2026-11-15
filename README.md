# CloudPulse

A Flask dashboard for monitoring cloud resource usage and cost. It tracks EC2, RDS, S3,
ElastiCache and EKS resources, estimates daily cost, compares spend to a monthly budget,
raises alerts and suggests savings. Data lives in SQLite. The first run seeds sample
resources and 90 days of history.

The repo also holds the full DevOps pipeline: Jenkins CI, a Docker image, a Kubernetes
deployment and an Ansible role.

## Run locally

Needs Python 3.10+.

```bash
python -m venv .venv
.venv/bin/pip install -e .[dev]    # Windows: .venv\Scripts\pip
cloudpulse
```

Open http://localhost:5000.

| Env var         | Default         | Purpose              |
|-----------------|-----------------|----------------------|
| `PORT`          | `5000`          | Port to listen on    |
| `CLOUDPULSE_DB` | `cloudpulse.db` | SQLite database path |

## Pages

| Path            | Shows                                                |
|-----------------|------------------------------------------------------|
| `/`             | Overview                                             |
| `/resources`    | Resource list with an add form; `/resources/<id>` for detail |
| `/costs`        | Daily cost history                                   |
| `/budget`       | Monthly budget and spend; set the budget             |
| `/optimization` | Underused resources and savings                      |
| `/alerts`       | CPU, memory, storage and budget alerts               |
| `/reports`      | Cost reports                                         |

## JSON API

| Method | Path                    | Notes                                                       |
|--------|-------------------------|-------------------------------------------------------------|
| GET    | `/health`               | `{"status": "ok"}` (used by the Kubernetes probes)          |
| GET    | `/api/overview`         |                                                             |
| GET    | `/api/resources`        |                                                             |
| POST   | `/api/resources`        | Body: `name`, `type`, `region`, `status`, `storage_gb`      |
| GET    | `/api/resources/<id>`   |                                                             |
| GET    | `/api/costs`            |                                                             |
| GET    | `/api/budget`           |                                                             |
| PUT    | `/api/budget`           | Body: `{"amount": 750}`                                     |
| GET    | `/api/optimization`     |                                                             |
| GET    | `/api/alerts`           |                                                             |
| GET    | `/api/reports`          |                                                             |

`type` is a key of `HOURLY` in `cloudpulse/pricing.py`, such as `t3.micro`, `db.m5.large`,
`s3-standard` or `eks-cluster`. `status` is one of `active`, `inactive`, `failed`.

## Test and build

```bash
pytest
python -m build --wheel    # writes dist/cloudpulse-1.0.0-py3-none-any.whl
```

## Pipeline

1. **Jenkins** (`Jenkinsfile`): polls the repo every minute, then sets up a venv, runs
   `pytest` (JUnit report), builds the wheel and archives it. It runs on Linux and Windows agents.
2. **Docker** (`Dockerfile`): installs the built wheel into `python:3.12-slim`.
   ```bash
   docker build -t cloudpulse:1.0.0 .
   ```
3. **Kubernetes** (`k8s/`): 3 replicas with readiness and liveness probes on `/health`,
   exposed by a NodePort service on port `30080`. The image is never pulled
   (`imagePullPolicy: Never`), so load it into minikube first.
   ```bash
   minikube image load cloudpulse:1.0.0
   kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
   kubectl get pods
   minikube service cloudpulse --url
   ```
4. **Ansible** (`ansible/`): installs the wheel as a systemd service on port 8080.
   `-K` prompts for your sudo password.
   ```bash
   cd ansible
   ansible-playbook -i inventory playbook.yml -K
   ```

Steps 2–4 were run on an Ubuntu VM.

## Layout

```
cloudpulse/   Flask app: routes, analytics, pricing, SQLite db, templates
tests/        pytest suite
k8s/          Deployment and Service
ansible/      Playbook, inventory and cloudpulse role
```
