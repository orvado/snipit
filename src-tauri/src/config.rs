use std::path::PathBuf;

pub const APP_NAME: &str = "SnipIt";
pub const APP_VERSION: &str = "0.1.0";

pub const AUTO_CLOSE_MS: u64 = 1500;
pub const MAX_CONTENT_LEN: usize = 32768;
pub const MAX_HEADING_LEN: usize = 120;
pub const MAX_RESULTS: usize = 300;
pub const MAX_BACKUPS: usize = 10;
#[allow(dead_code)]
pub const EXCHANGE_TIMEOUT_S: u64 = 30;

pub const WINDOW_WIDTH: f64 = 720.0;
pub const WINDOW_HEIGHT: f64 = 420.0;
pub const MARGIN_TOP: f64 = 140.0;

pub const CLIPBOARD_CRLF: bool = true;

#[allow(dead_code)]
pub const IPC_PORT: u16 = 48731;
#[allow(dead_code)]
pub const MUTEX_NAME: &str = "Local\\SnipIt.SingleInstance.v1";

pub const CLOUD_SCOPES: &[&str] = &["https://www.googleapis.com/auth/drive.appdata"];

pub fn default_hotkey() -> String {
    if let Ok(val) = std::env::var("SNIPIT_HOTKEY") {
        if !val.is_empty() {
            return val;
        }
    }
    #[cfg(target_os = "macos")]
    {
        "command+alt+s".to_string()
    }
    #[cfg(not(target_os = "macos"))]
    {
        "ctrl+alt+s".to_string()
    }
}

pub fn tauri_hotkey() -> String {
    let raw = default_hotkey();
    raw.split('+')
        .map(|part| {
            let lower = part.to_lowercase();
            match lower.as_str() {
                "ctrl" => "Ctrl".to_string(),
                "alt" => "Alt".to_string(),
                "shift" => "Shift".to_string(),
                "super" | "cmd" | "command" | "meta" => "Super".to_string(),
                _ => {
                    let mut c = part.chars();
                    match c.next() {
                        None => String::new(),
                        Some(f) => f.to_uppercase().collect::<String>() + c.as_str().to_lowercase().as_str(),
                    }
                }
            }
        })
        .collect::<Vec<_>>()
        .join("+")
}

pub fn google_client_id() -> String {
    std::env::var("SNIPIT_GOOGLE_CLIENT_ID")
        .or_else(|_| std::env::var("GOOGLE_CLIENT_ID"))
        .unwrap_or_default()
}

pub fn google_client_secret() -> String {
    std::env::var("SNIPIT_GOOGLE_CLIENT_SECRET")
        .or_else(|_| std::env::var("GOOGLE_CLIENT_SECRET"))
        .unwrap_or_default()
}

pub fn data_dir() -> PathBuf {
    if let Ok(base) = std::env::var("SNIPIT_DATA_DIR") {
        if !base.is_empty() {
            let p = PathBuf::from(base).join("SnipIt");
            let _ = std::fs::create_dir_all(&p);
            return p;
        }
    }
    if let Ok(appdata) = std::env::var("APPDATA") {
        if !appdata.is_empty() {
            let p = PathBuf::from(appdata).join("SnipIt");
            let _ = std::fs::create_dir_all(&p);
            return p;
        }
    }
    if let Some(dir) = dirs::data_dir() {
        let p = dir.join("SnipIt");
        let _ = std::fs::create_dir_all(&p);
        return p;
    }
    let p = PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| ".".to_string())).join("SnipIt");
    let _ = std::fs::create_dir_all(&p);
    p
}

pub fn db_path() -> PathBuf {
    data_dir().join("snipit.db")
}

pub fn backups_dir() -> PathBuf {
    data_dir().join("backups")
}

pub fn cloud_token_path() -> PathBuf {
    data_dir().join("cloud_token.json")
}
