// Workspace — Tauri entry point.
//
// On launch this spawns the Python sidecar (the FastAPI server) as a child
// process and hands it to the app to manage. The webview then loads the React
// frontend, which talks to the sidecar over http://127.0.0.1:8765.
//
// Dev builds (`npm run tauri dev`) run the interpreter against the source
// tree — preferring the project venv, which has libsql for synced mode.
// Release builds spawn the PyInstaller-frozen sidecar bundled as a Tauri
// external binary (built by scripts/build_sidecar.py). The shell plugin
// spawns either one with CREATE_NO_WINDOW, so no console flashes.
//
// Release builds also check GitHub Releases for an update on startup
// (tauri-plugin-updater; endpoint + pubkey in tauri.conf.json) and offer to
// install via a native dialog. Failures are silent — no network, no
// release yet, nothing newer — the app just starts.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let shell = app.shell();
            let (mut rx, _child) = if cfg!(debug_assertions) {
                // Dev: run the interpreter against the source tree. Prefer
                // the project venv (has libsql for synced mode); fall back
                // to whatever python3 is on PATH, matching the old behaviour.
                let src_python = std::env::current_dir().unwrap().join("../src-python");
                let venv_python = src_python.join(".venv/Scripts/python.exe");
                let python_cmd = if venv_python.exists() {
                    venv_python.to_string_lossy().into_owned()
                } else {
                    "python3".to_string()
                };
                shell
                    .command(python_cmd)
                    .args([
                        "-m",
                        "uvicorn",
                        "server:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8765",
                    ])
                    .current_dir(src_python)
                    .spawn()
                    .expect("failed to spawn python sidecar")
            } else {
                // Release: the bundled PyInstaller binary. It owns its own
                // config/data paths (%APPDATA%/com.michael.workspace).
                shell
                    .sidecar("workspace-sidecar")
                    .expect("sidecar binary not bundled")
                    .spawn()
                    .expect("failed to spawn bundled sidecar")
            };

            // Forward sidecar stdout/stderr to the Tauri console so you can see
            // fetch progress and tracebacks during development.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            // Update check — release builds only; dev has no signed artifacts.
            if !cfg!(debug_assertions) {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
                    use tauri_plugin_updater::UpdaterExt;
                    let Ok(updater) = handle.updater() else { return };
                    let Ok(Some(update)) = updater.check().await else { return };
                    let msg = format!(
                        "Version {} is available (you have {}).\n\nInstall and restart?",
                        update.version, update.current_version
                    );
                    let install = handle
                        .dialog()
                        .message(msg)
                        .title("Workspace update")
                        .buttons(MessageDialogButtons::OkCancelCustom(
                            "Install".into(),
                            "Later".into(),
                        ))
                        .blocking_show();
                    if install {
                        if update.download_and_install(|_, _| {}, || {}).await.is_ok() {
                            handle.restart();
                        }
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
