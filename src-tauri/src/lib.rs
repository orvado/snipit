mod backup;
mod clipboard;
mod cloud;
mod commands;
mod config;
mod db;
mod oauth;
mod state;

use tauri::{Emitter, Manager};

fn position_window(window: &tauri::WebviewWindow) {
    if let Ok(Some(monitor)) = window.current_monitor() {
        let size = monitor.size();
        let scale = monitor.scale_factor();
        let sw = size.width as f64 / scale;
        let sh = size.height as f64 / scale;
        let w = config::WINDOW_WIDTH.min((sw - 24.0).max(320.0));
        let h = config::WINDOW_HEIGHT.min((sh - 120.0).max(240.0));
        let x = (sw - w) / 2.0;
        let y = config::MARGIN_TOP.min((sh - h - 80.0).max(0.0));
        let _ = window.set_size(tauri::Size::Logical(tauri::LogicalSize { width: w, height: h }));
        let _ = window.set_position(tauri::Position::Logical(tauri::LogicalPosition { x, y }));
    }
}

fn toggle_window(window: &tauri::WebviewWindow) {
    let visible = window.is_visible().unwrap_or(false);
    let focused = window.is_focused().unwrap_or(false);
    if visible && focused {
        let _ = window.hide();
    } else {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

pub fn run() {
    let db_path = config::db_path();
    let database = db::Database::new(&db_path).expect("failed to open database");
    let first_run = database.first_run;

    let app_state = state::AppState {
        db: std::sync::Mutex::new(database),
        first_run,
    };

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.unminimize();
                let _ = win.show();
                let _ = win.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            commands::get_config,
            commands::search,
            commands::get_snippet,
            commands::add_snippet,
            commands::update_snippet,
            commands::delete_snippet,
            commands::mark_used,
            commands::copy_text,
            commands::cloud_status,
            commands::cloud_disconnect,
            commands::cloud_connect,
            commands::backup_now,
            commands::list_backups,
            commands::restore_backup,
        ])
        .setup(move |app| {
            let window = app.get_webview_window("main").expect("main window missing");
            position_window(&window);

            // System tray
            use tauri::menu::{Menu, MenuItem};
            use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

            let show_i = MenuItem::with_id(app, "show", "Show SnipIt", true, None::<&str>)?;
            let new_i = MenuItem::with_id(app, "new", "New snippet\u{2026}", true, None::<&str>)?;
            let backup_i = MenuItem::with_id(app, "backup", "Back up now\u{2026}", true, None::<&str>)?;
            let cloud_i = MenuItem::with_id(app, "cloud", "Cloud\u{2026}", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_i, &new_i, &backup_i, &cloud_i, &quit_i])?;

            let _tray = TrayIconBuilder::with_id("main")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("SnipIt — snippet manager")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.unminimize();
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "new" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.unminimize();
                            let _ = w.show();
                            let _ = w.set_focus();
                            let _ = w.emit("tray-new", ());
                        }
                    }
                    "backup" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.emit("tray-backup", ());
                        }
                    }
                    "cloud" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.unminimize();
                            let _ = w.show();
                            let _ = w.set_focus();
                            let _ = w.emit("tray-cloud", ());
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.unminimize();
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Global hotkey
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
                let hotkey_str = config::tauri_hotkey();
                if let Ok(shortcut) = hotkey_str.parse::<Shortcut>() {
                    let app_handle = app.handle().clone();
                    let _ = app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
                        if event.state == ShortcutState::Pressed {
                            if let Some(w) = app_handle.get_webview_window("main") {
                                toggle_window(&w);
                            }
                        }
                    });
                } else {
                    // Fallback: try Ctrl+Alt+S explicitly
                    let fallback = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyS);
                    let app_handle = app.handle().clone();
                    let _ = app.global_shortcut().on_shortcut(fallback, move |_app, _shortcut, event| {
                        if event.state == ShortcutState::Pressed {
                            if let Some(w) = app_handle.get_webview_window("main") {
                                toggle_window(&w);
                            }
                        }
                    });
                    log::warn!("Failed to parse hotkey '{hotkey_str}', fell back to Ctrl+Alt+S");
                }
            }

            // Close button hides instead of quitting (tray quit is the real quit)
            let win = window.clone();
            let win2 = win.clone();
            win.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = win2.hide();
                }
            });

            // Show main window on launch — the frontend handles its own
            // hidden/visible lifecycle after that (Esc hides, tray/hotkey shows).
            // Previously this was gated on first_run, which left the window
            // invisible after the initial seed and forced users to find the tray.
            let w = app.get_webview_window("main").unwrap();
            let _ = w.show();
            let _ = w.set_focus();

            Ok(())
        });

    builder
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                api.prevent_exit();
            }
        });
}
