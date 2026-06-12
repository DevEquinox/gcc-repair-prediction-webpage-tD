<script lang="ts">
  import { onMount } from "svelte";

  type ModelMetrics = {
    train_mae: number;
    val_mae: number;
    train_r2: number;
    val_r2: number;
    train_rmse: number;
    val_rmse: number;
  };

  type TrainResponse = {
    run_id: string;
    message: string;
    current_model: ModelMetrics;
    new_model: ModelMetrics;
  };

  type Requirements = {
    sheets: string[];
    columns: Record<string, string[]>;
  };

  let file: File | null = null;
  let consumablesFile: File | null = null;
  let requirements: Requirements | null = null;
  let requirementsLoading = true;
  let requirementsError = "";

  let loading = false;
  let errorMessage = "";
  let missingColumns: string[] = [];
  let trainResponse: TrainResponse | null = null;
  let confirmMessage = "";


  function handleFileChange(event: Event) {
    const input = event.target as HTMLInputElement;
    file = input.files?.[0] ?? null;

    errorMessage = "";
    missingColumns = [];
    trainResponse = null;
    confirmMessage = "";
  }

  function handleConsumablesChange(event: Event) {
    const input = event.target as HTMLInputElement;
    consumablesFile = input.files?.[0] ?? null;

    errorMessage = "";
    missingColumns = [];
    trainResponse = null;
    confirmMessage = "";
  }

  async function uploadDataset() {
    if (!file) {
      errorMessage = "Por favor carga un dataset primero.";
      return;
    }

    loading = true;
    errorMessage = "";
    missingColumns = [];
    trainResponse = null;
    confirmMessage = "";

    const formData = new FormData();
    formData.append("file", file);
    if (consumablesFile) {
      formData.append("consumables", consumablesFile);
    }

    try {
      const response = await fetch("/api/models/train", {
        method: "POST",
        body: formData
      });

      const data = await response.json();

      if (!response.ok) {
        errorMessage = data.message ?? "El dataset no pudo ser procesado.";
        missingColumns = data.missing_columns ?? [];
        return;
      }

      trainResponse = data;
    } catch (error) {
      console.log(error);
      errorMessage = "Error inesperado al cargar el dataset.";
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    try {
      const response = await fetch("/api/models/requirements");
      if (!response.ok) {
        const data = await response.json();
        requirementsError = data.detail ?? "Error al cargar requisitos.";
        return;
      }
      requirements = await response.json();
    } catch (err) {
      requirementsError = "Error de red cargando requisitos.";
    } finally {
      requirementsLoading = false;
    }
  });

  async function confirmModel(useNewModel: boolean) {
    if (!trainResponse) return;

    confirmMessage = "";

    const response = await fetch("/api/models/confirm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        run_id: trainResponse.run_id,
        use_new_model: useNewModel ? "y" : "n"
      })
    });

    const data = await response.json();

    if (!response.ok) {
      confirmMessage = data.detail ?? data.message ?? "No se pudo confirmar la selección del modelo.";
      return;
    }

    confirmMessage = data.message;
  }
</script>

<section class="page">
  <h1>Entrenar Nuevo Modelo</h1>
  <p>
    Carga un nuevo dataset para entrenar un modelo candidato y compararlo contra
    el modelo de producción actual.
  </p>

  {#if requirementsLoading}
    <p>Cargando requisitos del dataset...</p>
  {:else if requirementsError}
    <div class="error">
      <p>{requirementsError}</p>
    </div>
  {:else if requirements}
    <div class="requirements-card">
      <h2>Formato de Dataset Requerido</h2>
      <p>El libro de Excel cargado debe contener estas hojas:</p>
      <ul>
        {#each requirements.sheets as sheet}
          <li><strong>{sheet}</strong></li>
        {/each}
      </ul>

      <p>Cada hoja debe tener exactamente estos nombres de columna:</p>
      {#each Object.entries(requirements.columns) as [sheet, columns]}
        <div class="sheet-columns">
          <span class="sheet-name">{sheet}</span>
          <span class="column-list">{columns.join(", ")}</span>
        </div>
      {/each}
    </div>
  {/if}

  <div class="upload-card">
    <label>
      Cargar dataset
      <input type="file" accept=".xlsx,.xls" on:change={handleFileChange} />
    </label>

    {#if file}
      <p class="file-name">Archivo seleccionado: {file.name}</p>
    {/if}

    <label>
      Cargar lista de consumibles (opcional)
      <input type="file" accept=".xlsx,.xls" on:change={handleConsumablesChange} />
    </label>

    {#if consumablesFile}
      <p class="file-name">Archivo de consumibles seleccionado: {consumablesFile.name}</p>
    {/if}

    <button on:click={uploadDataset} disabled={loading}>
      {loading ? "Entrenando..." : "Cargar y Entrenar"}
    </button>
  </div>

  {#if errorMessage}
    <div class="error">
      <h3>Error en el dataset</h3>
      <p>{errorMessage}</p>

      {#if missingColumns.length > 0}
        <p>Columnas faltantes:</p>
        <ul>
          {#each missingColumns as column}
            <li>{column}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  {#if trainResponse}
    <div class="results">
      <h2>Comparación de Modelos</h2>
      <p>{trainResponse.message}</p>

      <table>
        <thead>
          <tr>
            <th>Métrica</th>
            <th>Modelo Actual</th>
            <th>Nuevo Modelo</th>
          </tr>
        </thead>

        <tbody>
          <tr>
            <td>MAE Entrenamiento</td>
            <td>{trainResponse.current_model.train_mae}</td>
            <td>{trainResponse.new_model.train_mae}</td>
          </tr>

          <tr>
            <td>MAE Validación</td>
            <td>{trainResponse.current_model.val_mae}</td>
            <td>{trainResponse.new_model.val_mae}</td>
          </tr>

          <tr>
            <td>R² Entrenamiento</td>
            <td>{trainResponse.current_model.train_r2}</td>
            <td>{trainResponse.new_model.train_r2}</td>
          </tr>

          <tr>
            <td>R² Validación</td>
            <td>{trainResponse.current_model.val_r2}</td>
            <td>{trainResponse.new_model.val_r2}</td>
          </tr>

          <tr>
            <td>RMSE Entrenamiento</td>
            <td>{trainResponse.current_model.train_rmse}</td>
            <td>{trainResponse.new_model.train_rmse}</td>
          </tr>

          <tr>
            <td>RMSE Validación</td>
            <td>{trainResponse.current_model.val_rmse}</td>
            <td>{trainResponse.new_model.val_rmse}</td>
          </tr>
        </tbody>
      </table>

      <div class="actions">
        <button class="accept" on:click={() => confirmModel(true)}>
          Usar nuevo modelo
        </button>

        <button class="reject" on:click={() => confirmModel(false)}>
          Mantener modelo anterior
        </button>
      </div>
    </div>
  {/if}

  {#if confirmMessage}
    <div class="confirmation">
      {confirmMessage}
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
  }

  p {
    color: #666;
  }

  .upload-card,
  .results,
  .error,
  .confirmation,
  .requirements-card {
    margin-top: 1.5rem;
    padding: 1.2rem;
    border-radius: 12px;
    border: 1px solid #ddd;
    background: white;
  }

  .requirements-card h2 {
    font-size: 1.2rem;
    margin: 0 0 0.8rem 0;
  }

  .requirements-card ul {
    margin: 0.5rem 0 1rem 0;
    padding-left: 1.2rem;
  }

  .requirements-card li {
    margin-bottom: 0.3rem;
  }

  .sheet-columns {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.4rem;
  }

  .sheet-name {
    font-weight: 600;
    min-width: 160px;
  }

  .column-list {
    color: #4b5563;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    font-weight: 600;
  }

  input {
    margin-top: 0.5rem;
  }

  button {
    margin-top: 1rem;
    padding: 0.7rem 1rem;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    background: #111827;
    color: white;
    font-weight: 600;
  }

  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .file-name {
    margin-top: 0.8rem;
  }

  .error {
    border-color: #ef4444;
    background: #fef2f2;
  }

  .error h3 {
    color: #b91c1c;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
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

  .actions {
    display: flex;
    gap: 1rem;
    margin-top: 1rem;
  }

  .accept {
    background: #15803d;
  }

  .reject {
    background: #991b1b;
  }

  .confirmation {
    background: #ecfdf5;
    border-color: #10b981;
  }
</style>