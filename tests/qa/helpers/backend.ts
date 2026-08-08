import { execSync } from 'node:child_process';

/**
 * Backend glue — run a one-liner in the live api pod's Django shell.
 *
 * The stack moved from docker-compose (`docker exec auto_sec-web-1 …`) to
 * local Kubernetes (namespace `autosec`), so all backend fixture provisioning
 * goes through kubectl now. Override the target via:
 *
 *   QA_KUBE_NS      k8s namespace          default autosec
 *   QA_KUBE_TARGET  kubectl exec target    default deploy/api
 */
const NS = process.env.QA_KUBE_NS || 'autosec';
const TARGET = process.env.QA_KUBE_TARGET || 'deploy/api';

export const sh = (py: string): string =>
  execSync(
    `kubectl -n ${NS} exec ${TARGET} -- python manage.py shell -c "${py}"`,
    { maxBuffer: 10 * 1024 * 1024 }
  ).toString();
