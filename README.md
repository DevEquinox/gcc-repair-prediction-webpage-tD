# Spare Parts Demand Forecast

Web application that predicts 30-day spare part demand for GCC's fleet maintenance operations. An XGBoost Poisson regressor turns historical work orders, part usage records, and truck characteristics into estimated quantities per plant and material.

## Live URL

`http://imgoingtostealthexenserverresourcestodothisheehee` *(replace with actual URL)*

## Repository Structure

| Directory | Purpose |
|-----------|---------|
| `backend/` | FastAPI service (Python 3.11) — prediction pipeline, retraining, model registry |
| `frontend/` | SvelteKit app (Node 20) — dashboard, predictions, model history, retraining UI |
| `model/` | Versioned model artifacts, encoder mappings, and metrics JSON |
| `nginx/` | Reverse proxy routing `/api` to backend and `/` to frontend |
| `docker-compose.yml` | Orchestrates backend, frontend, and nginx containers |

## Local Setup

1. Clone the repository.
2. Install [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/).
3. From the repository root run:
   ```bash
   docker-compose up --build
   ```
4. Open [http://localhost](http://localhost).

Requires Docker Engine 20.10+ and Compose 1.29+.

## Data Upload Format

The retraining endpoint (`POST /api/models/train`) accepts an **Excel workbook** (`.xlsx` or `.xls`) with exactly three worksheets:

| Worksheet | Required Columns | Description |
|-----------|------------------|-------------|
| `Equipos` | `EQUIPO`, `MARCA`, `MODELO` | Truck registry |
| `Ordenes de trabajo` | `Order`, `Equipment`, `Plant`, `Created On` | Maintenance orders |
| `Refacciones` | `Order`, `Material`, `Posting Date`, `Quantity in UnE` | Part usage logs |

- `Created On` and `Posting Date` must be parseable dates.
- `Quantity in UnE` must be numeric and non-negative.
- Records with missing `Material` codes are tolerated if part descriptions are present.

**Sample row** (from `Refacciones`):

| Order | Material | Posting Date | Quantity in UnE |
|-------|----------|--------------|-----------------|
| 41154281 | 3000791 | 2020-03-14 | 57.0 |

A full example workbook is available at `toDo`.

## Retraining Workflow

1. Go to `/dashboard/train-model`.
2. Upload an Excel workbook matching the format above.
3. The backend trains a candidate model and shows training vs. validation metrics next to the current production model.
4. Click **Use new model** to promote the candidate, or **Keep old model** to discard it.
5. View all versions and roll back at `/dashboard/model-history`.

## Authentication

None.

## Model Information

- **Algorithm**: XGBoost Regressor (Poisson objective)
- **Configuration**: `n_estimators=200`, `max_depth=6`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`
- **Training data**: GCC fleet maintenance records — 220 trucks, 33,521 work orders, 104,412 spare-part events
- **Original test-set performance**:
  - MAE: 1.62
  - RMSE: 9.38
  - R²: 0.74

## Known Limitations

1. **Demand sparsity**: Most plant-material combinations record zero demand in a 30-day window, so rare-demand events are inherently harder to predict.
2. **Missing external signals**: The model does not use route conditions, supplier delays, driver behaviour, or seasonality beyond month-of-year.
