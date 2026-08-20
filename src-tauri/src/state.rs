use std::sync::Mutex;

use crate::db::Database;

pub struct AppState {
    pub db: Mutex<Database>,
    pub first_run: bool,
}
