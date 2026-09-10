// Workspace — Tauri entry point.
//
// On launch this spawns the Python sidecar (the FastAPI server) as a child
// process and hands it to the app to manage. The webview then loads the React
// frontend, which talks to the sidecar over http://127.0.0.1:8765.
//
// In dev (`npm run tauri dev`) the sidecar is started from the python source
// via the shell plugin. For a packaged build you'd bundle a PyInstaller binary
// as a Tauri "sidecar" and launch that instead — noted in README.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Launch the FastAPI sidecar. In dev we run the interpreter against
            // the source tree; the working directory is the project root.
            let shell = app.shell();
            let (mut rx, _child) = shell
                .command("python3")
                .args([
                    "-m",
                    "uvicorn",
                    "server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8765",
                ])
                .current_dir(
                    std::env::current_dir()
                        .unwrap()
                        .join("../src-python"),
                )
                .spawn()
                .expect("failed to spawn python sidecar");

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

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
