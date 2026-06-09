<script lang="ts">
  import { onMount } from "svelte";

  type PredictionRow = {
    plant: string;
    material: string;
    spare_part_name: string;
    estimated_quantity: number;
  };

  let rows: PredictionRow[] = [];
  let loading = true;
  let errorMessage = "";

  let selectedPlant = "ALL";
  let search = "";

  onMount(async () => {
    try {
      const response = await fetch("/api/predictions");
      if (!response.ok) {
        const data = await response.json();
        errorMessage = data.detail ?? "Failed to load predictions.";
        loading = false;
        return;
      }
      const data = await response.json();
      // Map backend field names to frontend expected fields
      rows = data.map((item: any) => ({
        plant: item.plant,
        material: String(item.material),
        spare_part_name: item.spare_part_name,
        estimated_quantity: item.predicted_quantity ?? 0
      }));
    } catch (err) {
      errorMessage = "Network error. Is the backend running?";
    } finally {
      loading = false;
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
</style>