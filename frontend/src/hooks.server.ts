import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  const pathname = event.url.pathname;
  const authCookie = event.cookies.get('auth_session');

  const isProtectedRoute = pathname === '/' || pathname.startsWith('/dashboard');

  // If the user is not authenticated and tries to access a protected page,
  // redirect them to the login screen.
  if (isProtectedRoute && !authCookie) {
    return new Response(null, {
      status: 302,
      headers: { location: '/login' }
    });
  }

  // If the user is already authenticated, there is no reason to show the
  // login page again.
  if (pathname === '/login' && authCookie) {
    return new Response(null, {
      status: 302,
      headers: { location: '/dashboard/predictions' }
    });
  }

  return resolve(event);
};
