# A2A demo on Kyma

This is an intentionally public demo deployment. The Kyma APIRule exposes only
the Frontend service; Nginx serves the SPA and proxies same-origin /api requests
to the internal Gateway Service with SSE buffering disabled.

Gateway and Team Server run as two containers in one single-replica Pod. The Team
Server is only reachable through 127.0.0.1:8091. The shared RWO PVC persists
Harness Studio revisions and evaluation reports; do not scale this Backend
Deployment above one replica while it uses SQLite.

## Prerequisites

- Kyma API Gateway and a default dynamic StorageClass.
- kubectl (with built-in Kustomize, or standalone kustomize), envsubst,
  Docker-compatible build/push access, and a target namespace.
- AI Core and Grounding credentials. They are supplied only through runtime.env.

## Build and publish images

Run from repository root with immutable target-registry tags:

~~~bash
docker build -t <registry>/a2a-demo-backend:<tag> demo/backend
docker build -t <registry>/a2a-demo-frontend:<tag> demo/frontend
docker push <registry>/a2a-demo-backend:<tag>
docker push <registry>/a2a-demo-frontend:<tag>
~~~

For a private registry, create an image-pull Secret and add it to every
Deployment before applying the manifests.

## Configure and deploy

~~~bash
cd demo/deploy/kyma/overlays/production
cp deployment.env.example deployment.env
cp runtime.env.example runtime.env
# Fill every required value; do not commit either file.

kubectl -n <kyma-namespace> create secret generic a2a-demo-runtime-secret \
  --from-env-file=runtime.env \
  --dry-run=client -o yaml | kubectl apply -f -

export NAMESPACE=<kyma-namespace>
export BACKEND_IMAGE=<registry>/a2a-demo-backend:<immutable-tag>
export FRONTEND_IMAGE=<registry>/a2a-demo-frontend:<immutable-tag>
bash deploy.sh
~~~

deployment.env holds public routing values. Create the runtime Kubernetes Secret
from your protected AI Core environment file before running the script. The
namespace must exist before running the script.

## Verify

~~~bash
kubectl -n "$NAMESPACE" get deploy,pod,svc,pvc,apirule
kubectl -n "$NAMESPACE" logs deployment/a2a-demo-backend -c gateway --tail=100
kubectl -n "$NAMESPACE" logs deployment/a2a-demo-backend -c team-server --tail=100
~~~

Open https://<PUBLIC_HOST> and verify the SPA, an SSE Agent request, and a Harness Studio save.
Restart the Backend Pod and confirm the Harness revision and evaluation report
remain. Do not create another APIRule for Gateway, Team Server, or Frontend.
