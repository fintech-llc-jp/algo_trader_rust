use async_trait::async_trait;
use engine_core::{
    CancelOrderRequest, CancelOrderResponse, Exchange, ExchangeError, LoginRequest, LoginResponse,
    NewOrderRequest, NewOrderResponse, OrderBook, PositionSummary,
};
use reqwest::Client;
use std::sync::RwLock;
use tracing::debug;

/// ExchSim REST client implementing [`Exchange`].
pub struct ExchSimAdapter {
    http: Client,
    base_url: String,
    username: Option<String>,
    password: Option<String>,
    token: RwLock<Option<String>>,
}

impl ExchSimAdapter {
    pub fn from_token(base_url: impl Into<String>, token: impl Into<String>) -> Self {
        Self {
            http: Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            username: None,
            password: None,
            token: RwLock::new(Some(token.into())),
        }
    }

    pub fn from_credentials(
        base_url: impl Into<String>,
        username: impl Into<String>,
        password: impl Into<String>,
    ) -> Self {
        Self {
            http: Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            username: Some(username.into()),
            password: Some(password.into()),
            token: RwLock::new(None),
        }
    }

    fn auth_headers(token: &str) -> reqwest::header::HeaderMap {
        let mut h = reqwest::header::HeaderMap::new();
        let v = format!("Bearer {token}").parse().expect("header value");
        h.insert(reqwest::header::AUTHORIZATION, v);
        h.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        h
    }

    async fn post_json<T: serde::de::DeserializeOwned>(
        &self,
        path: &str,
        body: &impl serde::Serialize,
        headers: reqwest::header::HeaderMap,
    ) -> Result<T, ExchangeError> {
        let url = format!("{}{}", self.base_url, path);
        let res = self
            .http
            .post(&url)
            .headers(headers)
            .json(body)
            .send()
            .await
            .map_err(|e| ExchangeError::Http(e.to_string()))?;
        if !res.status().is_success() {
            let txt = res.text().await.unwrap_or_default();
            return Err(ExchangeError::BadResponse(format!("{} {}", path, txt)));
        }
        res.json::<T>()
            .await
            .map_err(|e| ExchangeError::Http(e.to_string()))
    }

    async fn get_json<T: serde::de::DeserializeOwned>(
        &self,
        path: &str,
        headers: reqwest::header::HeaderMap,
    ) -> Result<T, ExchangeError> {
        let url = format!("{}{}", self.base_url, path);
        let res = self
            .http
            .get(&url)
            .headers(headers)
            .send()
            .await
            .map_err(|e| ExchangeError::Http(e.to_string()))?;
        if !res.status().is_success() {
            let txt = res.text().await.unwrap_or_default();
            return Err(ExchangeError::BadResponse(format!("{} {}", path, txt)));
        }
        res.json::<T>()
            .await
            .map_err(|e| ExchangeError::Http(e.to_string()))
    }
}

#[async_trait]
impl Exchange for ExchSimAdapter {
    async fn login_or_refresh(&self) -> Result<(), ExchangeError> {
        if self.token.read().unwrap().is_some() {
            return Ok(());
        }
        let (u, p) = match (&self.username, &self.password) {
            (Some(u), Some(p)) => (u.clone(), p.clone()),
            _ => {
                return Err(ExchangeError::BadResponse(
                    "missing username/password for login".into(),
                ))
            }
        };
        let login = LoginRequest {
            username: u,
            password: p,
        };
        let mut h = reqwest::header::HeaderMap::new();
        h.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        let res: LoginResponse = self.post_json("/api/auth/login", &login, h).await?;
        *self.token.write().unwrap() = Some(res.token);
        Ok(())
    }

    async fn place_order(&self, req: NewOrderRequest) -> Result<NewOrderResponse, ExchangeError> {
        self.login_or_refresh().await?;
        let token = self
            .token
            .read()
            .unwrap()
            .clone()
            .ok_or_else(|| ExchangeError::BadResponse("no token".into()))?;
        let headers = Self::auth_headers(&token);
        self.post_json("/api/orders/new", &req, headers).await
    }

    async fn cancel_order(
        &self,
        req: CancelOrderRequest,
    ) -> Result<CancelOrderResponse, ExchangeError> {
        self.login_or_refresh().await?;
        let token = self
            .token
            .read()
            .unwrap()
            .clone()
            .ok_or_else(|| ExchangeError::BadResponse("no token".into()))?;
        let headers = Self::auth_headers(&token);
        self.post_json("/api/orders/cancel", &req, headers).await
    }

    async fn get_order_book(&self, symbol: &str) -> Result<OrderBook, ExchangeError> {
        self.login_or_refresh().await?;
        let token = self
            .token
            .read()
            .unwrap()
            .clone()
            .ok_or_else(|| ExchangeError::BadResponse("no token".into()))?;
        let headers = Self::auth_headers(&token);
        let path = format!("/api/market/board/{symbol}?depth=2");
        debug!(%path, "fetch order book");
        self.get_json(&path, headers).await
    }

    async fn get_position_summary(&self) -> Result<PositionSummary, ExchangeError> {
        self.login_or_refresh().await?;
        let token = self
            .token
            .read()
            .unwrap()
            .clone()
            .ok_or_else(|| ExchangeError::BadResponse("no token".into()))?;
        let headers = Self::auth_headers(&token);
        self.get_json("/api/positions/summary", headers).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path, path_regex};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn login_and_fetch_board() {
        let srv = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/auth/login"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "token": "t0",
                "username": "u"
            })))
            .mount(&srv)
            .await;
        Mock::given(method("GET"))
            .and(path_regex(r"/api/market/board/BTCJPY"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "symbol": "BTCJPY",
                "bids": [{"price": 100.0, "quantity": 1.0}],
                "asks": [{"price": 101.0, "quantity": 1.0}],
                "asOf": 1
            })))
            .mount(&srv)
            .await;

        let a = ExchSimAdapter::from_credentials(srv.uri(), "u", "p");
        let ob = a.get_order_book("BTCJPY").await.unwrap();
        assert_eq!(ob.best_bid(), Some(100.0));
        assert_eq!(ob.best_ask(), Some(101.0));
    }

    #[tokio::test]
    async fn login_and_fetch_positions() {
        let srv = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/auth/login"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "token": "t0",
                "username": "u"
            })))
            .mount(&srv)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/positions/summary"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "positions": [{"symbol": "BTCJPY", "quantity": 0.02}]
            })))
            .mount(&srv)
            .await;

        let a = ExchSimAdapter::from_credentials(srv.uri(), "u", "p");
        let ps = a.get_position_summary().await.unwrap();
        assert_eq!(ps.quantity_for_symbol("BTCJPY"), 0.02);
    }
}
