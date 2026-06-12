import type { Handle } from '@sveltejs/kit';

// Auth is verified client-side because the auth cookie is set by the backend
// service (a different origin on Render), so it is never sent to this frontend
// service during server-side rendering.
export const handle: Handle = async ({ event, resolve }) => {
  return resolve(event);
};
