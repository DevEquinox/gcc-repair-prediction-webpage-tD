<script lang="ts">
  import { page } from "$app/stores";

  const nav = [
    { label: "Predicciones", href: "/dashboard/predictions" },
    { label: "Entrenar Modelo", href: "/dashboard/train-model" },
    { label: "Historial de Modelos", href: "/dashboard/model-history" },
  ];

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
  }
</script>

<div class="shell">
  <aside class="sidebar">
    <h2>Panel GCC</h2>
    <nav>
      {#each nav as item}
        <a
          href={item.href}
          class:active={$page.url.pathname === item.href}
        >
          {item.label}
        </a>
      {/each}
    </nav>

    <button class="logout" on:click={logout}>Cerrar sesión</button>
  </aside>

  <main class="content">
    <slot />
  </main>
</div>

<style>
  .shell {
    display: flex;
    min-height: 100vh;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  }

  .sidebar {
    width: 220px;
    background: #111827;
    color: white;
    padding: 1.5rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .sidebar h2 {
    font-size: 1.25rem;
    margin: 0;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #374151;
  }

  nav {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  nav a {
    color: #d1d5db;
    text-decoration: none;
    padding: 0.6rem 0.8rem;
    border-radius: 8px;
    font-weight: 500;
    transition: background 0.15s;
  }

  nav a:hover {
    background: #1f2937;
  }

  nav a.active {
    background: #2563eb;
    color: white;
  }

  .logout {
    margin-top: auto;
    padding: 0.6rem 0.8rem;
    border: 1px solid #374151;
    border-radius: 8px;
    background: transparent;
    color: #d1d5db;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
  }

  .logout:hover {
    background: #1f2937;
    color: white;
  }

  .content {
    flex: 1;
    background: #f3f4f6;
    overflow-y: auto;
  }
</style>
