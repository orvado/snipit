use base64::Engine as _;
use rand::Rng;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::PathBuf;

pub const GOOGLE_AUTH_URL: &str = "https://accounts.google.com/o/oauth2/v2/auth";
pub const GOOGLE_TOKEN_URL: &str = "https://oauth2.googleapis.com/token";

const VERIFIER_ALPHABET: &[u8] =
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

pub fn make_code_verifier(n: usize) -> String {
    let mut rng = rand::thread_rng();
    (0..n)
        .map(|_| {
            let idx = rng.gen_range(0..VERIFIER_ALPHABET.len());
            VERIFIER_ALPHABET[idx] as char
        })
        .collect()
}

pub fn make_code_challenge(verifier: &str) -> String {
    let digest = Sha256::digest(verifier.as_bytes());
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest)
}

pub fn build_authorize_url(
    client_id: &str,
    redirect_uri: &str,
    state: &str,
    verifier: &str,
    scopes: &[&str],
) -> String {
    let challenge = make_code_challenge(verifier);
    let params = [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("scope", &scopes.join(" ")),
        ("state", state),
        ("code_challenge", &challenge),
        ("code_challenge_method", "S256"),
        ("access_type", "offline"),
        ("prompt", "consent"),
    ];
    let query = params
        .iter()
        .map(|(k, v)| format!("{}={}", urlencoding(k), urlencoding(v)))
        .collect::<Vec<_>>()
        .join("&");
    format!("{GOOGLE_AUTH_URL}?{query}")
}

fn urlencoding(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenResponse {
    pub access_token: Option<String>,
    pub refresh_token: Option<String>,
    pub expires_in: Option<u64>,
    pub token_type: Option<String>,
    pub scope: Option<String>,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

pub fn parse_redirect(query_string: &str, expected_state: &str) -> Result<String, String> {
    let params: HashMap<String, String> =
        url::form_urlencoded::parse(query_string.as_bytes()).into_owned().collect();
    let state = params.get("state").map(|s| s.as_str()).unwrap_or("");
    if state != expected_state {
        return Err("OAuth state mismatch — aborting connect".to_string());
    }
    if let Some(err) = params.get("error") {
        return Err(format!("authorization failed: {err}"));
    }
    let code = params.get("code").map(|s| s.as_str()).unwrap_or("");
    if code.is_empty() {
        return Err("no authorization code in redirect".to_string());
    }
    Ok(code.to_string())
}

pub fn exchange_code_blocking(
    code: &str,
    verifier: &str,
    redirect_uri: &str,
    client_id: &str,
    client_secret: &str,
) -> Result<TokenResponse, String> {
    let mut form = HashMap::new();
    form.insert("grant_type", "authorization_code");
    form.insert("code", code);
    form.insert("redirect_uri", redirect_uri);
    form.insert("client_id", client_id);
    form.insert("code_verifier", verifier);
    let secret = client_secret.to_string();
    if !client_secret.is_empty() {
        form.insert("client_secret", secret.as_str());
    }
    post_form_blocking(GOOGLE_TOKEN_URL, &form)
}

pub fn refresh_access_token_blocking(
    refresh_token: &str,
    client_id: &str,
    client_secret: &str,
) -> Result<TokenResponse, String> {
    let mut form = HashMap::new();
    form.insert("grant_type", "refresh_token");
    form.insert("refresh_token", refresh_token);
    form.insert("client_id", client_id);
    let secret = client_secret.to_string();
    if !client_secret.is_empty() {
        form.insert("client_secret", secret.as_str());
    }
    post_form_blocking(GOOGLE_TOKEN_URL, &form)
}

fn post_form_blocking(
    url: &str,
    form: &HashMap<&str, &str>,
) -> Result<TokenResponse, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client.post(url).form(form).send().map_err(|e| e.to_string())?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().unwrap_or_default();
        let detail = if body.is_empty() {
            status.to_string()
        } else {
            body.chars().take(400).collect()
        };
        return Err(format!("token endpoint {}: {detail}", status.as_u16()));
    }
    resp.json::<TokenResponse>().map_err(|e| e.to_string())
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct StoredTokens {
    pub access_token: Option<String>,
    pub refresh_token: Option<String>,
    pub expires_at: Option<f64>,
    pub expires_in: Option<u64>,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

pub struct TokenStore {
    pub path: PathBuf,
}

impl TokenStore {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn load(&self) -> StoredTokens {
        if !self.path.exists() {
            return StoredTokens::default();
        }
        let text = std::fs::read_to_string(&self.path).unwrap_or_default();
        serde_json::from_str(&text).unwrap_or_default()
    }

    pub fn save(&self, tokens: &StoredTokens) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let text = serde_json::to_string(tokens).map_err(|e| e.to_string())?;
        std::fs::write(&self.path, text).map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&self.path, std::fs::Permissions::from_mode(0o600));
        }
        Ok(())
    }

    pub fn clear(&self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

pub fn run_oauth_loopback(
    client_id: &str,
    scopes: &[&str],
    client_secret: &str,
    timeout_secs: u64,
) -> Result<StoredTokens, String> {
    let verifier = make_code_verifier(64);
    let state: String = make_code_verifier(16);
    let port = free_port()?;
    let redirect_uri = format!("http://localhost:{port}");

    let auth_url = build_authorize_url(client_id, &redirect_uri, &state, &verifier, scopes);

    tauri_plugin_opener::open_url(auth_url, None::<&str>).map_err(|e| e.to_string())?;

    let code = wait_for_code(port, &state, timeout_secs)?;
    let mut tokens = exchange_code_blocking(&code, &verifier, &redirect_uri, client_id, client_secret)
        .map_err(|e| format!("token exchange failed: {e}"))?;

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    let expires_at = now + tokens.expires_in.unwrap_or(3600) as f64;

    Ok(StoredTokens {
        access_token: tokens.access_token.take(),
        refresh_token: tokens.refresh_token.take(),
        expires_at: Some(expires_at),
        expires_in: tokens.expires_in,
        extra: HashMap::new(),
    })
}

fn free_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    Ok(listener.local_addr().map_err(|e| e.to_string())?.port())
}

fn wait_for_code(port: u16, expected_state: &str, timeout_secs: u64) -> Result<String, String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    let listener = std::net::TcpListener::bind(format!("127.0.0.1:{port}"))
        .or_else(|_| std::net::TcpListener::bind(format!("[::1]:{port}")))
        .map_err(|e| e.to_string())?;
    listener
        .set_nonblocking(true)
        .map_err(|e| e.to_string())?;

    loop {
        if std::time::Instant::now() > deadline {
            return Err(
                "sign-in timed out — the browser never reached the local callback page (if you use a proxy/VPN, make sure localhost is excluded from it)".to_string()
            );
        }
        match listener.accept() {
            Ok((mut stream, _)) => {
                use std::io::{BufRead, BufReader, Write};
                let mut reader = BufReader::new(&stream);
                let mut request_line = String::new();
                if reader.read_line(&mut request_line).is_ok() {
                    let path = request_line
                        .split_whitespace()
                        .nth(1)
                        .unwrap_or("/");
                    let query = path.splitn(2, '?').nth(1).unwrap_or("");
                    let code_result = parse_redirect(query, expected_state);
                    let (status, body) = match &code_result {
                        Ok(_) => (
                            "200 OK",
                            "<h2>SnipIt</h2><p>Signed in — you can close this window.</p>",
                        ),
                        Err(e) => ("400 Bad Request", e.as_str()),
                    };
                    let response = format!(
                        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    let _ = stream.write_all(response.as_bytes());
                    if let Ok(code) = code_result {
                        return Ok(code);
                    } else {
                        return Err(code_result.unwrap_err());
                    }
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(e) => return Err(e.to_string()),
        }
    }
}
