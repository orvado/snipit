use std::sync::Mutex;

use crate::db::Database;

pub struct AppState {
    pub db: Mutex<Database>,
    #[allow(dead_code)]
    pub first_run: bool,
}
