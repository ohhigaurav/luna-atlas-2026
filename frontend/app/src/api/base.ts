// Where the backend lives. Empty (local dev, run_local.sh, the Docker image serving the app) means
// the same origin; the hosted app on Cloudflare Pages sets VITE_API_BASE to the VM's https address
// (an internal document (not published)). Static-answer keys keep using the bare /api/... path.
export const API = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '');
