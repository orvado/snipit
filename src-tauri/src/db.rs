use chrono::Utc;
use rusqlite::{params, Connection, Row};
use serde::Serialize;
use std::path::Path;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS snippets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    heading      TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    last_used_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS snippets_fts USING fts5(
    heading, content, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS snippets_ai AFTER INSERT ON snippets BEGIN
    INSERT INTO snippets_fts(rowid, heading, content)
    VALUES (new.id, new.heading, new.content);
END;
CREATE TRIGGER IF NOT EXISTS snippets_ad AFTER DELETE ON snippets BEGIN
    DELETE FROM snippets_fts WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS snippets_au AFTER UPDATE ON snippets BEGIN
    DELETE FROM snippets_fts WHERE rowid = old.id;
    INSERT INTO snippets_fts(rowid, heading, content)
    VALUES (new.id, new.heading, new.content);
END;
"#;

const MRU_ORDER: &str = "ORDER BY last_used_at DESC, updated_at DESC, id DESC";

#[derive(Debug, Clone, Serialize)]
pub struct Snippet {
    pub id: i64,
    pub heading: String,
    pub content: String,
    pub created_at: String,
    pub updated_at: String,
    pub last_used_at: Option<String>,
}

fn row_to_snippet(row: &Row) -> rusqlite::Result<Snippet> {
    Ok(Snippet {
        id: row.get(0)?,
        heading: row.get(1)?,
        content: row.get(2)?,
        created_at: row.get(3)?,
        updated_at: row.get(4)?,
        last_used_at: row.get(5)?,
    })
}

fn now_seconds() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

fn now_millis() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%S%.3f").to_string()
}

fn seed_snippets() -> Vec<(&'static str, &'static str)> {
    #[cfg(target_os = "macos")]
    {
        vec![
            ("Show IP configuration", "ifconfig"),
            ("Flush DNS cache", "sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"),
            ("List listening ports", "lsof -iTCP -sTCP:LISTEN -n -P"),
            ("Kill a process by PID", "kill -9 <pid>"),
            ("Process on a port", "lsof -i :8080"),
            ("Check Wi-Fi networks", "networksetup -listallhardwareports"),
            ("Open clipboard history", "⌘+V (clipboard history via app)"),
            ("ChatGPT: code explainer", "Please explain the following code snippet line by line, assuming I am a beginner:\n\n```\n<code>\n```"),
            ("ChatGPT: rubber duck", "You are my rubber duck. I will describe my plan and reasoning. Ask me sharp questions to help me find flaws in my thinking."),
            ("ChatGPT: TL;DR", "Summarize the following text in 3 bullet points, each at most 12 words:\n\n<text>"),
        ]
    }
    #[cfg(not(target_os = "macos"))]
    {
        vec![
            ("Show IP configuration", "ipconfig /all"),
            ("Flush DNS cache", "ipconfig /flushdns"),
            ("List active TCP connections", "netstat -ano | findstr LISTENING"),
            ("Kill a process by PID", "taskkill /F /PID <pid>"),
            ("PowerShell: process on a port", "Get-NetTCPConnection -LocalPort 8080 | Select-Object OwningProcess"),
            ("Check saved Wi-Fi profiles", "netsh wlan show profiles"),
            ("Open clipboard history", "Win+V"),
            ("ChatGPT: code explainer", "Please explain the following code snippet line by line, assuming I am a beginner:\n\n```\n<code>\n```"),
            ("ChatGPT: rubber duck", "You are my rubber duck. I will describe my plan and reasoning. Ask me sharp questions to help me find flaws in my thinking."),
            ("ChatGPT: TL;DR", "Summarize the following text in 3 bullet points, each at most 12 words:\n\n<text>"),
        ]
    }
}

pub struct Database {
    pub path: String,
    pub conn: Connection,
    pub first_run: bool,
}

impl Database {
    pub fn new<P: AsRef<Path>>(path: P) -> Result<Self, String> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        if let Some(parent) = path.as_ref().parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let conn = Connection::open(path.as_ref()).map_err(|e| e.to_string())?;
        conn.execute("PRAGMA journal_mode=WAL", [])
            .map_err(|e| e.to_string())?;

        let existing: std::collections::HashSet<String> = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='table'")
            .map_err(|e| e.to_string())?
            .query_map([], |row| row.get(0))
            .map_err(|e| e.to_string())?
            .collect::<Result<_, _>>()
            .map_err(|e: rusqlite::Error| e.to_string())?;

        conn.execute_batch(SCHEMA).map_err(|e| e.to_string())?;
        Self::migrate(&conn, &existing)?;

        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM snippets", [], |r| r.get(0))
            .map_err(|e| e.to_string())?;
        let first_run = count == 0;

        let mut db = Self {
            path: path_str,
            conn,
            first_run,
        };
        if first_run {
            for (heading, content) in seed_snippets() {
                db.add(heading, content)?;
            }
        }
        Ok(db)
    }

    fn migrate(
        conn: &Connection,
        existing: &std::collections::HashSet<String>,
    ) -> Result<(), String> {
        let cols: std::collections::HashSet<String> = conn
            .prepare("PRAGMA table_info(snippets)")
            .map_err(|e| e.to_string())?
            .query_map([], |row| row.get::<_, String>(1))
            .map_err(|e| e.to_string())?
            .collect::<Result<_, _>>()
            .map_err(|e: rusqlite::Error| e.to_string())?;

        let needs_mru = !cols.contains("last_used_at");
        if needs_mru {
            conn.execute("ALTER TABLE snippets ADD COLUMN last_used_at TEXT", [])
                .map_err(|e| e.to_string())?;
        }
        if !existing.contains("snippets_fts") {
            conn.execute(
                "INSERT INTO snippets_fts(rowid, heading, content) SELECT id, heading, content FROM snippets",
                [],
            )
            .map_err(|e| e.to_string())?;
        }
        if needs_mru {
            conn.execute(
                "UPDATE snippets SET last_used_at = updated_at WHERE last_used_at IS NULL",
                [],
            )
            .map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    fn like_pattern(term: &str) -> String {
        let escaped = term.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_");
        format!("%{escaped}%")
    }

    pub fn search(&self, query: &str, limit: i64) -> Result<Vec<Snippet>, String> {
        let terms: Vec<String> = query
            .split_whitespace()
            .map(|t| t.trim().to_string())
            .filter(|t| !t.is_empty())
            .collect();

        if terms.is_empty() {
            let sql = format!("SELECT id, heading, content, created_at, updated_at, last_used_at FROM snippets {MRU_ORDER} LIMIT ?");
            let mut stmt = self.conn.prepare(&sql).map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![limit], row_to_snippet)
                .map_err(|e| e.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?;
            return Ok(rows);
        }

        let fts_terms: Vec<&String> = terms.iter().filter(|t| t.len() >= 3).collect();
        let like_terms: Vec<&String> = terms.iter().filter(|t| t.len() < 3).collect();

        if fts_terms.is_empty() {
            let mut clauses = Vec::new();
            let mut qparams: Vec<String> = Vec::new();
            for t in &like_terms {
                let like = Self::like_pattern(&t.to_lowercase());
                clauses.push("(lower(heading) LIKE ? ESCAPE '\\' OR lower(content) LIKE ? ESCAPE '\\')".to_string());
                qparams.push(like.clone());
                qparams.push(like);
            }
            let sql = format!(
                "SELECT id, heading, content, created_at, updated_at, last_used_at FROM snippets WHERE {} {MRU_ORDER} LIMIT ?",
                clauses.join(" AND ")
            );
            let mut stmt = self.conn.prepare(&sql).map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(
                    rusqlite::params_from_iter(qparams.iter().chain(std::iter::once(&limit.to_string()))),
                    row_to_snippet,
                )
                .map_err(|e| e.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?;
            return Ok(rows);
        }

        let fts_match = fts_terms
            .iter()
            .map(|t| format!("\"{}\"", t.replace('"', "\"\"")))
            .collect::<Vec<_>>()
            .join(" AND ");

        let mut sql = "SELECT s.id, s.heading, s.content, s.created_at, s.updated_at, s.last_used_at \
                       FROM snippets_fts JOIN snippets s ON s.id = snippets_fts.rowid \
                       WHERE snippets_fts MATCH ?"
            .to_string();
        let mut str_params: Vec<String> = vec![fts_match];

        if !like_terms.is_empty() {
            let mut clauses = Vec::new();
            for t in &like_terms {
                let like = Self::like_pattern(&t.to_lowercase());
                clauses.push("(lower(s.heading) LIKE ? ESCAPE '\\' OR lower(s.content) LIKE ? ESCAPE '\\')".to_string());
                str_params.push(like.clone());
                str_params.push(like);
            }
            sql.push_str(" AND ");
            sql.push_str(&clauses.join(" AND "));
        }
        sql.push_str(" ORDER BY bm25(snippets_fts, 5.0, 1.0), s.last_used_at DESC, s.updated_at DESC, s.id DESC LIMIT ?");
        str_params.push(limit.to_string());

        let mut stmt = self.conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(rusqlite::params_from_iter(str_params.iter()), row_to_snippet)
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        Ok(rows)
    }

    pub fn count(&self) -> Result<i64, String> {
        self.conn
            .query_row("SELECT COUNT(*) FROM snippets", [], |r| r.get(0))
            .map_err(|e| e.to_string())
    }

    pub fn get(&self, id: i64) -> Result<Option<Snippet>, String> {
        let mut stmt = self
            .conn
            .prepare("SELECT id, heading, content, created_at, updated_at, last_used_at FROM snippets WHERE id=?")
            .map_err(|e| e.to_string())?;
        let mut rows = stmt.query_map(params![id], row_to_snippet).map_err(|e| e.to_string())?;
        match rows.next() {
            Some(Ok(s)) => Ok(Some(s)),
            Some(Err(e)) => Err(e.to_string()),
            None => Ok(None),
        }
    }

    pub fn add(&mut self, heading: &str, content: &str) -> Result<i64, String> {
        let now = now_seconds();
        let now_ms = now_millis();
        self.conn
            .execute(
                "INSERT INTO snippets (heading, content, created_at, updated_at, last_used_at) VALUES (?, ?, ?, ?, ?)",
                params![heading, content, now, now, now_ms],
            )
            .map_err(|e| e.to_string())?;
        Ok(self.conn.last_insert_rowid())
    }

    pub fn mark_used(&self, id: i64) -> Result<(), String> {
        self.conn
            .execute(
                "UPDATE snippets SET last_used_at=? WHERE id=?",
                params![now_millis(), id],
            )
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn update(&self, id: i64, heading: &str, content: &str) -> Result<(), String> {
        self.conn
            .execute(
                "UPDATE snippets SET heading=?, content=?, updated_at=? WHERE id=?",
                params![heading, content, now_seconds(), id],
            )
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn delete(&self, id: i64) -> Result<(), String> {
        self.conn
            .execute("DELETE FROM snippets WHERE id=?", params![id])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn close(self) {}
}
