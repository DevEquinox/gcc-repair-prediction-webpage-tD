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

  let selectedPlant = "ALL";
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
        if (detail.toLowerCase().includes("no existing model") || detail.toLowerCase().includes("no active model")) {
          noModel = true;
        } else {
          errorMessage = detail || "Failed to load predictions.";
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
      errorMessage = "Network error. Is the backend running?";
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

  $: plants = ["ALL", ...Array.from(new Set(rows.map((row) => row.plant))).sort()];

  $: filteredRows = rows.filter((row) => {
    const matchesPlant = selectedPlant === "ALL" || row.plant === selectedPlant;

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
      <h1>Spare Parts Demand Forecast</h1>
      <p>
        Estimated spare part quantities required for the next 30 days.
      </p>
    </div>
  </div>

  {#if noModel}
    <div class="no-model">
      <h2>No existing model</h2>
      <p>
        Train a model first to see spare part demand predictions.
      </p>
    </div>
  {:else}
    <div class="cards">
      <div class="card">
        <p>Total estimated quantity</p>
        <h2>{totalEstimatedQty}</h2>
      </div>

      <div class="card">
        <p>Displayed part records</p>
        <h2>{totalParts}</h2>
      </div>
    </div>

    {#if modelLoading}
      <div class="model-info loading">Loading current model info...</div>
    {:else if currentModel}
      <div class="model-info">
        <h3>Current Production Model</h3>
        <div class="model-grid">
          <div>
            <span class="label">Version ID</span>
            <span class="value mono">{currentModel.version_id}</span>
          </div>
          <div>
            <span class="label">Trained At</span>
            <span class="value">{formatDate(currentModel.timestamp)}</span>
          </div>
          <div>
            <span class="label">Val MAE</span>
            <span class="value">{currentModel.val_mae?.toFixed(4) ?? "—"}</span>
          </div>
          <div>
            <span class="label">Val R²</span>
            <span class="value">{currentModel.val_r2?.toFixed(4) ?? "—"}</span>
          </div>
          <div>
            <span class="label">Val RMSE</span>
            <span class="value">{currentModel.val_rmse?.toFixed(4) ?? "—"}</span>
          </div>
        </div>
      </div>
    {/if}

    <div class="filters">
      <label>
        Plant
        <select bind:value={selectedPlant}>
          {#each plants as plant}
            <option value={plant}>{plant}</option>
          {/each}
        </select>
      </label>

      <label>
        Search part
        <input
          type="text"
          bind:value={search}
          placeholder="Search by part name or material ID"
        />
      </label>
    </div>

    {#if loading}
      <p>Loading predictions...</p>
    {:else if errorMessage}
      <div class="error">
        <p>{errorMessage}</p>
      </div>
    {:else if filteredRows.length === 0}
      <p>No predictions match your filters.</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Plant</th>
              <th>Material ID</th>
              <th>Spare Part Name</th>
              <th>Estimated Quantity Required</th>
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