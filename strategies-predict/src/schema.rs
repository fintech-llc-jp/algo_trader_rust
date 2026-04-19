use serde::{Deserialize, Serialize};
use std::path::Path;

use crate::PredictError;

/// Versioned feature contract between Python training and Rust inference.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeatureSchema {
    pub version: u32,
    pub feature_dim: usize,
    #[serde(default)]
    pub columns: Vec<String>,
}

impl FeatureSchema {
    pub fn load(path: impl AsRef<Path>) -> Result<Self, PredictError> {
        let raw = std::fs::read_to_string(path.as_ref())?;
        let s: FeatureSchema = serde_json::from_str(&raw)?;
        if s.feature_dim == 0 {
            return Err(PredictError::Schema("feature_dim must be > 0".into()));
        }
        Ok(s)
    }
}
