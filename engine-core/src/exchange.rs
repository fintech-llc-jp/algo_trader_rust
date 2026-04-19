use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Exchange-facing errors.
#[derive(Debug, Error)]
pub enum ExchangeError {
    #[error("http: {0}")]
    Http(String),
    #[error("bad response: {0}")]
    BadResponse(String),
    #[error("serialization: {0}")]
    Serde(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoginRequest {
    pub username: String,
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoginResponse {
    pub token: String,
    #[serde(default)]
    pub username: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewOrderRequest {
    pub symbol: String,
    pub side: String,
    #[serde(rename = "ordType")]
    pub ord_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub price: Option<f64>,
    pub quantity: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tif: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub open: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub close: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NewOrderResponse {
    #[serde(rename = "cl_ord_id")]
    pub cl_ord_id: Option<String>,
    pub symbol: Option<String>,
    pub side: Option<String>,
    pub status: Option<String>,
    #[serde(rename = "order_px")]
    pub order_px: Option<f64>,
    #[serde(rename = "order_qty")]
    pub order_qty: Option<f64>,
    #[serde(rename = "filled_qty")]
    pub filled_qty: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OrderBookLevel {
    pub price: Option<f64>,
    pub quantity: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OrderBook {
    pub symbol: Option<String>,
    pub bids: Vec<OrderBookLevel>,
    pub asks: Vec<OrderBookLevel>,
    #[serde(rename = "asOf")]
    pub as_of: Option<i64>,
}

impl OrderBook {
    pub fn best_bid(&self) -> Option<f64> {
        self.bids.first().and_then(|l| l.price)
    }

    pub fn best_ask(&self) -> Option<f64> {
        self.asks.first().and_then(|l| l.price)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CancelOrderRequest {
    #[serde(rename = "clOrdID")]
    pub cl_ord_id: String,
    pub symbol: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CancelOrderResponse {
    #[serde(rename = "clOrdID")]
    pub cl_ord_id: Option<String>,
    #[serde(rename = "ordStatus")]
    pub ord_status: Option<String>,
}

#[async_trait]
pub trait Exchange: Send + Sync {
    async fn login_or_refresh(&self) -> Result<(), ExchangeError>;

    async fn place_order(&self, req: NewOrderRequest) -> Result<NewOrderResponse, ExchangeError>;

    async fn cancel_order(
        &self,
        req: CancelOrderRequest,
    ) -> Result<CancelOrderResponse, ExchangeError>;

    async fn get_order_book(&self, symbol: &str) -> Result<OrderBook, ExchangeError>;
}
