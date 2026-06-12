/**
 * Build a full API URL from a path.
 * When VITE_API_BASE_URL is set at build time (e.g. on Render) the backend
 * origin is prepended. When it is empty (e.g. local nginx proxy) the path
 * is left relative.
 */
export function apiUrl(path: string): string {
	const base = import.meta.env.VITE_API_BASE_URL || '';
	// Avoid double slashes when base is empty.
	return base ? `${base.replace(/\/$/, '')}${path}` : path;
}

/**
 * Wrapper around fetch that always includes credentials.
 * This is required for cross-origin cookie-based authentication on Render.
 */
export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
	return fetch(apiUrl(path), {
		...init,
		credentials: 'include'
	});
}
