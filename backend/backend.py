import os
import time
import json
import uuid
import io
import joblib
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Union
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import xgboost as xgb

app = FastAPI(title="Spare Parts Inventory Prediction Engine")

# Enable CORS for Svelte frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURATION ---
MODEL_DIR = "../model"
# Metadata file that acts as the single source of truth for the active model version
ACTIVE_VERSION_CONFIG = os.path.join(MODEL_DIR, "active_version.json")

# Default raw data used for predictions when no upload is present
DEFAULT_DATA_CANDIDATES = [
    "../../Equipo-D/data/raw/raw_data.xlsx",
    "../data/raw/raw_data.xlsx",
    "raw_data.xlsx",
]

# Consumables list path (for filtering out consumable items)
CONSUMABLES_CANDIDATES = [
    "../../Equipo-D/data/raw/consumables.xlsx",
    "../data/raw/consumables.xlsx",
    "consumables.xlsx",
]

# In-memory registry to hold staging candidates before confirmation
CANDIDATE_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Required Excel worksheets
REQUIRED_SHEETS = ["Equipos", "Ordenes de trabajo", "Refacciones"]

# Columns we expect in each sheet (used for validation and reading)
EXPECTED_COLUMNS = {
    "Equipos": ["EQUIPO", "MARCA", "MODELO"],
    "Ordenes de trabajo": ["Order", "Equipment", "Plant", "Created On"],
    "Refacciones": ["Order", "Material", "Posting Date", "Quantity in UnE"],
}


# --- PYDANTIC MODELS ---

class ConfirmModelRequest(BaseModel):
    run_id: str
    use_new_model: str  # "y" or "n"


class RollbackModelRequest(BaseModel):
    version_id: str


# --- HELPER UTILITIES ---

def find_first_existing(paths: List[str]) -> str:
    for p in paths:
        if os.path.exists(p):
            return p
    return ""


def get_active_version_id() -> str:
    """Reads the active version tracking file, returns 'legacy' if file doesn't exist."""
    if os.path.exists(ACTIVE_VERSION_CONFIG):
        try:
            with open(ACTIVE_VERSION_CONFIG, "r") as f:
                config = json.load(f)
                return config.get("active_version_id", "legacy")
        except Exception:
            return "legacy"
    return "legacy"


def load_production_artifacts():
    """Loads production model components securely based on the active version tracker."""
    try:
        version_id = get_active_version_id()

        if version_id == "legacy":
            model_path = os.path.join(MODEL_DIR, "production_pipeline.joblib")
            encoder_path = os.path.join(MODEL_DIR, "encoder_mappings.joblib")
            metrics_path = os.path.join(MODEL_DIR, "current_production_metrics.json")
        else:
            model_path = os.path.join(MODEL_DIR, f"model_{version_id}.joblib")
            encoder_path = os.path.join(MODEL_DIR, f"encoders_{version_id}.joblib")
            metrics_path = os.path.join(MODEL_DIR, f"metrics_{version_id}.json")

        model = joblib.load(model_path)
        encoders = joblib.load(encoder_path)
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        return model, encoders, metrics
    except Exception:
        return None, None, None


def load_consumables() -> set:
    """Load consumables list from Excel for filtering."""
    path = find_first_existing(CONSUMABLES_CANDIDATES)
    if not path:
        return set()
    try:
        df = pd.read_excel(path, sheet_name=0, header=None)
        items = df[0].astype(str).str.strip().str.upper().unique()
        return set(items)
    except Exception:
        return set()


def preprocess_raw_sheets(excel_file: Union[str, bytes]) -> pd.DataFrame:
    """
    Replicates the core preprocessing from notebook 03.
    Reads the three required sheets, cleans, merges, filters consumables,
    and returns a consolidated DataFrame.
    """
    try:
        if isinstance(excel_file, bytes):
            excel_file = io.BytesIO(excel_file)
        xls = pd.ExcelFile(excel_file)
    except Exception as e:
        raise ValueError(f"Invalid Excel file format: {str(e)}")

    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in xls.sheet_names]
    if missing_sheets:
        raise ValueError(f"Missing required Excel worksheets: {', '.join(missing_sheets)}")

    # --- Read sheets ---
    teams = pd.read_excel(xls, sheet_name="Equipos")
    orders = pd.read_excel(xls, sheet_name="Ordenes de trabajo")
    repairs = pd.read_excel(xls, sheet_name="Refacciones")

    # --- Validate required columns ---
    missing_cols_report = []
    for sheet_name, required_cols in EXPECTED_COLUMNS.items():
        df_map = {"Equipos": teams, "Ordenes de trabajo": orders, "Refacciones": repairs}
        df_local = df_map[sheet_name]
        missing = [c for c in required_cols if c not in df_local.columns]
        if missing:
            missing_cols_report.append(f"Sheet '{sheet_name}' missing columns: {', '.join(missing)}")
    if missing_cols_report:
        raise ValueError("; ".join(missing_cols_report))

    # --- Clean keys ---
    teams["EQUIPO"] = teams["EQUIPO"].astype(str).str.strip()
    orders["Order"] = orders["Order"].astype(str).str.strip()
    orders["Equipment"] = orders["Equipment"].astype(str).str.strip()
    repairs["Order"] = repairs["Order"].astype(str).str.strip()

    # --- Parse dates ---
    orders["Created On"] = pd.to_datetime(orders["Created On"], errors="coerce")
    repairs["Posting Date"] = pd.to_datetime(repairs["Posting Date"], errors="coerce")

    # --- Merge ---
    base = orders.merge(repairs, on="Order", how="inner", suffixes=("_order", "_part"))
    base = base.merge(teams, left_on="Equipment", right_on="EQUIPO", how="left")

    # --- Clean merged data ---
    base = base.dropna(subset=["Plant", "Material", "Posting Date", "Quantity in UnE"])
    base = base[base["Quantity in UnE"] >= 0]
    base = base[base["Description_part"].astype(str).str.strip() != ""]

    # --- Filter consumables ---
    consumables = load_consumables()
    if consumables:
        mask = ~base["Description_part"].astype(str).str.strip().str.upper().isin(consumables)
        base = base[mask]

    # --- Standardize column names ---
    base = base.rename(columns={
        "Plant": "plant",
        "Material": "material",
        "Description_part": "spare_part_name",
    })

    return base


def build_snapshot(master_df: pd.DataFrame, ref_date: pd.Timestamp) -> pd.DataFrame:
    """
    Builds a single point-in-time feature matrix for all plant-material combos
    active up to ref_date. Target is demand in the 30 days after ref_date.
    """
    past = master_df[master_df["Posting Date"] < ref_date]
    future = master_df[
        (master_df["Posting Date"] >= ref_date)
        & (master_df["Posting Date"] < ref_date + pd.Timedelta(days=30))
    ]

    # All combos seen before ref_date
    if past.empty:
        return pd.DataFrame()

    combos = past[["plant", "material", "spare_part_name"]].drop_duplicates()

    # 90-day historical aggregates
    past_90 = past[past["Posting Date"] >= ref_date - pd.Timedelta(days=90)]
    feat_90 = past_90.groupby(["plant", "material"]).agg(
        qty_last_90d=("Quantity in UnE", "sum"),
        orders_last_90d=("Order", "nunique"),
    ).reset_index()

    # 180-day historical aggregates
    past_180 = past[past["Posting Date"] >= ref_date - pd.Timedelta(days=180)]
    feat_180 = past_180.groupby(["plant", "material"]).agg(
        qty_last_180d=("Quantity in UnE", "sum"),
        orders_last_180d=("Order", "nunique"),
    ).reset_index()

    # Days since last use
    last_use = past.groupby(["plant", "material"])["Posting Date"].max().reset_index()
    last_use["days_since_last_used"] = (ref_date - last_use["Posting Date"]).dt.days
    last_use = last_use.drop(columns=["Posting Date"])

    # Target: next 30 days
    target = future.groupby(["plant", "material"]).agg(
        qty_needed_next_30d=("Quantity in UnE", "sum")
    ).reset_index()

    # Assemble snapshot
    snap = combos.merge(feat_90, on=["plant", "material"], how="left")
    snap = snap.merge(feat_180, on=["plant", "material"], how="left")
    snap = snap.merge(last_use, on=["plant", "material"], how="left")
    snap = snap.merge(target, on=["plant", "material"], how="left")

    snap = snap.fillna(0)
    snap["reference_month"] = ref_date.month
    snap["part_never_used"] = (snap["days_since_last_used"] == 0).astype(int)
    snap["reference_date"] = ref_date

    return snap


def create_training_snapshots(master_df: pd.DataFrame) -> pd.DataFrame:
    """Creates monthly snapshots across the data span for training/validation."""
    min_date = master_df["Posting Date"].min() + pd.DateOffset(months=6)
    max_date = master_df["Posting Date"].max() - pd.Timedelta(days=30)

    if min_date >= max_date:
        # Not enough date range — create a single snapshot at max_date
        ref_dates = [max_date]
    else:
        ref_dates = pd.date_range(start=min_date, end=max_date, freq="MS")

    snapshots = []
    for ref_date in ref_dates:
        snap = build_snapshot(master_df, ref_date)
        if not snap.empty:
            snapshots.append(snap)

    if not snapshots:
        raise ValueError("No valid snapshots could be generated from the dataset.")

    return pd.concat(snapshots, ignore_index=True)


def apply_target_encoding(train_df, val_df, test_df, target_col):
    """Target-encode plant and material using training statistics only."""
    global_mean = train_df[target_col].mean()
    plant_map = train_df.groupby("plant")[target_col].mean()
    material_map = train_df.groupby("material")[target_col].mean()

    for df in (train_df, val_df, test_df):
        df["plant_encoded"] = df["plant"].map(plant_map).fillna(global_mean)
        df["material_encoded"] = df["material"].map(material_map).fillna(global_mean)

    encoders = {
        "global_mean": global_mean,
        "plant_target_mean": plant_map.to_dict(),
        "material_target_mean": material_map.to_dict(),
    }
    return encoders


def train_xgboost_model(X_train, y_train, X_val, y_val):
    """Trains an XGBoost Regressor with Poisson objective."""
    model = xgb.XGBRegressor(
        objective="count:poisson",
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        eval_metric="poisson-nloglik",
    )
    model.fit(X_train, y_train)
    return model


def compute_metrics(model, X, y):
    preds = model.predict(X)
    preds = np.clip(preds, 0, None)
    return {
        "mae": round(float(mean_absolute_error(y, preds)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y, preds))), 4),
        "r2": round(float(r2_score(y, preds)), 4),
    }


# --- STARTUP: Train a default model if none exists ---

@app.on_event("startup")
def startup_event():
    os.makedirs(MODEL_DIR, exist_ok=True)

    # If an active version already exists, do nothing
    if os.path.exists(ACTIVE_VERSION_CONFIG):
        return

    # If legacy artifacts exist, do nothing (let them load naturally)
    legacy_model = os.path.join(MODEL_DIR, "production_pipeline.joblib")
    if os.path.exists(legacy_model):
        return

    # Try to train an initial model from default data
    data_path = find_first_existing(DEFAULT_DATA_CANDIDATES)
    if not data_path:
        print("[Startup] No default data found. Skipping auto-training.")
        return

    try:
        print(f"[Startup] Auto-training initial model from {data_path}")
        master = preprocess_raw_sheets(data_path)
        model_df = create_training_snapshots(master)

        # Temporal split
        unique_dates = sorted(model_df["reference_date"].unique())
        train_end = unique_dates[int(len(unique_dates) * 0.70)]
        val_end = unique_dates[int(len(unique_dates) * 0.85)]

        train_df = model_df[model_df["reference_date"] <= train_end].copy()
        val_df = model_df[
            (model_df["reference_date"] > train_end)
            & (model_df["reference_date"] <= val_end)
        ].copy()
        test_df = model_df[model_df["reference_date"] > val_end].copy()

        target_col = "qty_needed_next_30d"
        feature_cols = [
            "plant_encoded",
            "material_encoded",
            "qty_last_90d",
            "orders_last_90d",
            "qty_last_180d",
            "orders_last_180d",
            "days_since_last_used",
            "reference_month",
            "part_never_used",
        ]

        encoders = apply_target_encoding(train_df, val_df, test_df, target_col)

        X_train = train_df[feature_cols]
        y_train = train_df[target_col]
        X_val = val_df[feature_cols]
        y_val = val_df[target_col]
        X_test = test_df[feature_cols]
        y_test = test_df[target_col]

        model = train_xgboost_model(X_train, y_train, X_val, y_val)

        train_metrics = compute_metrics(model, X_train, y_train)
        val_metrics = compute_metrics(model, X_val, y_val)
        test_metrics = compute_metrics(model, X_test, y_test)

        version_id = "auto-" + str(uuid.uuid4())[:8]
        full_metrics = {
            "version_id": version_id,
            "timestamp": time.time(),
            "train_mae": train_metrics["mae"],
            "val_mae": val_metrics["mae"],
            "test_mae": test_metrics["mae"],
            "train_rmse": train_metrics["rmse"],
            "val_rmse": val_metrics["rmse"],
            "test_rmse": test_metrics["rmse"],
            "train_r2": train_metrics["r2"],
            "val_r2": val_metrics["r2"],
            "test_r2": test_metrics["r2"],
        }

        joblib.dump(model, os.path.join(MODEL_DIR, f"model_{version_id}.joblib"))
        joblib.dump(encoders, os.path.join(MODEL_DIR, f"encoders_{version_id}.joblib"))
        with open(os.path.join(MODEL_DIR, f"metrics_{version_id}.json"), "w") as f:
            json.dump(full_metrics, f, indent=4)

        with open(ACTIVE_VERSION_CONFIG, "w") as f:
            json.dump({"active_version_id": version_id}, f, indent=4)

        print(f"[Startup] Auto-trained model {version_id} saved.")
    except Exception as e:
        print(f"[Startup] Auto-training failed: {e}")


# --- API ENDPOINTS ---

@app.get("/api/predictions")
def get_predictions():
    """
    ENDPOINT 1: DASHBOARD PREDICTIONS
    Loads the active model, builds features from the default dataset,
    and returns estimated quantities for the next 30 days per plant-material.
    """
    model, encoders, _ = load_production_artifacts()

    if model is None or encoders is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No production model is available. Please train a model first.",
        )

    data_path = find_first_existing(DEFAULT_DATA_CANDIDATES)
    if not data_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Default dataset not found on server.",
        )

    try:
        master = preprocess_raw_sheets(data_path)
        ref_date = master["Posting Date"].max()
        snap = build_snapshot(master, ref_date)

        if snap.empty:
            return []

        # Apply target encoding using stored encoders
        snap["plant_encoded"] = snap["plant"].map(
            encoders.get("plant_target_mean", {})
        ).fillna(encoders.get("global_mean", 0))
        snap["material_encoded"] = snap["material"].map(
            encoders.get("material_target_mean", {})
        ).fillna(encoders.get("global_mean", 0))

        feature_cols = [
            "plant_encoded",
            "material_encoded",
            "qty_last_90d",
            "orders_last_90d",
            "qty_last_180d",
            "orders_last_180d",
            "days_since_last_used",
            "reference_month",
            "part_never_used",
        ]

        X = snap[feature_cols]
        preds = model.predict(X)
        preds = np.clip(preds, 0, None)

        snap["predicted_quantity"] = np.floor(preds).astype(int)

        # Return only rows with non-zero predictions + a sensible sample cap
        result = snap[snap["predicted_quantity"] > 0][
            ["plant", "material", "spare_part_name", "predicted_quantity"]
        ].to_dict(orient="records")

        # If everything predicted zero, return top 50 by predicted_quantity anyway
        if not result:
            snap = snap.sort_values("predicted_quantity", ascending=False).head(50)
            result = snap[
                ["plant", "material", "spare_part_name", "predicted_quantity"]
            ].to_dict(orient="records")

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction pipeline failed: {str(e)}",
        )


@app.post("/api/models/train", status_code=status.HTTP_200_OK)
async def train_new_model(file: UploadFile = File(...)):
    """
    ENDPOINT 2: DATA SUBMISSION & MODEL RETRAINING
    Accepts a raw Excel workbook, preprocesses it, trains a candidate XGBoost model,
    and returns a comparison against the current production model.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid format. Only Excel Workbooks (.xlsx / .xls) are accepted.",
        )

    file_content = await file.read()

    try:
        master = preprocess_raw_sheets(file_content)
    except ValueError as ve:
        error_msg = str(ve)
        # Try to extract missing columns info for frontend
        missing_columns = []
        if "missing columns" in error_msg.lower():
            parts = error_msg.split("missing columns:")
            if len(parts) > 1:
                missing_columns = [c.strip() for c in parts[1].split(",")]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": error_msg, "missing_columns": missing_columns},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": f"Preprocessing failed: {str(e)}", "missing_columns": []},
        )

    try:
        model_df = create_training_snapshots(master)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(ve), "missing_columns": []},
        )

    # Temporal split
    unique_dates = sorted(model_df["reference_date"].unique())
    train_end = unique_dates[int(len(unique_dates) * 0.70)]
    val_end = unique_dates[int(len(unique_dates) * 0.85)]

    train_df = model_df[model_df["reference_date"] <= train_end].copy()
    val_df = model_df[
        (model_df["reference_date"] > train_end)
        & (model_df["reference_date"] <= val_end)
    ].copy()
    test_df = model_df[model_df["reference_date"] > val_end].copy()

    target_col = "qty_needed_next_30d"
    feature_cols = [
        "plant_encoded",
        "material_encoded",
        "qty_last_90d",
        "orders_last_90d",
        "qty_last_180d",
        "orders_last_180d",
        "days_since_last_used",
        "reference_month",
        "part_never_used",
    ]

    encoders = apply_target_encoding(train_df, val_df, test_df, target_col)

    X_train = train_df[feature_cols]
    y_train = train_df[target_col]
    X_val = val_df[feature_cols]
    y_val = val_df[target_col]

    candidate_model = train_xgboost_model(X_train, y_train, X_val, y_val)

    train_metrics = compute_metrics(candidate_model, X_train, y_train)
    val_metrics = compute_metrics(candidate_model, X_val, y_val)

    new_metrics = {
        "train_mae": train_metrics["mae"],
        "val_mae": val_metrics["mae"],
        "train_rmse": train_metrics["rmse"],
        "val_rmse": val_metrics["rmse"],
        "train_r2": train_metrics["r2"],
        "val_r2": val_metrics["r2"],
    }

    # Load current model metrics for comparison
    _, _, current_metrics = load_production_artifacts()
    if current_metrics is None:
        current_metrics = {
            "train_mae": None,
            "val_mae": None,
            "train_rmse": None,
            "val_rmse": None,
            "train_r2": None,
            "val_r2": None,
        }

    run_id = str(uuid.uuid4())
    new_metrics["version_id"] = run_id
    new_metrics["timestamp"] = time.time()

    CANDIDATE_REGISTRY[run_id] = {
        "model": candidate_model,
        "encoders": encoders,
        "metrics": new_metrics,
    }

    # Persist candidate to disk so it survives backend restarts
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{run_id}.joblib")
        joblib.dump({
            "model": candidate_model,
            "encoders": encoders,
            "metrics": new_metrics,
        }, candidate_bundle_path)
    except Exception:
        pass  # Best-effort persistence; in-memory registry is the primary source

    return {
        "run_id": run_id,
        "message": "Data ingestion successful. Candidate pipeline evaluated.",
        "current_model": current_metrics,
        "new_model": new_metrics,
    }


@app.post("/api/models/confirm")
def confirm_model_promotion(payload: ConfirmModelRequest):
    """
    ENDPOINT 3: MODEL PROMOTION CONFIRMATION
    Accepts the frontend's 'use_new_model' flag ('y' or 'n') and either
    promotes the candidate to production or discards it.
    """
    action = payload.use_new_model.strip().lower()

    if action == "n":
        CANDIDATE_REGISTRY.pop(payload.run_id, None)
        # Also clean up the on-disk candidate bundle
        candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
        if os.path.exists(candidate_bundle_path):
            os.remove(candidate_bundle_path)
        return {"message": "Candidate discarded. Existing production artifacts retained."}

    if action == "y":
        candidate = CANDIDATE_REGISTRY.get(payload.run_id)
        if not candidate:
            # Try loading from disk if backend was restarted
            candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
            if os.path.exists(candidate_bundle_path):
                try:
                    bundle = joblib.load(candidate_bundle_path)
                    candidate = {
                        "model": bundle["model"],
                        "encoders": bundle["encoders"],
                        "metrics": bundle["metrics"],
                    }
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Staged run ID not found or already processed.",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Staged run ID not found or already processed.",
                )

        try:
            os.makedirs(MODEL_DIR, exist_ok=True)

            versioned_model_path = os.path.join(MODEL_DIR, f"model_{payload.run_id}.joblib")
            versioned_encoder_path = os.path.join(MODEL_DIR, f"encoders_{payload.run_id}.joblib")
            versioned_metrics_path = os.path.join(MODEL_DIR, f"metrics_{payload.run_id}.json")

            joblib.dump(candidate["model"], versioned_model_path)
            joblib.dump(candidate["encoders"], versioned_encoder_path)
            with open(versioned_metrics_path, "w") as f:
                json.dump(candidate["metrics"], f, indent=4)

            with open(ACTIVE_VERSION_CONFIG, "w") as f:
                json.dump({"active_version_id": payload.run_id}, f, indent=4)

            CANDIDATE_REGISTRY.pop(payload.run_id, None)
            # Clean up the on-disk candidate bundle after promotion
            candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
            if os.path.exists(candidate_bundle_path):
                os.remove(candidate_bundle_path)
            return {
                "message": f"Success! Model candidate {payload.run_id} has been promoted to production."
            }

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist production models: {str(e)}",
            )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid use_new_model value. Expected 'y' or 'n'.",
    )


@app.get("/api/models/history")
def get_model_history():
    """
    ENDPOINT 4: RETRIEVE ALL AVAILABLE HISTORICAL MODELS
    """
    if not os.path.exists(MODEL_DIR):
        return []

    history = []
    active_id = get_active_version_id()

    for file in os.listdir(MODEL_DIR):
        if file.startswith("metrics_") and file.endswith(".json"):
            v_id = file.replace("metrics_", "").replace(".json", "")
            try:
                with open(os.path.join(MODEL_DIR, file), "r") as f:
                    meta = json.load(f)
                    meta["is_active"] = (v_id == active_id)
                    history.append(meta)
            except Exception:
                continue

    history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return history


@app.post("/api/models/rollback")
def rollback_model(payload: RollbackModelRequest):
    """
    ENDPOINT 5: ROLLBACK
    Points the active pointer back to an existing older version.
    """
    target_metrics_path = os.path.join(MODEL_DIR, f"metrics_{payload.version_id}.json")

    if not os.path.exists(target_metrics_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested fallback version does not exist.",
        )

    try:
        with open(ACTIVE_VERSION_CONFIG, "w") as f:
            json.dump({"active_version_id": payload.version_id}, f, indent=4)

        return {
            "message": f"Successfully rolled back active production engine to version: {payload.version_id}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed updating pointer metadata during rollback: {str(e)}",
        )
