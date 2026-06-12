import os
import time
import json
import uuid
import io
import base64
import joblib
import bcrypt
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Union
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import xgboost as xgb

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")
FRONTEND_ORIGIN_HOST = os.getenv("FRONTEND_ORIGIN_HOST", "")
if not FRONTEND_ORIGIN and FRONTEND_ORIGIN_HOST:
    FRONTEND_ORIGIN = f"https://{FRONTEND_ORIGIN_HOST}.onrender.com"

# Cross-origin deployments (e.g. separate Render Web Services) need
# SameSite=None, which in turn requires Secure. Same-origin deployments keep Lax.
SAMESITE = "none" if FRONTEND_ORIGIN else "lax"
if SAMESITE == "none":
    COOKIE_SECURE = True

def _decode_password_hash(raw_hash: str) -> str:
    if not raw_hash:
        return ""
    try:
        decoded = base64.b64decode(raw_hash.encode("utf-8"), validate=True)
        return decoded.decode("utf-8")
    except Exception:
        return raw_hash

AUTH_PASSWORD_HASH_DECODED = _decode_password_hash(AUTH_PASSWORD_HASH)
SESSION_COOKIE_NAME = "auth_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7

_session_serializer = URLSafeTimedSerializer(AUTH_SECRET_KEY or "fallback-secret")

app = FastAPI(title="Spare Parts Inventory Prediction Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN else ["*"],
    allow_credentials=bool(FRONTEND_ORIGIN),
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_DIR = "../model"
ACTIVE_VERSION_CONFIG = os.path.join(MODEL_DIR, "active_version.json")

CONSUMABLES_CANDIDATES = [
    "../../Equipo-D/data/raw/consumables.xlsx",
    "../data/raw/consumables.xlsx",
    "consumables.xlsx",
]

CANDIDATE_REGISTRY: Dict[str, Dict[str, Any]] = {}

REQUIRED_SHEETS = ["Equipos", "Ordenes de trabajo", "Refacciones"]

EXPECTED_COLUMNS = {
    "Equipos": ["EQUIPO", "MARCA", "MODELO"],
    "Ordenes de trabajo": ["Order", "Equipment", "Plant", "Created On"],
    "Refacciones": ["Order", "Material", "Posting Date", "Quantity in UnE"],
}

class ConfirmModelRequest(BaseModel):
    run_id: str
    use_new_model: str

class RollbackModelRequest(BaseModel):
    version_id: str

class LoginRequest(BaseModel):
    username: str
    password: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def create_session_token(username: str) -> str:
    return _session_serializer.dumps({"user": username})

def decode_session_token(token: str) -> dict:
    return _session_serializer.loads(token, max_age=SESSION_MAX_AGE)

def get_current_user(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_session_token(token)
        return payload.get("user", "")
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión inválida o expirada",
            headers={"WWW-Authenticate": "Bearer"},
        )

def find_first_existing(paths: List[str]) -> str:
    for p in paths:
        if os.path.exists(p):
            return p
    return ""

def get_active_version_id() -> str:
    if os.path.exists(ACTIVE_VERSION_CONFIG):
        try:
            with open(ACTIVE_VERSION_CONFIG, "r") as f:
                config = json.load(f)
                return config.get("active_version_id", "legacy")
        except Exception:
            return "legacy"
    return "legacy"

def load_production_artifacts():
    try:
        version_id = get_active_version_id()

        if version_id == "legacy":
            model_path = os.path.join(MODEL_DIR, "production_pipeline.joblib")
            encoder_path = os.path.join(MODEL_DIR, "encoder_mappings.joblib")
            metrics_path = os.path.join(MODEL_DIR, "current_production_metrics.json")
            features_path = os.path.join(MODEL_DIR, "inference_features.joblib")
        else:
            model_path = os.path.join(MODEL_DIR, f"model_{version_id}.joblib")
            encoder_path = os.path.join(MODEL_DIR, f"encoders_{version_id}.joblib")
            metrics_path = os.path.join(MODEL_DIR, f"metrics_{version_id}.json")
            features_path = os.path.join(MODEL_DIR, f"features_{version_id}.joblib")

        model = joblib.load(model_path)
        encoders = joblib.load(encoder_path)
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        features = joblib.load(features_path)
        return model, encoders, metrics, features
    except Exception:
        return None, None, None, None

def load_consumables(source: Union[str, bytes, None] = None) -> set:
    try:
        if source is None:
            path = find_first_existing(CONSUMABLES_CANDIDATES)
            if not path:
                return set()
            df = pd.read_excel(path, sheet_name=0, header=None)
        elif isinstance(source, bytes):
            df = pd.read_excel(io.BytesIO(source), sheet_name=0, header=None)
        else:
            df = pd.read_excel(source, sheet_name=0, header=None)
        items = df[0].astype(str).str.strip().str.upper().unique()
        return set(items)
    except Exception:
        return set()

def preprocess_raw_sheets(
    excel_file: Union[str, bytes], consumables: Union[set, None] = None
) -> pd.DataFrame:
    try:
        if isinstance(excel_file, bytes):
            excel_file = io.BytesIO(excel_file)
        xls = pd.ExcelFile(excel_file)
    except Exception as e:
        raise ValueError(f"Formato de archivo Excel inválido: {str(e)}")

    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in xls.sheet_names]
    if missing_sheets:
        raise ValueError(f"Hojas de Excel requeridas faltantes: {', '.join(missing_sheets)}")

    teams = pd.read_excel(xls, sheet_name="Equipos")
    orders = pd.read_excel(xls, sheet_name="Ordenes de trabajo")
    repairs = pd.read_excel(xls, sheet_name="Refacciones")

    missing_cols_report = []
    for sheet_name, required_cols in EXPECTED_COLUMNS.items():
        df_map = {"Equipos": teams, "Ordenes de trabajo": orders, "Refacciones": repairs}
        df_local = df_map[sheet_name]
        missing = [c for c in required_cols if c not in df_local.columns]
        if missing:
            missing_cols_report.append(f"Hoja '{sheet_name}' columnas faltantes: {', '.join(missing)}")
    if missing_cols_report:
        raise ValueError("; ".join(missing_cols_report))

    teams["EQUIPO"] = teams["EQUIPO"].astype(str).str.strip()
    orders["Order"] = orders["Order"].astype(str).str.strip()
    orders["Equipment"] = orders["Equipment"].astype(str).str.strip()
    repairs["Order"] = repairs["Order"].astype(str).str.strip()

    orders["Created On"] = pd.to_datetime(orders["Created On"], errors="coerce")
    repairs["Posting Date"] = pd.to_datetime(repairs["Posting Date"], errors="coerce")

    base = orders.merge(repairs, on="Order", how="inner", suffixes=("_order", "_part"))
    base = base.merge(teams, left_on="Equipment", right_on="EQUIPO", how="left")

    base = base.dropna(subset=["Plant", "Material", "Posting Date", "Quantity in UnE"])
    base = base[base["Quantity in UnE"] >= 0]
    base = base[base["Description_part"].astype(str).str.strip() != ""]

    if consumables:
        mask = ~base["Description_part"].astype(str).str.strip().str.upper().isin(consumables)
        base = base[mask]

    base = base.rename(columns={
        "Plant": "plant",
        "Material": "material",
        "Description_part": "spare_part_name",
    })

    return base

def build_snapshot(master_df: pd.DataFrame, ref_date: pd.Timestamp) -> pd.DataFrame:
    past = master_df[master_df["Posting Date"] < ref_date]
    future = master_df[
        (master_df["Posting Date"] >= ref_date)
        & (master_df["Posting Date"] < ref_date + pd.Timedelta(days=30))
    ]

    if past.empty:
        return pd.DataFrame()

    combos = past[["plant", "material", "spare_part_name"]].drop_duplicates()

    past_90 = past[past["Posting Date"] >= ref_date - pd.Timedelta(days=90)]
    feat_90 = past_90.groupby(["plant", "material"]).agg(
        qty_last_90d=("Quantity in UnE", "sum"),
        orders_last_90d=("Order", "nunique"),
    ).reset_index()

    past_180 = past[past["Posting Date"] >= ref_date - pd.Timedelta(days=180)]
    feat_180 = past_180.groupby(["plant", "material"]).agg(
        qty_last_180d=("Quantity in UnE", "sum"),
        orders_last_180d=("Order", "nunique"),
    ).reset_index()

    last_use = past.groupby(["plant", "material"])["Posting Date"].max().reset_index()
    last_use["days_since_last_used"] = (ref_date - last_use["Posting Date"]).dt.days
    last_use = last_use.drop(columns=["Posting Date"])

    target = future.groupby(["plant", "material"]).agg(
        qty_needed_next_30d=("Quantity in UnE", "sum")
    ).reset_index()

    snap = combos.merge(feat_90, on=["plant", "material"], how="left")
    snap = snap.merge(feat_180, on=["plant", "material"], how="left")
    snap = snap.merge(last_use, on=["plant", "material"], how="left")
    snap = snap.merge(target, on=["plant", "material"], how="left")

    snap = snap.fillna(0)
    snap["reference_month"] = ref_date.month
    snap["part_never_used"] = (snap["days_since_last_used"] == 0).astype(int)
    snap["reference_date"] = ref_date

    return snap

def build_latest_inference_features(master_df: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty or "Posting Date" not in master_df.columns:
        return pd.DataFrame()

    ref_date = master_df["Posting Date"].max()
    snap = build_snapshot(master_df, ref_date)
    if snap.empty:
        return snap

    inference_cols = [
        "plant",
        "material",
        "spare_part_name",
        "qty_last_90d",
        "orders_last_90d",
        "qty_last_180d",
        "orders_last_180d",
        "days_since_last_used",
        "reference_month",
        "part_never_used",
    ]
    return snap[inference_cols].copy()

def create_training_snapshots(master_df: pd.DataFrame) -> pd.DataFrame:
    min_date = master_df["Posting Date"].min() + pd.DateOffset(months=6)
    max_date = master_df["Posting Date"].max() - pd.Timedelta(days=30)

    if min_date >= max_date:
        ref_dates = [max_date]
    else:
        ref_dates = pd.date_range(start=min_date, end=max_date, freq="MS")

    snapshots = []
    for ref_date in ref_dates:
        snap = build_snapshot(master_df, ref_date)
        if not snap.empty:
            snapshots.append(snap)

    if not snapshots:
        raise ValueError("No se pudieron generar snapshots válidos del dataset.")

    return pd.concat(snapshots, ignore_index=True)

def apply_target_encoding(train_df, val_df, test_df, target_col):
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

@app.on_event("startup")
def startup_event():
    os.makedirs(MODEL_DIR, exist_ok=True)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/login")
def login(payload: LoginRequest, response: Response):
    if not AUTH_USERNAME or not AUTH_PASSWORD_HASH:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La autenticación no está configurada en el servidor.",
        )

    if payload.username != AUTH_USERNAME or not verify_password(
        payload.password, AUTH_PASSWORD_HASH_DECODED
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña inválidos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_session_token(AUTH_USERNAME)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=SAMESITE,
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"message": "Sesión iniciada correctamente"}

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=SAMESITE,
    )
    return {"message": "Sesión cerrada"}

@app.get("/api/models/requirements", dependencies=[Depends(get_current_user)])
def get_training_requirements():
    return {
        "sheets": REQUIRED_SHEETS,
        "columns": EXPECTED_COLUMNS,
    }

@app.get("/api/predictions", dependencies=[Depends(get_current_user)])
def get_predictions():
    model, encoders, _, features = load_production_artifacts()

    if model is None or encoders is None or features is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay modelo existente",
        )

    try:
        snap = features.copy()

        if snap.empty:
            return []

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

        result = snap[snap["predicted_quantity"] > 0][
            ["plant", "material", "spare_part_name", "predicted_quantity"]
        ].to_dict(orient="records")

        if not result:
            snap = snap.sort_values("predicted_quantity", ascending=False).head(50)
            result = snap[
                ["plant", "material", "spare_part_name", "predicted_quantity"]
            ].to_dict(orient="records")

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"La predicción falló: {str(e)}",
        )

@app.post("/api/models/train", status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_user)])
async def train_new_model(
    file: UploadFile = File(...),
    consumables: UploadFile = File(None),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato inválido. Solo se aceptan libros de Excel (.xlsx / .xls).",
        )

    file_content = await file.read()

    consumables_set = set()
    if consumables is not None:
        consumables_content = await consumables.read()
        consumables_set = load_consumables(consumables_content)

    try:
        master = preprocess_raw_sheets(file_content, consumables=consumables_set)
    except ValueError as ve:
        error_msg = str(ve)
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
            detail={"message": f"El preprocesamiento falló: {str(e)}", "missing_columns": []},
        )

    try:
        model_df = create_training_snapshots(master)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(ve), "missing_columns": []},
        )

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

    _, _, current_metrics, _ = load_production_artifacts()
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

    inference_features = build_latest_inference_features(master)

    CANDIDATE_REGISTRY[run_id] = {
        "model": candidate_model,
        "encoders": encoders,
        "metrics": new_metrics,
        "features": inference_features,
    }

    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{run_id}.joblib")
        joblib.dump({
            "model": candidate_model,
            "encoders": encoders,
            "metrics": new_metrics,
            "features": inference_features,
        }, candidate_bundle_path)
    except Exception:
        pass

    return {
        "run_id": run_id,
        "message": "Ingesta de datos exitosa. Pipeline candidato evaluado.",
        "current_model": current_metrics,
        "new_model": new_metrics,
    }

@app.post("/api/models/confirm", dependencies=[Depends(get_current_user)])
def confirm_model_promotion(payload: ConfirmModelRequest):
    action = payload.use_new_model.strip().lower()

    if action == "n":
        CANDIDATE_REGISTRY.pop(payload.run_id, None)
        candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
        if os.path.exists(candidate_bundle_path):
            os.remove(candidate_bundle_path)
        return {"message": "Candidato descartado. Artefactos de producción existentes retenidos."}

    if action == "y":
        candidate = CANDIDATE_REGISTRY.get(payload.run_id)
        if not candidate:
            candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
            if os.path.exists(candidate_bundle_path):
                try:
                    bundle = joblib.load(candidate_bundle_path)
                    candidate = {
                        "model": bundle["model"],
                        "encoders": bundle["encoders"],
                        "metrics": bundle["metrics"],
                        "features": bundle.get("features"),
                    }
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="ID de ejecución no encontrado o ya procesado.",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ID de ejecución no encontrado o ya procesado.",
                )

        try:
            os.makedirs(MODEL_DIR, exist_ok=True)

            versioned_model_path = os.path.join(MODEL_DIR, f"model_{payload.run_id}.joblib")
            versioned_encoder_path = os.path.join(MODEL_DIR, f"encoders_{payload.run_id}.joblib")
            versioned_metrics_path = os.path.join(MODEL_DIR, f"metrics_{payload.run_id}.json")
            versioned_features_path = os.path.join(MODEL_DIR, f"features_{payload.run_id}.joblib")

            joblib.dump(candidate["model"], versioned_model_path)
            joblib.dump(candidate["encoders"], versioned_encoder_path)
            with open(versioned_metrics_path, "w") as f:
                json.dump(candidate["metrics"], f, indent=4)
            joblib.dump(candidate.get("features"), versioned_features_path)

            with open(ACTIVE_VERSION_CONFIG, "w") as f:
                json.dump({"active_version_id": payload.run_id}, f, indent=4)

            CANDIDATE_REGISTRY.pop(payload.run_id, None)
            candidate_bundle_path = os.path.join(MODEL_DIR, f"candidate_{payload.run_id}.joblib")
            if os.path.exists(candidate_bundle_path):
                os.remove(candidate_bundle_path)
            return {
                "message": f"¡Éxito! El candidato {payload.run_id} ha sido promovido a producción."
            }

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al persistir modelos de producción: {str(e)}",
            )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Valor use_new_model inválido. Se esperaba 'y' o 'n'.",
    )

@app.get("/api/models/current", dependencies=[Depends(get_current_user)])
def get_current_model():
    version_id = get_active_version_id()
    if not version_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró modelo activo.",
        )

    metrics_path = os.path.join(MODEL_DIR, f"metrics_{version_id}.json")
    if not os.path.exists(metrics_path):
        return {
            "version_id": version_id,
            "message": "Métricas no encontradas para el modelo activo.",
        }

    with open(metrics_path, "r") as f:
        metrics = json.load(f)

    return {
        "version_id": version_id,
        "timestamp": metrics.get("timestamp"),
        "train_mae": metrics.get("train_mae"),
        "val_mae": metrics.get("val_mae"),
        "train_r2": metrics.get("train_r2"),
        "val_r2": metrics.get("val_r2"),
        "train_rmse": metrics.get("train_rmse"),
        "val_rmse": metrics.get("val_rmse"),
    }

@app.get("/api/models/history", dependencies=[Depends(get_current_user)])
def get_model_history():
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

@app.post("/api/models/rollback", dependencies=[Depends(get_current_user)])
def rollback_model(payload: RollbackModelRequest):
    target_metrics_path = os.path.join(MODEL_DIR, f"metrics_{payload.version_id}.json")

    if not os.path.exists(target_metrics_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La versión solicitada no existe.",
        )

    try:
        with open(ACTIVE_VERSION_CONFIG, "w") as f:
            json.dump({"active_version_id": payload.version_id}, f, indent=4)

        return {
            "message": f"Se activó exitosamente el motor de producción a la versión: {payload.version_id}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar metadata durante activación: {str(e)}",
        )
