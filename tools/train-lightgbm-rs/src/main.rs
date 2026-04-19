use anyhow::{anyhow, bail, Context, Result};
use clap::{Parser, Subcommand};
use lightgbm3::{Booster, Dataset};
use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

#[derive(Debug, Parser)]
#[command(author, version, about = "Rust LightGBM training PoC CLI")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Run deterministic smoke training with synthetic data.
    Smoke {
        #[arg(long, default_value_t = 512)]
        rows: usize,
        #[arg(long, default_value_t = 8)]
        features: usize,
        #[arg(long, default_value_t = 42)]
        seed: u64,
        #[arg(long, default_value = "artifacts/lightgbm-rs-smoke")]
        out_dir: PathBuf,
    },
    /// Train from CSV file and emit model/metrics artifacts.
    Train {
        #[arg(long)]
        csv: PathBuf,
        #[arg(long, default_value = "label")]
        label_col: String,
        #[arg(long, default_value_t = 42)]
        seed: u64,
        #[arg(long, default_value_t = 0.8)]
        train_ratio: f64,
        #[arg(long, default_value = "ml_bridge/lightgbm_baseline_params.json")]
        params_json: PathBuf,
        #[arg(long, default_value = "artifacts/lightgbm-rs-train")]
        out_dir: PathBuf,
        #[arg(long)]
        schema_path: Option<PathBuf>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FeatureSchema {
    version: u32,
    feature_dim: usize,
    columns: Vec<String>,
}

#[derive(Debug, Clone)]
struct DataSet {
    rows: Vec<Vec<f64>>,
    labels: Vec<f32>,
    columns: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
struct Metrics {
    auc: f64,
    logloss: f64,
}

#[derive(Debug, Clone, Serialize)]
struct RunSummary {
    runtime: String,
    seed: u64,
    params: Value,
    train_rows: usize,
    valid_rows: usize,
    feature_dim: usize,
    train_metrics: Metrics,
    valid_metrics: Metrics,
    elapsed_ms: u128,
    dataset_sha256: String,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Smoke {
            rows,
            features,
            seed,
            out_dir,
        } => run_smoke(rows, features, seed, &out_dir),
        Commands::Train {
            csv,
            label_col,
            seed,
            train_ratio,
            params_json,
            out_dir,
            schema_path,
        } => run_train(
            &csv,
            &label_col,
            seed,
            train_ratio,
            &params_json,
            &out_dir,
            schema_path.as_deref(),
        ),
    }
}

fn run_smoke(rows: usize, features: usize, seed: u64, out_dir: &Path) -> Result<()> {
    let mut rng = StdRng::seed_from_u64(seed);
    let mut x = Vec::with_capacity(rows);
    let mut y = Vec::with_capacity(rows);
    for _ in 0..rows {
        let row = (0..features)
            .map(|_| rng.gen_range(-1.0..1.0))
            .collect::<Vec<f64>>();
        // Linear boundary with controlled noise.
        let score = row.iter().enumerate().fold(0.0, |acc, (i, v)| {
            let weight = 1.0 + (i as f64 * 0.1);
            acc + (weight * v)
        });
        let noisy = score + rng.gen_range(-0.25..0.25);
        let label = if noisy > 0.0 { 1.0 } else { 0.0 };
        x.push(row);
        y.push(label);
    }

    let columns = (0..features)
        .map(|i| format!("feature_{i}"))
        .collect::<Vec<_>>();
    let dataset = DataSet {
        rows: x,
        labels: y,
        columns,
    };
    let params = baseline_params();
    train_and_emit(dataset, seed, 0.8, params, out_dir)
}

fn run_train(
    csv_path: &Path,
    label_col: &str,
    seed: u64,
    train_ratio: f64,
    params_json: &Path,
    out_dir: &Path,
    schema_path: Option<&Path>,
) -> Result<()> {
    if !(0.0..1.0).contains(&train_ratio) {
        bail!("train_ratio must be in (0, 1), got {train_ratio}");
    }
    let mut data = read_csv_dataset(csv_path, label_col)?;
    if let Some(schema_path) = schema_path {
        let expected = read_schema(schema_path)?;
        if expected.columns != data.columns {
            bail!("schema columns mismatch between CSV and provided schema");
        }
    }
    // Make sure we have enough rows after split.
    if data.rows.len() < 10 {
        bail!(
            "need at least 10 rows for training, got {}",
            data.rows.len()
        );
    }
    // Keep deterministic shuffle tied to seed.
    shuffle_dataset(&mut data, seed);
    let params = load_params(params_json)?;
    train_and_emit(data, seed, train_ratio, params, out_dir)
}

fn train_and_emit(
    data: DataSet,
    seed: u64,
    train_ratio: f64,
    params: Value,
    out_dir: &Path,
) -> Result<()> {
    fs::create_dir_all(out_dir)
        .with_context(|| format!("create output dir {}", out_dir.display()))?;
    let start = Instant::now();
    let dataset_hash = hash_dataset(&data);

    let split_idx = ((data.rows.len() as f64) * train_ratio).floor() as usize;
    let split_idx = split_idx.clamp(1, data.rows.len() - 1);

    let (train_x, valid_x) = data.rows.split_at(split_idx);
    let (train_y, valid_y) = data.labels.split_at(split_idx);
    let n_features = data.columns.len() as i32;

    let train_flat = flatten_2d(train_x);
    let valid_flat = flatten_2d(valid_x);

    let mut train_ds = Dataset::from_slice(&train_flat, train_y, n_features, true)
        .map_err(|e| anyhow!("build train dataset: {e}"))?;
    train_ds
        .set_feature_names(&data.columns)
        .map_err(|e| anyhow!("set feature names: {e}"))?;
    let valid_ds =
        Dataset::from_slice_with_reference(&valid_flat, valid_y, n_features, true, Some(&train_ds))
            .map_err(|e| anyhow!("build valid dataset: {e}"))?;

    let booster =
        Booster::train_with_valid(train_ds, Some(valid_ds), &params).map_err(|e| anyhow!("{e}"))?;

    let train_pred = booster
        .predict(&train_flat, n_features, true)
        .map_err(|e| anyhow!("{e}"))?;
    let valid_pred = booster
        .predict(&valid_flat, n_features, true)
        .map_err(|e| anyhow!("{e}"))?;

    let train_metrics = compute_metrics(train_y, &train_pred)?;
    let valid_metrics = compute_metrics(valid_y, &valid_pred)?;
    let elapsed_ms = start.elapsed().as_millis();

    let model_path = out_dir.join("model.lgb");
    let model_path_str = model_path
        .to_str()
        .ok_or_else(|| anyhow!("model path must be valid utf-8"))?;
    booster
        .save_file(model_path_str)
        .map_err(|e| anyhow!("save model: {e}"))?;

    let schema = FeatureSchema {
        version: 1,
        feature_dim: data.columns.len(),
        columns: data.columns.clone(),
    };
    write_json_pretty(out_dir.join("feature_schema.json"), &schema)?;

    let summary = RunSummary {
        runtime: "rust-lightgbm3".to_string(),
        seed,
        params: params.clone(),
        train_rows: train_x.len(),
        valid_rows: valid_x.len(),
        feature_dim: data.columns.len(),
        train_metrics,
        valid_metrics,
        elapsed_ms,
        dataset_sha256: dataset_hash,
    };
    write_json_pretty(out_dir.join("metrics.json"), &summary)?;
    write_json_pretty(
        out_dir.join("training_manifest.json"),
        &json!({
            "runtime": "rust",
            "tool": "train-lightgbm-rs",
            "seed": seed,
            "parameters": params,
            "dataset_sha256": summary.dataset_sha256,
            "model_file": "model.lgb",
            "schema_file": "feature_schema.json",
            "metrics_file": "metrics.json",
        }),
    )?;

    println!(
        "training finished: valid_auc={:.6}, valid_logloss={:.6}, elapsed_ms={}",
        summary.valid_metrics.auc, summary.valid_metrics.logloss, summary.elapsed_ms
    );
    Ok(())
}

fn read_csv_dataset(csv_path: &Path, label_col: &str) -> Result<DataSet> {
    let mut rdr =
        csv::Reader::from_path(csv_path).with_context(|| format!("open {}", csv_path.display()))?;
    let headers = rdr
        .headers()
        .with_context(|| "read CSV header")?
        .iter()
        .map(|s| s.to_string())
        .collect::<Vec<_>>();
    let label_idx = headers
        .iter()
        .position(|h| h == label_col)
        .ok_or_else(|| anyhow!("label column '{label_col}' not found"))?;
    let feature_cols = headers
        .iter()
        .enumerate()
        .filter_map(|(i, h)| {
            if i == label_idx {
                None
            } else {
                Some(h.clone())
            }
        })
        .collect::<Vec<_>>();

    let mut rows = Vec::new();
    let mut labels = Vec::new();
    for rec in rdr.records() {
        let rec = rec?;
        let mut row = Vec::with_capacity(feature_cols.len());
        let mut label = None;
        for (idx, raw) in rec.iter().enumerate() {
            if idx == label_idx {
                label = Some(
                    raw.parse::<f32>()
                        .with_context(|| format!("parse label '{raw}'"))?,
                );
            } else {
                row.push(
                    raw.parse::<f64>()
                        .with_context(|| format!("parse feature '{raw}'"))?,
                );
            }
        }
        rows.push(row);
        labels.push(label.ok_or_else(|| anyhow!("missing label value"))?);
    }
    Ok(DataSet {
        rows,
        labels,
        columns: feature_cols,
    })
}

fn read_schema(path: &Path) -> Result<FeatureSchema> {
    let raw = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let schema = serde_json::from_str::<FeatureSchema>(&raw)
        .with_context(|| format!("parse schema {}", path.display()))?;
    Ok(schema)
}

fn baseline_params() -> Value {
    json!({
        "objective": "binary",
        "metric": ["auc", "binary_logloss"],
        "num_iterations": 80,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "min_data_in_leaf": 20,
        "seed": 42,
        "verbosity": -1
    })
}

fn load_params(path: &Path) -> Result<Value> {
    let raw = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let params = serde_json::from_str::<Value>(&raw)
        .with_context(|| format!("parse params json {}", path.display()))?;
    Ok(params)
}

fn shuffle_dataset(data: &mut DataSet, seed: u64) {
    let mut idx = (0..data.rows.len()).collect::<Vec<_>>();
    let mut rng = StdRng::seed_from_u64(seed);
    idx.shuffle(&mut rng);

    let mut shuffled_rows = Vec::with_capacity(data.rows.len());
    let mut shuffled_labels = Vec::with_capacity(data.labels.len());
    for i in idx {
        shuffled_rows.push(data.rows[i].clone());
        shuffled_labels.push(data.labels[i]);
    }
    data.rows = shuffled_rows;
    data.labels = shuffled_labels;
}

fn flatten_2d(rows: &[Vec<f64>]) -> Vec<f64> {
    rows.iter()
        .flat_map(|r| r.iter().copied())
        .collect::<Vec<_>>()
}

fn compute_metrics(labels: &[f32], preds: &[f64]) -> Result<Metrics> {
    if labels.len() != preds.len() {
        bail!(
            "labels/preds length mismatch: {} != {}",
            labels.len(),
            preds.len()
        );
    }
    let auc = binary_auc(labels, preds)?;
    let logloss = binary_logloss(labels, preds)?;
    Ok(Metrics { auc, logloss })
}

fn binary_logloss(labels: &[f32], preds: &[f64]) -> Result<f64> {
    if labels.is_empty() {
        bail!("cannot compute logloss for empty labels");
    }
    let mut sum = 0.0f64;
    for (y, p) in labels.iter().zip(preds.iter()) {
        let p = p.clamp(1e-7, 1.0 - 1e-7);
        let y = *y as f64;
        sum += -(y * p.ln() + (1.0 - y) * (1.0 - p).ln());
    }
    Ok(sum / labels.len() as f64)
}

fn binary_auc(labels: &[f32], preds: &[f64]) -> Result<f64> {
    if labels.is_empty() {
        bail!("cannot compute auc for empty labels");
    }
    let mut pairs = labels
        .iter()
        .zip(preds.iter())
        .map(|(y, p)| (*p, *y))
        .collect::<Vec<_>>();
    pairs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut rank_sum_pos = 0.0f64;
    let mut pos = 0.0f64;
    let mut neg = 0.0f64;
    for (i, (_, y)) in pairs.iter().enumerate() {
        if *y >= 0.5 {
            pos += 1.0;
            rank_sum_pos += (i + 1) as f64;
        } else {
            neg += 1.0;
        }
    }
    if pos == 0.0 || neg == 0.0 {
        bail!("auc requires both positive and negative labels");
    }
    let auc = (rank_sum_pos - (pos * (pos + 1.0) / 2.0)) / (pos * neg);
    Ok(auc)
}

fn hash_dataset(data: &DataSet) -> String {
    let mut hasher = Sha256::new();
    for name in &data.columns {
        hasher.update(name.as_bytes());
        hasher.update([0u8]);
    }
    for (row, y) in data.rows.iter().zip(data.labels.iter()) {
        for x in row {
            hasher.update(x.to_le_bytes());
        }
        hasher.update(y.to_le_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn write_json_pretty(path: PathBuf, value: &impl Serialize) -> Result<()> {
    let raw = serde_json::to_string_pretty(value)?;
    fs::write(&path, raw).with_context(|| format!("write {}", path.display()))
}
