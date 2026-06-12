<script lang="ts">
  import { onMount } from "svelte";
  import { apiFetch } from "$lib/api";

  type HistoryItem = {
    version_id: string;
    timestamp: number;
    train_mae: number;
    val_mae: number;
    train_r2: number;
    val_r2: number;
    train_rmse: number;
    val_rmse: number;
    is_active?: boolean;
  };

  let history: HistoryItem[] = [];
  let loading = true;
  let errorMessage = "";
  let rollbackMessage = "";
  let rollingBackId: string | null = null;

  function formatDate(ts: number): string {
    return new Date(ts * 1000).toLocaleString();
  }

  async function loadHistory() {
    loading = true;
    errorMessage = "";
    rollbackMessage = "";
    try {
      const res = await apiFetch("/api/models/history");
      if (!res.ok) {
        const data = await res.json();
        errorMessage = data.detail ?? data.message ?? "Error al cargar el historial de modelos.";
        history = [];
        return;
      }
      history = await res.json();
    } catch (e) {
      errorMessage = "Error de red. ¿El backend está ejecutándose?";
      history = [];
    } finally {
      loading = false;
    }
  }

  async function activateModel(versionId: string) {
    rollingBackId = versionId;
    rollbackMessage = "";
    errorMessage = "";
    try {
      const res = await apiFetch("/api/models/rollback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: versionId }),
      });
      const data = await res.json();
      if (!res.ok) {
        errorMessage = data.detail ?? data.message ?? "Error al activar.";
        return;
      }
      rollbackMessage = data.message;
      await loadHistory();
    } catch (e) {
      errorMessage = "Error de red al activar.";
    } finally {
      rollingBackId = null;
    }
  }

  onMount(loadHistory);
</script>

<section class="page">
  <h1>Historial de Modelos</h1>
  <p>Ver todos los modelos entrenados anteriormente y activar una versión anterior si es necesario.</p>

  {#if loading}
    <p class="info">Cargando historial...</p>
  {:else if errorMessage}
    <div class="error">
      <p>{errorMessage}</p>
      <button on:click={loadHistory}>Reintentar</button>
    </div>
  {:else if history.length === 0}
    <div class="empty">
      <p>No se encontró historial de modelos. Entrena tu primer modelo para comenzar.</p>
    </div>
  {:else}
    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>ID de Versión</th>
            <th>Entrenado el</th>
            <th>MAE Validación</th>
            <th>R² Validación</th>
            <th>RMSE Validación</th>
            <th>Estado</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>
          {#each history as item}
            <tr class:active={item.is_active}>
              <td class="mono">{item.version_id.slice(0, 8)}...</td>
              <td>{formatDate(item.timestamp)}</td>
              <td>{item.val_mae?.toFixed(4) ?? "—"}</td>
              <td>{item.val_r2?.toFixed(4) ?? "—"}</td>
              <td>{item.val_rmse?.toFixed(4) ?? "—"}</td>
              <td>
                {#if item.is_active}
                  <span class="badge active-badge">Activo</span>
                {:else}
                  <span class="badge">Inactivo</span>
                {/if}
              </td>
              <td>
                {#if !item.is_active}
                  <button
                    class="activate-btn"
                    on:click={() => activateModel(item.version_id)}
                    disabled={rollingBackId === item.version_id}
                  >
                    {rollingBackId === item.version_id ? "Activando..." : "Activar"}
                  </button>
                {:else}
                  <span class="muted">—</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if rollbackMessage}
    <div class="success">
      {rollbackMessage}
    </div>
  {/if}
</section>

<style>
  .page {
    padding: 2rem;
  }

  h1 {
    font-size: 2rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
  }

  p {
    color: #666;
    margin-top: 0;
  }

  .info,
  .empty {
    margin-top: 1.5rem;
    padding: 1.2rem;
    border-radius: 12px;
    background: white;
    border: 1px solid #ddd;
  }

  .error {
    margin-top: 1.5rem;
    padding: 1.2rem;
    border-radius: 12px;
    background: #fef2f2;
    border: 1px solid #ef4444;
    color: #b91c1c;
  }

  .error button {
    margin-top: 0.5rem;
  }

  .success {
    margin-top: 1.5rem;
    padding: 1.2rem;
    border-radius: 12px;
    background: #ecfdf5;
    border: 1px solid #10b981;
    color: #065f46;
  }

  .table-card {
    margin-top: 1.5rem;
    padding: 1.2rem;
    border-radius: 12px;
    background: white;
    border: 1px solid #ddd;
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th,
  td {
    padding: 0.8rem;
    border-bottom: 1px solid #eee;
    text-align: left;
    font-size: 0.9rem;
  }

  th {
    background: #f7f7f7;
    font-weight: 600;
  }

  tr.active {
    background: #eff6ff;
  }

  .mono {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
  }

  .badge {
    display: inline-block;
    padding: 0.25rem 0.5rem;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    background: #e5e7eb;
    color: #374151;
  }

  .active-badge {
    background: #dbeafe;
    color: #1e40af;
  }

  .activate-btn {
    padding: 0.4rem 0.8rem;
    border: none;
    border-radius: 6px;
    background: #111827;
    color: white;
    font-weight: 600;
    cursor: pointer;
    font-size: 0.8rem;
  }

  .activate-btn:hover {
    background: #374151;
  }

  .activate-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .muted {
    color: #9ca3af;
  }

  button {
    padding: 0.6rem 1rem;
    border: none;
    border-radius: 8px;
    background: #111827;
    color: white;
    font-weight: 600;
    cursor: pointer;
  }
</style>
