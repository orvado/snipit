use serde::Serialize;
use tauri::State;

use crate::config;
use crate::db::Snippet;
use crate::oauth::{refresh_access_token_blocking, StoredTokens, TokenStore};
use crate::state::AppState;

#[derive(Serialize)]
pub struct ConfigInfo {
    pub app_name: String,
    pub app_version: String,
    pub google_configured: bool,
    pub max_content_len: usize,
    pub max_heading_len: usize,
    pub max_results: usize,
    pub auto_close_ms: u64,
}

#[tauri::command]
pub fn get_config() -> ConfigInfo {
    ConfigInfo {
        app_name: config::APP_NAME.to_string(),
        app_version: config::APP_VERSION.to_string(),
        google_configured: !config::google_client_id().is_empty(),
        max_content_len: config::MAX_CONTENT_LEN,
        max_heading_len: config::MAX_HEADING_LEN,
        max_results: config::MAX_RESULTS,
        auto_close_ms: config::AUTO_CLOSE_MS,
    }
}

#[tauri::command]
pub fn search(query: String, limit: Option<i64>, state: State<AppState>) -> Result<Vec<Snippet>, String> {
    let lim = limit.unwrap_or(config::MAX_RESULTS as i64);
    let db = state.db.lock().map_err(|e| e.to_string())?;
    db.search(&query, lim)
}

#[tauri::command]
pub fn get_snippet(id: i64, state: State<AppState>) -> Result<Option<Snippet>, String> {
    let db = state.db.lock().map_err(|e| e.to_string())?;
    db.get(id)
}

#[tauri::command]
pub fn add_snippet(heading: String, content: String, state: State<AppState>) -> Result<i64, String> {
    if content.trim().is_empty() {
        return Err("content must not be empty".to_string());
    }
    if content.len() > config::MAX_CONTENT_LEN {
        return Err(format!(
            "content is {} chars; limit is {}",
            content.len(),
            config::MAX_CONTENT_LEN
        ));
    }
    let heading = heading.chars().take(config::MAX_HEADING_LEN).collect::<String>();
    let mut db = state.db.lock().map_err(|e| e.to_string())?;
    db.add(&heading, &content)
}

#[tauri::command]
pub fn update_snippet(
    id: i64,
    heading: String,
    content: String,
    state: State<AppState>,
) -> Result<(), String> {
    if content.trim().is_empty() {
        return Err("content must not be empty".to_string());
    }
    if content.len() > config::MAX_CONTENT_LEN {
        return Err(format!(
            "content is {} chars; limit is {}",
            content.len(),
            config::MAX_CONTENT_LEN
        ));
    }
    let heading = heading.chars().take(config::MAX_HEADING_LEN).collect::<String>();
    let db = state.db.lock().map_err(|e| e.to_string())?;
    db.update(id, &heading, &content)
}

#[tauri::command]
pub fn delete_snippet(id: i64, state: State<AppState>) -> Result<(), String> {
    let db = state.db.lock().map_err(|e| e.to_string())?;
    db.delete(id)
}

#[tauri::command]
pub fn mark_used(id: i64, state: State<AppState>) -> Result<(), String> {
    let db = state.db.lock().map_err(|e| e.to_string())?;
    db.mark_used(id)
}

#[tauri::command]
pub fn copy_text(text: String) -> Result<(), String> {
    let normalized = crate::clipboard::normalize_for_clipboard(&text);
    clipboard_copy(&normalized)
}

#[cfg(target_os = "windows")]
fn clipboard_copy(text: &str) -> Result<(), String> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::HANDLE;
    use windows_sys::Win32::System::DataExchange::{CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData};
    use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};
    const CF_UNICODETEXT: u32 = 13;
    unsafe {
        let mut last_err = std::io::Error::last_os_error();
        let mut opened = false;
        for _ in 0..10 {
            if OpenClipboard(0) != 0 {
                opened = true;
                break;
            }
            last_err = std::io::Error::last_os_error();
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if !opened {
            return Err(format!("OpenClipboard failed: {last_err}"));
        }
        let wide: Vec<u16> = OsStr::new(text).encode_wide().chain(std::iter::once(0)).collect();
        let bytes = wide.len() * 2;
        let h = GlobalAlloc(GMEM_MOVEABLE, bytes);
        if h == 0 {
            CloseClipboard();
            return Err("GlobalAlloc failed".to_string());
        }
        let ptr = GlobalLock(h as HANDLE);
        if ptr.is_null() {
            CloseClipboard();
            return Err("GlobalLock failed".to_string());
        }
        std::ptr::copy_nonoverlapping(wide.as_ptr() as *const u8, ptr as *mut u8, bytes);
        GlobalUnlock(h as HANDLE);
        EmptyClipboard();
        let result = SetClipboardData(CF_UNICODETEXT, h as HANDLE);
        CloseClipboard();
        if result == 0 {
            return Err("SetClipboardData failed".to_string());
        }
        Ok(())
    }
}

#[cfg(not(target_os = "windows"))]
fn clipboard_copy(text: &str) -> Result<(), String> {
    // On macOS the frontend uses the Tauri clipboard plugin; this is a fallback
    // that shells out to pbcopy so tests and non-Tauri callers can still copy.
    use std::io::Write;
    let mut child = std::process::Command::new("pbcopy")
        .stdin(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    if let Some(stdin) = child.stdin.as_mut() {
        stdin.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
    }
    let status = child.wait().map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("pbcopy failed with status {status}"))
    }
}

#[derive(Serialize)]
pub struct CloudStatus {
    pub connected: bool,
    pub has_refresh_token: bool,
}

#[tauri::command]
pub fn cloud_status() -> CloudStatus {
    let store = TokenStore::new(config::cloud_token_path());
    let tokens = store.load();
    let has_refresh = tokens.refresh_token.as_deref().map(|s| !s.is_empty()).unwrap_or(false);
    CloudStatus {
        connected: has_refresh,
        has_refresh_token: has_refresh,
    }
}

#[tauri::command]
pub fn cloud_disconnect() -> Result<(), String> {
    TokenStore::new(config::cloud_token_path()).clear();
    Ok(())
}

#[tauri::command]
pub fn cloud_connect() -> Result<(), String> {
    let client_id = config::google_client_id();
    if client_id.is_empty() {
        return Err("Cloud is not configured. Set SNIPIT_GOOGLE_CLIENT_ID.".to_string());
    }
    let client_secret = config::google_client_secret();
    let scopes: Vec<&str> = config::CLOUD_SCOPES.to_vec();
    let tokens = crate::oauth::run_oauth_loopback(&client_id, &scopes, &client_secret, 120)
        .map_err(|e| e.to_string())?;
    TokenStore::new(config::cloud_token_path())
        .save(&tokens)
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn ensure_access_token() -> Result<String, String> {
    let store = TokenStore::new(config::cloud_token_path());
    let tokens = store.load();
    let refresh = tokens
        .refresh_token
        .clone()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "cloud not connected".to_string())?;

    if let Some(at) = tokens.access_token.clone() {
        if let Some(exp) = tokens.expires_at {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs_f64();
            if exp > now + 60.0 && !at.is_empty() {
                return Ok(at);
            }
        }
    }

    let client_id = config::google_client_id();
    let client_secret = config::google_client_secret();
    let fresh = refresh_access_token_blocking(&refresh, &client_id, &client_secret)
        .map_err(|e| e.to_string())?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    let access = fresh.access_token.clone().unwrap_or_default();
    if access.is_empty() {
        return Err("refresh did not return an access token".to_string());
    }
    let updated = StoredTokens {
        access_token: fresh.access_token.clone(),
        refresh_token: tokens.refresh_token.clone(),
        expires_at: Some(now + fresh.expires_in.unwrap_or(3600) as f64),
        expires_in: fresh.expires_in,
        extra: Default::default(),
    };
    store.save(&updated).map_err(|e| e.to_string())?;
    let _ = tokens;
    Ok(access)
}

struct EnvTokenGetter;

impl crate::cloud::TokenGetter for EnvTokenGetter {
    fn get(&self) -> Result<String, String> {
        ensure_access_token()
    }
}

#[tauri::command]
pub fn backup_now(state: State<AppState>) -> Result<String, String> {
    let db_path = {
        let db = state.db.lock().map_err(|e| e.to_string())?;
        std::path::PathBuf::from(db.path.clone())
    };
    let local_dir = config::backups_dir();
    let provider = crate::cloud::GoogleDriveProvider::new(Box::new(EnvTokenGetter));
    let store = crate::backup::BackupStore::new(
        Box::new(CloudProviderAdapter(provider)),
        db_path,
        local_dir,
    );
    store.backup()
}

#[tauri::command]
pub fn list_backups() -> Result<Vec<crate::backup::BackupMeta>, String> {
    let db_path = config::db_path();
    let local_dir = config::backups_dir();
    let provider = crate::cloud::GoogleDriveProvider::new(Box::new(EnvTokenGetter));
    let store = crate::backup::BackupStore::new(
        Box::new(CloudProviderAdapter(provider)),
        db_path,
        local_dir,
    );
    store.list_backups()
}

#[tauri::command]
pub fn restore_backup(name: String, state: State<AppState>) -> Result<(), String> {
    let db_path = {
        let db = state.db.lock().map_err(|e| e.to_string())?;
        std::path::PathBuf::from(db.path.clone())
    };
    let local_dir = config::backups_dir();
    let provider = crate::cloud::GoogleDriveProvider::new(Box::new(EnvTokenGetter));
    let store = crate::backup::BackupStore::new(
        Box::new(CloudProviderAdapter(provider)),
        db_path.clone(),
        local_dir,
    );
    let tmp = store.prepare_restore(&name, &db_path)?;
    {
        let db = state.db.lock().map_err(|e| e.to_string())?;
        let _ = db.path.clone();
        drop(db);
        std::mem::drop(state);
        return store.apply_restore(&db_path, &tmp);
    }
}

struct CloudProviderAdapter(crate::cloud::GoogleDriveProvider);

impl crate::backup::CloudProvider for CloudProviderAdapter {
    fn upload(&self, name: &str, path: &std::path::Path) -> Result<(), String> {
        self.0.upload(name, path)
    }
    fn download(&self, name: &str, dest: &std::path::Path) -> Result<(), String> {
        self.0.download(name, dest)
    }
    fn delete(&self, name: &str) -> Result<(), String> {
        self.0.delete(name)
    }
    fn list(&self) -> Result<Vec<crate::backup::BackupMeta>, String> {
        self.0.list()
    }
}
