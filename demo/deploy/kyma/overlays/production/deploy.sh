#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
namespace="${NAMESPACE:?Set NAMESPACE to the Kyma namespace}"
: "${BACKEND_IMAGE:?Set BACKEND_IMAGE to the pushed backend image reference}"
: "${FRONTEND_IMAGE:?Set FRONTEND_IMAGE to the pushed frontend image reference}"

if [[ ! -f "$script_dir/deployment.env" ]]; then
  echo "Missing $script_dir/deployment.env. Copy its .example file and fill in the deployment values." >&2
  exit 1
fi

command -v kubectl >/dev/null || { echo "kubectl is required." >&2; exit 1; }
command -v envsubst >/dev/null || { echo "envsubst is required (gettext package)." >&2; exit 1; }

if command -v kustomize >/dev/null; then
  render=(kustomize build .)
else
  render=(kubectl kustomize .)
fi

kubectl get namespace "$namespace" >/dev/null
kubectl --namespace "$namespace" get secret a2a-demo-runtime-secret >/dev/null || {
  echo "Missing a2a-demo-runtime-secret. Create it from runtime.env before deploying." >&2
  exit 1
}
(
  cd "$script_dir"
  "${render[@]}" | envsubst '$BACKEND_IMAGE $FRONTEND_IMAGE' | kubectl apply --namespace "$namespace" -f -
)
kubectl rollout status --namespace "$namespace" deployment/a2a-demo-backend
kubectl rollout status --namespace "$namespace" deployment/a2a-demo-frontend
