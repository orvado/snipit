use rusqlite::Connection;
use serde::Serialize;
use std::path::{Path, PathBuf};

use crate::config::MAX_BACKUPS;

#[derive(Debug, Clone, Serialize)]
pub struct BackupMeta {
    pub name: String,
    pub created_at: String,
    pub size: i64,
    pub id: String,
}

pub trait CloudProvider: Send + Sync {
    fn upload(&self, name: &str, path: &Path) -> Result<(), String>;
    fn download(&self, name: &str, dest: &Path) -> Result<(), String>;
    fn delete(&self, name: &str) -> Result<(), String>;
    fn list(&self) -> Result<Vec<BackupMeta>, String>;
}

fn quote_sql(s: &str) -> String {
    s.replace('\'', "''")
}

pub fn snapshot_db(src: &Path, dest_dir: &Path, prefix: &str) -> Result<PathBuf, String> {
    std::fs::create_dir_all(dest_dir).map_err(|e| e.to_string())?;
    let stamp = chrono::Utc::now().format("%Y%m%d_%H%M%S_%3f").to_string();
    let dest = dest_dir.join(format!("{prefix}{stamp}.db"));
    if dest.exists() {
        let _ = std::fs::remove_file(&dest);
    }
    let conn = Connection::open(src).map_err(|e| e.to_string())?;
    let sql = format!("VACUUM INTO '{}'", quote_sql(&dest.to_string_lossy()));
    conn.execute(&sql, []).map_err(|e| e.to_string())?;
    Ok(dest)
}

pub fn snapshot_db_default(src: &Path, dest_dir: &Path) -> Result<PathBuf, String> {
    snapshot_db(src, dest_dir, "snipit_backup_")
}

pub fn prune_backups(dir: &Path, keep: usize) -> Result<Vec<PathBuf>, String> {
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
        .map_err(|e| e.to_string())?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("snipit_backup_") && n.ends_with(".db"))
                .unwrap_or(false)
        })
        .collect();
    files.sort_by(|a, b| b.cmp(a));
    for old in files.iter().skip(keep) {
        let _ = std::fs::remove_file(old);
    }
    files.truncate(keep);
    Ok(files)
}

pub struct BackupStore {
    pub provider: Box<dyn CloudProvider>,
    pub db_path: PathBuf,
    pub local_dir: PathBuf,
    pub keep: usize,
}

impl BackupStore {
    pub fn new(provider: Box<dyn CloudProvider>, db_path: PathBuf, local_dir: PathBuf) -> Self {
        Self {
            provider,
            db_path,
            local_dir,
            keep: MAX_BACKUPS,
        }
    }

    pub fn backup(&self) -> Result<String, String> {
        let snap = snapshot_db_default(&self.db_path, &self.local_dir)?;
        let name = snap
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();
        if let Err(e) = self.provider.upload(&name, &snap) {
            let _ = std::fs::remove_file(&snap);
            return Err(e);
        }
        self.prune_cloud()?;
        let _ = prune_backups(&self.local_dir, self.keep);
        Ok(name)
    }

    pub fn list_backups(&self) -> Result<Vec<BackupMeta>, String> {
        let mut metas = self.provider.list()?;
        metas.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(metas)
    }

    pub fn download_verified(&self, name: &str, dest: &Path) -> Result<PathBuf, String> {
        self.provider.download(name, dest)?;
        let conn = Connection::open(dest).map_err(|e| e.to_string())?;
        let row: String = conn
            .query_row("PRAGMA quick_check", [], |r| r.get(0))
            .map_err(|e| e.to_string())?;
        if row != "ok" {
            return Err(format!("downloaded backup failed integrity check: {row}"));
        }
        Ok(dest.to_path_buf())
    }

    pub fn prepare_restore(&self, name: &str, db_path: &Path) -> Result<PathBuf, String> {
        self.pre_restore_snapshot(db_path)?;
        let tmp = db_path.with_file_name(format!(".restore_{}.db", uuid::Uuid::new_v4().simple()));
        match self.download_verified(name, &tmp) {
            Ok(p) => Ok(p),
            Err(e) => {
                let _ = std::fs::remove_file(&tmp);
                Err(e)
            }
        }
    }

    pub fn apply_restore(&self, live_path: &Path, verified_tmp: &Path) -> Result<(), String> {
        std::fs::rename(verified_tmp, live_path).map_err(|e| e.to_string())?;
        for suffix in ["-wal", "-shm"] {
            let p = PathBuf::from(format!("{}{suffix}", live_path.to_string_lossy()));
            let _ = std::fs::remove_file(p);
        }
        Ok(())
    }

    fn pre_restore_snapshot(&self, db_path: &Path) -> Result<PathBuf, String> {
        let snap = snapshot_db(db_path, &self.local_dir, "pre_restore_")?;
        let mut files: Vec<PathBuf> = std::fs::read_dir(&self.local_dir)
            .map_err(|e| e.to_string())?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.starts_with("pre_restore_") && n.ends_with(".db"))
                    .unwrap_or(false)
            })
            .collect();
        files.sort_by(|a, b| b.cmp(a));
        for old in files.iter().skip(3) {
            let _ = std::fs::remove_file(old);
        }
        Ok(snap)
    }

    fn prune_cloud(&self) -> Result<(), String> {
        let mut metas = self.provider.list()?;
        metas.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        for meta in metas.iter().skip(self.keep) {
            let _ = self.provider.delete(&meta.name);
        }
        Ok(())
    }
}
