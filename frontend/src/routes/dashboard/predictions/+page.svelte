<script lang="ts">
  import { onMount } from "svelte";

  type PredictionRow = {
    plant: string;
    material: string;
    spare_part_name: string;
    estimated_quantity: number;
  };

  type CurrentModel = {
    version_id: string;
    timestamp: number;
    train_mae: number;
    val_mae: number;
    train_r2: number;
    val_r2: number;
    train_rmse: number;
    val_rmse: number;
  };

  let rows: PredictionRow[] = [];
  let loading = true;
  let errorMessage = "";
  let noModel = false;

  let currentModel: CurrentModel | null = null;
  let modelLoading = true;

  let selectedPlant = "TODAS";
  let search = "";

  function formatDate(ts: number): string {
    return new Date(ts * 1000).toLocaleString();
  }

  onMount(async () => {
    // Load predictions
    try {
      const response = await fetch("/api/predictions");
      if (!response.ok) {
        const data = await response.json();
        const detail = data.detail ?? "";
        if (detail.toLowerCase().includes("no hay modelo") || detail.toLowerCase().includes("no active model")) {
          noModel = true;
        } else {
          errorMessage = detail || "Error al cargar predicciones.";
        }
        loading = false;
        modelLoading = false;
        return;
      }
      const data = await response.json();
      rows = data.map((item: any) => ({
        plant: item.plant,
        material: String(item.material),
        spare_part_name: item.spare_part_name,
        estimated_quantity: item.predicted_quantity ?? 0
      }));
    } catch (err) {
      errorMessage = "Error de red. ¿El backend está ejecutándose?";
      loading = false;
      modelLoading = false;
      return;
    } finally {
      loading = false;
    }

    // Load current model metadata
    try {
      const res = await fetch("/api/models/current");
      if (res.ok) {
        currentModel = await res.json();
      }
    } catch (err) {
      // Best-effort; predictions already loaded.
    } finally {
      modelLoading = false;
    }
  });

  $: plants = ["TODAS", ...Array.from(new Set(rows.map((row) => row.plant))).sort()];

  $: filteredRows = rows.filter((row) => {
    const matchesPlant = selectedPlant === "TODAS" || row.plant === selectedPlant;

    const matchesSearch =
      row.spare_part_name.toLowerCase().includes(search.toLowerCase()) ||
      row.material.toLowerCase().includes(search.toLowerCase());

    return matchesPlant && matchesSearch;
  });

  $: totalEstimatedQty = filteredRows.reduce(
    (sum, row) => sum + row.estimated_quantity,
    0
  );

  $: totalParts = filteredRows.length;
</script>

<section class="page">
  <div class="header">
    <div>
      <h1>Pronóstico de Demanda de Refacciones</h1>
      <p>
        Cantidades estimadas de refacciones requeridas para los próximos 30 días.
      </p>
    </div>
  </div>

  {#if noModel}
    <div class="no-model">
      <h2>No hay modelo existente</h2>
      <p>
        Entrena un modelo primero para ver los pronósticos de demanda de refacciones.
      </p>
    </div>
  {:else}
    <div class="cards">
      <div class="card">
        <p>Cantidad estimada total</p>
        <h2>{totalEstimatedQty}</h2>
      </div>

      <div class="card">
        <p>Registros mostrados</p>
        <h2>{totalParts}</h2>
      </div>
    </div>

    {#if modelLoading}
      <div class="model-info loading">Loading current model info...</div>
    {:else if currentModel}
      <div class="model-info">
        <h3>Modelo de Producción Actual</h3>
        <div class="model-grid">
          <div>
            <span class="label">ID de Versión</span>
            <span class="value mono">{currentModel.version_id}</span>
          </div>
          <div>
            <span class="label">Entrenado el</span>
            <span class="value">{formatDate(currentModel.timestamp)}</span>
          </div>
          <div>
            <span class="label">MAE de Validación</span>
            <span class="value">{currentModel.val_mae?.toFixed(4) ?? "—"}</span>
          </div>
          <div>
            <span class="label">R² de Validación</span>
            <span class="value">{currentModel.val_r2?.toFixed(4) ?? "—"}</span>
          </div>
          <div>
            <span class="label">RMSE de Validación</span>
            <span class="value">{currentModel.val_rmse?.toFixed(4) ?? "—"}</span>
          </div>
        </div>
      </div>
    {/if}

    <div class="filters">
      <label>
        Planta
        <select bind:value={selectedPlant}>
          {#each plants as plant}
            <option value={plant}>{plant}</option>
          {/each}
        </select>
      </label>

      <label>
        Buscar refacción
        <input
          type="text"
          bind:value={search}
          placeholder="Buscar por nombre de refacción o ID de material"
        />
      </label>
    </div>

    {#if loading}
      <p>Cargando predicciones...</p>
    {:else if errorMessage}
      <div class="error">
        <p>{errorMessage}</p>
      </div>
    {:else if filteredRows.length === 0}
      <p>Ninguna predicción coincide con tus filtros.</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Planta</th>
              <th>ID de Material</th>
              <th>Nombre de Refacción</th>
              <th>Cantidad Estimada Requerida</th>
            </tr>
          </thead>

          <tbody>
            {#each filteredRows as row}
              <tr>
                <td>{row.plant}</td>
                <td>{row.material}</td>
                <td>{row.spare_part_name}</td>
                <td>{row.estimated_quantity}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</section>

<style>
  .page {
    padding: 2rem;
  }

  .header {
    margin-bottom: 1.5rem;
  }

  h1 {
    font-size: 2rem;
    font-weight: 700;
  }

  p {
    color: #666;
  }

  .cards {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  .card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 1rem;
    min-width: 220px;
  }

  .card h2 {
    font-size: 2rem;
    margin: 0;
  }

  .filters {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-weight: 600;
  }

  input,
  select {
    padding: 0.6rem;
    border: 1px solid #ccc;
    border-radius: 8px;
    min-width: 240px;
  }

  .table-wrapper {
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    background: white;
  }

  th,
  td {
    padding: 0.8rem;
    border-bottom: 1px solid #eee;
    text-align: left;
  }

  th {
    background: #f7f7f7;
  }

  .error {
    color: #b91c1c;
    background: #fef2f2;
    border: 1px solid #ef4444;
    border-radius: 8px;
    padding: 1rem;
  }

  .model-info {
    background: white;
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 1.5rem;
  }

  .model-info h3 {
    margin: 0 0 0.8rem 0;
    font-size: 1.1rem;
    font-weight: 600;
  }

  .model-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
  }

  .model-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .label {
    font-size: 0.75rem;
    color: #6b7280;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .value {
    font-size: 0.95rem;
    font-weight: 600;
    color: #111827;
  }

  .mono {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
  }

  .model-info.loading {
    color: #6b7280;
    background: #f9fafb;
  }

  .no-model {
    background: white;
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
  }

  .no-model h2 {
    font-size: 1.5rem;
    margin: 0 0 0.5rem 0;
  }

  .no-model p {
    margin: 0;
    color: #6b7280;
  }
</style>