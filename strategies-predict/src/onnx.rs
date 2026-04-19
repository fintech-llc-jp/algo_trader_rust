use ndarray::{Array1, Axis};
use ort::session::Session;
use ort::value::Value;
use std::sync::Mutex;
use thiserror::Error;

use engine_core::{StrategyVote, VoteSide};
use strategy_api::MarketSnapshot;

use crate::schema::FeatureSchema;
use crate::PredictStrategyConfig;

#[derive(Debug, Error)]
pub enum PredictError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("onnx: {0}")]
    Onnx(String),
    #[error("schema: {0}")]
    Schema(String),
    #[error("inference: {0}")]
    Inference(String),
}

pub struct OnnxPredictor {
    session: Mutex<Session>,
    schema: FeatureSchema,
    input_name: String,
    output_name: String,
}

impl OnnxPredictor {
    pub fn from_files(cfg: &PredictStrategyConfig) -> Result<Self, PredictError> {
        let schema = FeatureSchema::load(&cfg.schema_path)?;
        let session = Session::builder()
            .map_err(|e| PredictError::Onnx(e.to_string()))?
            .commit_from_file(&cfg.model_path)
            .map_err(|e| PredictError::Onnx(e.to_string()))?;
        Ok(Self {
            session: Mutex::new(session),
            schema,
            input_name: cfg.input_name.clone(),
            output_name: cfg.output_name.clone(),
        })
    }

    fn build_features(&self, snapshot: &MarketSnapshot) -> Result<Array1<f32>, PredictError> {
        let n = self.schema.feature_dim;
        let mut v = vec![0.0f32; n];
        if let Some(mid) = snapshot.book.mid() {
            v[0] = mid as f32;
        }
        if n > 1 {
            if let Some(sp) = snapshot.book.spread() {
                v[1] = sp as f32;
            }
        }
        let mut i = 2usize;
        for b in snapshot.bars.iter().rev() {
            if i >= n {
                break;
            }
            v[i] = b.close as f32;
            i += 1;
        }
        Array1::from_shape_vec(n, v).map_err(|e| PredictError::Schema(e.to_string()))
    }

    fn run(&self, features: &Array1<f32>) -> Result<Vec<f32>, PredictError> {
        let input_f = features.clone().insert_axis(Axis(0));
        let value =
            Value::from_array(input_f).map_err(|e| PredictError::Inference(e.to_string()))?;
        let mut session = self
            .session
            .lock()
            .map_err(|e| PredictError::Inference(e.to_string()))?;
        let mut out = session
            .run(ort::inputs![self.input_name.as_str() => value])
            .map_err(|e| PredictError::Inference(e.to_string()))?;
        let tensor = out
            .remove(&self.output_name)
            .ok_or_else(|| PredictError::Inference("missing output tensor".into()))?;
        let (_shape, data) = tensor
            .try_extract_tensor::<f32>()
            .map_err(|e| PredictError::Inference(e.to_string()))?;
        Ok(data.to_vec())
    }

    pub fn predict_vote(
        &self,
        snapshot: &MarketSnapshot,
        three_class: bool,
    ) -> Result<StrategyVote, PredictError> {
        let feats = self.build_features(snapshot)?;
        let out = self.run(&feats)?;
        let (side, strength) = if three_class && out.len() >= 3 {
            let mut best = 0usize;
            for i in 1..out.len() {
                if out[i] > out[best] {
                    best = i;
                }
            }
            let s = out[best].clamp(0.0, 1.0) as f64;
            let side = match best {
                0 => VoteSide::Sell,
                2 => VoteSide::Buy,
                _ => VoteSide::Hold,
            };
            (side, s)
        } else if !out.is_empty() {
            let v = out[0].tanh();
            let side = if v > 0.1 {
                VoteSide::Buy
            } else if v < -0.1 {
                VoteSide::Sell
            } else {
                VoteSide::Hold
            };
            (side, v.abs().min(1.0) as f64)
        } else {
            return Ok(StrategyVote::abstain("price_prediction"));
        };
        Ok(StrategyVote {
            strategy_id: "price_prediction".to_string(),
            side,
            strength,
        })
    }
}
