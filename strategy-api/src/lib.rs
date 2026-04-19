//! Strategy plugin API: market snapshot + [`Strategy`] trait.

mod snapshot;
mod strategy;

pub use snapshot::{Bar, MarketSnapshot, OrderBookTop};
pub use strategy::Strategy;
