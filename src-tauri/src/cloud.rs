use std::path::Path;

use crate::backup::BackupMeta;

const DRIVE_API: &str = "https://www.googleapis.com/drive/v3";
const DRIVE_UPLOAD: &str = "https://www.googleapis.com/upload/drive/v3/files";
const APP_DATA_FOLDER: &str = "appDataFolder";

pub trait TokenGetter: Send + Sync {
    fn get(&self) -> Result<String, String>;
}

pub struct GoogleDriveProvider {
    token: Box<dyn TokenGetter>,
}

impl GoogleDriveProvider {
    pub fn new(token: Box<dyn TokenGetter>) -> Self {
        Self { token }
    }

    fn auth_header(&self) -> Result<String, String> {
        Ok(format!("Bearer {}", self.token.get()?))
    }

    fn client() -> Result<reqwest::blocking::Client, String> {
        reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(|e| e.to_string())
    }

    fn check_resp(resp: reqwest::blocking::Response) -> Result<reqwest::blocking::Response, String> {
        if resp.status().is_success() {
            Ok(resp)
        } else {
            let status = resp.status().as_u16();
            let body = resp.text().unwrap_or_default();
            let detail = if body.is_empty() {
                format!("HTTP {status}")
            } else {
                body.chars().take(400).collect()
            };
            Err(format!("Drive API {status}: {detail}"))
        }
    }

    pub fn list(&self) -> Result<Vec<BackupMeta>, String> {
        let auth = self.auth_header()?;
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("spaces", APP_DATA_FOLDER)
            .append_pair("pageSize", "100")
            .append_pair("orderBy", "createdTime desc")
            .append_pair("fields", "files(id,name,createdTime,size)")
            .finish();
        let url = format!("{DRIVE_API}/files?{query}");
        let resp = Self::client()?
            .get(&url)
            .header("Authorization", &auth)
            .send()
            .map_err(|e| e.to_string())?;
        let resp = Self::check_resp(resp)?;
        let data: serde_json::Value = resp.json().map_err(|e| e.to_string())?;
        let files = data
            .get("files")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        Ok(files
            .iter()
            .map(|f| BackupMeta {
                name: f.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                created_at: f.get("createdTime").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                size: f
                    .get("size")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse::<i64>().ok())
                    .or_else(|| f.get("size").and_then(|v| v.as_i64()))
                    .unwrap_or(0),
                id: f.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            })
            .collect())
    }

    pub fn upload(&self, name: &str, path: &Path) -> Result<(), String> {
        let auth = self.auth_header()?;
        let boundary = format!("snipit{}", uuid::Uuid::new_v4().simple());
        let meta = serde_json::json!({"name": name, "parents": [APP_DATA_FOLDER]}).to_string();
        let payload = std::fs::read(path).map_err(|e| e.to_string())?;

        let mut body: Vec<u8> = Vec::new();
        body.extend_from_slice(format!("--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").as_bytes());
        body.extend_from_slice(meta.as_bytes());
        body.extend_from_slice(b"\r\n");
        body.extend_from_slice(format!("--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes());
        body.extend_from_slice(&payload);
        body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());

        let url = format!("{DRIVE_UPLOAD}?uploadType=multipart");
        let resp = Self::client()?
            .post(&url)
            .header("Authorization", &auth)
            .header("Content-Type", format!("multipart/related; boundary={boundary}"))
            .body(body)
            .send()
            .map_err(|e| e.to_string())?;
        Self::check_resp(resp)?;
        Ok(())
    }

    pub fn download(&self, name: &str, dest: &Path) -> Result<(), String> {
        let meta = self.find(name)?;
        let auth = self.auth_header()?;
        let url = format!("{DRIVE_API}/files/{}?alt=media", meta.id);
        let resp = Self::client()?
            .get(&url)
            .header("Authorization", &auth)
            .send()
            .map_err(|e| e.to_string())?;
        let resp = Self::check_resp(resp)?;
        let bytes = resp.bytes().map_err(|e| e.to_string())?;
        std::fs::write(dest, &bytes).map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn delete(&self, name: &str) -> Result<(), String> {
        let meta = self.find(name)?;
        let auth = self.auth_header()?;
        let url = format!("{DRIVE_API}/files/{}", meta.id);
        let resp = Self::client()?
            .delete(&url)
            .header("Authorization", &auth)
            .send()
            .map_err(|e| e.to_string())?;
        Self::check_resp(resp)?;
        Ok(())
    }

    fn find(&self, name: &str) -> Result<BackupMeta, String> {
        for meta in self.list()? {
            if meta.name == name {
                return Ok(meta);
            }
        }
        Err(format!("backup not found on cloud: {name}"))
    }
}
