import { invoke } from "@tauri-apps/api/core";

export type Snippet = {
  id: number;
  heading: string;
  content: string;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export type BackupMeta = {
  name: string;
  created_at: string;
  size: number;
  id: string;
};

export type ConfigInfo = {
  app_name: string;
  app_version: string;
  google_configured: boolean;
  max_content_len: number;
  max_heading_len: number;
  max_results: number;
  auto_close_ms: number;
};

export type CloudStatus = {
  connected: boolean;
  has_refresh_token: boolean;
};

export const api = {
  getConfig: () => invoke<ConfigInfo>("get_config"),
  search: (query: string, limit?: number) =>
    invoke<Snippet[]>("search", { query, limit }),
  getSnippet: (id: number) => invoke<Snippet | null>("get_snippet", { id }),
  addSnippet: (heading: string, content: string) =>
    invoke<number>("add_snippet", { heading, content }),
  updateSnippet: (id: number, heading: string, content: string) =>
    invoke<void>("update_snippet", { id, heading, content }),
  deleteSnippet: (id: number) => invoke<void>("delete_snippet", { id }),
  markUsed: (id: number) => invoke<void>("mark_used", { id }),
  copyText: (text: string) => invoke<void>("copy_text", { text }),
  cloudStatus: () => invoke<CloudStatus>("cloud_status"),
  cloudDisconnect: () => invoke<void>("cloud_disconnect"),
  cloudConnect: () => invoke<void>("cloud_connect"),
  backupNow: () => invoke<string>("backup_now"),
  listBackups: () => invoke<BackupMeta[]>("list_backups"),
  restoreBackup: (name: string) => invoke<void>("restore_backup", { name }),
};
