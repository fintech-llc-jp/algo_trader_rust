//! ONNX price-direction helper (uses `ort` runtime).

mod onnx;
mod schema;

pub use onnx::{OnnxPredictor, PredictError};
pub use schema::FeatureSchema;

use async_trait::async_trait;
use engine_core::StrategyVote;
use onnx::OnnxPredictor as OnnxInner;
use strategy_api::{MarketSnapshot, Strategy};

/// Configuration for [`PricePredictionStrategy`].
#[derive(Debug, Clone)]
pub struct PredictStrategyConfig {
    pub model_path: std::path::PathBuf,
    pub schema_path: std::path::PathBuf,
    pub input_name: String,
    pub output_name: String,
    /// If true, first output dimension is treated as logits \[down, neutral, up\].
    pub three_class: bool,
}

pub struct PricePredictionStrategy {
    config: PredictStrategyConfig,
    predictor: Option<OnnxInner>,
}

impl PricePredictionStrategy {
    pub fn new(config: PredictStrategyConfig) -> Self {
        let predictor = match OnnxInner::from_files(&config) {
            Ok(p) => Some(p),
            Err(e) => {
                tracing::warn!(error = %e, "ONNX predictor not loaded; strategy will abstain");
                None
            }
        };
        Self { config, predictor }
    }
}

#[async_trait]
impl Strategy for PricePredictionStrategy {
    fn id(&self) -> &'static str {
        "price_prediction"
    }

    async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote {
        let Some(ref p) = self.predictor else {
            return StrategyVote::abstain(self.id());
        };
        match p.predict_vote(snapshot, self.config.three_class) {
            Ok(v) => v,
            Err(e) => {
                tracing::debug!(error = %e, "prediction failed; abstain");
                StrategyVote::abstain(self.id())
            }
        }
    }
}
