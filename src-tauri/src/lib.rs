use std::{
    io::{BufRead, BufReader},
    net::TcpStream,
    process::{Child, Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Mutex},
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::DialogExt;

// Only native dialogs and native drop events may mint file-selection tickets.
struct NativeSelections(std::path::PathBuf);
struct SafeExit(AtomicBool);

fn active_job_count(directory: &std::path::Path) -> u64 {
    let Ok(entries) = std::fs::read_dir(directory) else { return 0; };
    entries.filter_map(Result::ok).filter(|entry| {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        name == "active-jobs.json" || (name.starts_with("active-jobs-") && name.ends_with(".json"))
    }).map(|entry| {
        std::fs::read_to_string(entry.path()).ok()
            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
            .and_then(|value| value.get("active").and_then(|count| count.as_u64()))
            .unwrap_or(1)
    }).sum()
}

fn request_safe_exit(app: &tauri::AppHandle) {
    if app.state::<SafeExit>().0.swap(true, Ordering::SeqCst) { return; }
    if active_job_count(&app.state::<NativeSelections>().0) == 0 {
        begin_safe_exit(app);
        return;
    }
    let english = interface_language() == "en";
    let handle = app.clone();
    app.dialog().message(if english {
        "A tool is running. Finish the current item, stop remaining items, then quit?"
    } else {
        "工具仍在运行。是否等待当前文件处理完成，停止后续任务后退出？"
    }).title("Calabash").buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom(
        if english { "Stop safely and quit" } else { "安全停止后退出" }.into(),
        if english { "Stay" } else { "暂不退出" }.into(),
    )).show(move |confirmed| {
        if !confirmed {
            handle.state::<SafeExit>().0.store(false, Ordering::SeqCst);
            return;
        }
        begin_safe_exit(&handle);
    });
}

fn backend_running(app: &tauri::AppHandle) -> bool {
    let Some(backend) = app.try_state::<BackendProcess>() else { return false; };
    let Ok(mut child) = backend.0.lock() else { return true; };
    child.as_mut().is_some_and(|process| !matches!(process.try_wait(), Ok(Some(_))))
}

fn begin_safe_exit(handle: &tauri::AppHandle) {
    let handle = handle.clone();
    let english = interface_language() == "en";
    let directory = handle.state::<NativeSelections>().0.clone();
    if std::fs::write(directory.join("stop-jobs"), b"").is_err() {
        handle.state::<SafeExit>().0.store(false, Ordering::SeqCst);
        handle.dialog().message(if english { "Unable to stop safely. Keep the app open and cancel from the tool." } else { "无法安全停止，请保持应用打开并在工具中取消任务。" }).show(|_| {});
        return;
    }
    thread::spawn(move || {
        while !directory.join("exit-ready").is_file() && backend_running(&handle) {
            thread::sleep(Duration::from_millis(200));
        }
        handle.exit(0);
    });
}

#[cfg(target_os = "macos")]
fn install_safe_app_menu(app: &tauri::App) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
    let menu = Menu::default(app.handle())?;
    let quit = MenuItem::with_id(app, "safe-quit", "Quit Calabash", true, Some("CmdOrCtrl+Q"))?;
    let application = Submenu::with_items(app, "Calabash", true, &[
        &PredefinedMenuItem::about(app, None, None)?,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::services(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::hide(app, None)?,
        &PredefinedMenuItem::hide_others(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &quit,
    ])?;
    // Preserve the standard File/Edit/View/Window menus. Native terminate:
    // bypasses ExitRequested, so the application menu uses an explicit event.
    menu.remove_at(0)?;
    menu.insert(&application, 0)?;
    app.set_menu(menu)?;
    Ok(())
}

impl Drop for NativeSelections {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn selection_ticket(
    app: &tauri::AppHandle,
    paths: Vec<std::path::PathBuf>,
) -> Result<String, String> {
    write_selection_ticket(&app.state::<NativeSelections>().0, paths)
}

fn write_selection_ticket(
    directory: &std::path::Path,
    paths: Vec<std::path::PathBuf>,
) -> Result<String, String> {
    use std::io::Write;
    if paths.len() > 20 {
        return Err("limit".into());
    }
    let token = uuid::Uuid::new_v4().simple().to_string();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "clock")?
        .as_secs_f64();
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let path = directory.join(format!("{token}.json"));
    let mut file = options.open(&path).map_err(|_| "ticket")?;
    let payload = serde_json::json!({"paths": paths, "created": now});
    if file.write_all(payload.to_string().as_bytes()).is_err() {
        let _ = std::fs::remove_file(path);
        return Err("ticket".into());
    }
    Ok(token)
}

#[tauri::command]
async fn select_chat_files(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let Some(files) = app.dialog().file().blocking_pick_files() else {
            return Ok(None);
        };
        let paths = files
            .into_iter()
            .map(|file| file.into_path().map_err(|_| "path".to_string()))
            .collect::<Result<Vec<_>, _>>()?;
        selection_ticket(&app, paths).map(Some)
    })
    .await
    .map_err(|_| "picker".to_string())?
}

struct BackendProcess(Mutex<Option<Child>>);

#[tauri::command]
async fn save_tool_output(app: tauri::AppHandle, ticket: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        if ticket.len() != 32 || !ticket.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("ticket".into());
        }
        let path = app
            .state::<NativeSelections>()
            .0
            .join(format!("output-{ticket}.json"));
        let claimed = path.with_extension("claimed");
        std::fs::rename(&path, &claimed).map_err(|_| "ticket")?;
        let data = std::fs::read(&claimed);
        let _ = std::fs::remove_file(&claimed);
        let data: serde_json::Value =
            serde_json::from_slice(&data.map_err(|_| "ticket")?).map_err(|_| "ticket")?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "clock")?
            .as_secs_f64();
        let age = now - data["created"].as_f64().ok_or("ticket")?;
        if !(0.0..=300.0).contains(&age) {
            return Err("expired".into());
        }
        let source = std::path::PathBuf::from(data["path"].as_str().ok_or("ticket")?);
        let metadata = std::fs::symlink_metadata(&source).map_err(|_| "source")?;
        if !metadata.is_file() || metadata.len() != data["size"].as_u64().ok_or("ticket")? {
            return Err("source".into());
        }
        let mut input = std::fs::File::open(&source).map_err(|_| "source")?;
        let name = source
            .file_name()
            .ok_or("source")?
            .to_string_lossy()
            .to_string();
        let Some(destination) = app.dialog().file().set_file_name(name).blocking_save_file() else {
            return Ok(());
        };
        let destination = destination.into_path().map_err(|_| "destination")?;
        let current = input.metadata().map_err(|_| "source")?;
        if current.len() != metadata.len() || current.modified().ok() != metadata.modified().ok() {
            return Err("source_changed".into());
        }
        // Even a confirmed dialog cannot overwrite source files or existing results.
        let mut output = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&destination)
            .map_err(|_| "exists_or_denied")?;
        if std::io::copy(&mut input, &mut output)
            .and_then(|_| output.sync_all())
            .is_err()
            || input
                .metadata()
                .map(|after| {
                    after.len() != current.len() || after.modified().ok() != current.modified().ok()
                })
                .unwrap_or(true)
        {
            drop(output);
            let _ = std::fs::remove_file(destination);
            return Err("copy".into());
        }
        Ok(())
    })
    .await
    .map_err(|_| "save".to_string())?
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        self.shutdown();
    }
}

impl BackendProcess {
    fn shutdown(&self) {
        let Ok(mut child) = self.0.lock() else {
            return;
        };
        let Some(mut child) = child.take() else {
            return;
        };
        terminate_backend(&mut child);
    }
}

#[cfg(dev)]
fn project_root_path() -> Result<std::path::PathBuf, String> {
    let manifest_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "failed to resolve project root".to_string())
}

fn wait_for_backend(url: &tauri::Url) {
    let Some(host) = url.host_str() else {
        return;
    };
    let Some(port) = url.port_or_known_default() else {
        return;
    };
    let address = format!("{host}:{port}");
    for _ in 0..100 {
        if TcpStream::connect(&address).is_ok() {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(unix)]
fn isolate_backend_process(command: &mut Command) {
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) == 0 {
                Ok(())
            } else {
                Err(std::io::Error::last_os_error())
            }
        });
    }
}

#[cfg(not(unix))]
fn isolate_backend_process(_command: &mut Command) {}

#[cfg(unix)]
fn terminate_backend(child: &mut Child) {
    let pid = child.id() as libc::pid_t;
    unsafe {
        let _ = libc::kill(-pid, libc::SIGTERM);
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    unsafe {
        let _ = libc::kill(-pid, libc::SIGKILL);
    }
    let _ = child.wait();
}

#[cfg(not(unix))]
fn terminate_backend(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(dev)]
fn backend_command(_app: &tauri::App) -> Result<Command, String> {
    let root = project_root_path()?;
    let mut command = Command::new("uv");
    command
        .args([
            "run",
            "python",
            "-m",
            "backend.desktop_server",
            "--print-ready",
        ])
        .current_dir(root);
    Ok(command)
}

#[cfg(not(dev))]
fn backend_command(_app: &tauri::App) -> Result<Command, String> {
    let executable_dir = std::env::current_exe()
        .map_err(|error| format!("failed to resolve current executable path: {error}"))?
        .parent()
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "failed to resolve current executable directory".to_string())?;
    let binary_name = if cfg!(windows) {
        "calabash-backend.exe"
    } else {
        "calabash-backend"
    };
    let binary_path = executable_dir.join(binary_name);
    let mut command = Command::new(&binary_path);
    command.arg("--print-ready").current_dir(executable_dir);
    command.env("CALABASH_FRONTEND_RUNTIME", _app.path().resource_dir()
        .map_err(|error| error.to_string())?.join("frontend-runtime"));
    Ok(command)
}

fn start_backend(app: &tauri::App) -> Result<(), String> {
    let mut command = backend_command(app)?;
    command.env("CALABASH_SELECTION_DIR", &app.state::<NativeSelections>().0);
    isolate_backend_process(&mut command);
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("failed to start Calabash backend: {error}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to capture backend stdout".to_string())?;
    let stderr = child.stderr.take();

    app.manage(BackendProcess(Mutex::new(Some(child))));

    let app_handle = app.handle().clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut opened = false;
        for line in reader.lines().map_while(Result::ok) {
            if opened {
                continue;
            }
            let Some(payload) = line.strip_prefix("CALABASH_READY ") else {
                continue;
            };
            let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) else {
                continue;
            };
            let Some(url) = value.get("url").and_then(|url| url.as_str()) else {
                continue;
            };
            let Ok(parsed) = url.parse::<tauri::Url>() else {
                continue;
            };
            if parsed.scheme() != "http" || parsed.host_str() != Some("127.0.0.1") {
                continue;
            }
            // Native file permissions belong only to the host's exact origin,
            // never every loopback tool/preview process.
            let origin = format!("{}/*", parsed.as_str().trim_end_matches('/'));
            let capability = tauri::ipc::CapabilityBuilder::new("workspace-host")
                .local(false).window("main").remote(origin)
                .permission("allow-select-chat-files")
                .permission("allow-save-tool-output")
                .permission("dialog:allow-open")
                .permission("core:window:allow-start-dragging")
                .permission("core:window:allow-internal-toggle-maximize");
            if app_handle.add_capability(capability).is_err() { continue; }
            wait_for_backend(&parsed);
            let thread_handle = app_handle.clone();
            let window_handle = app_handle.clone();
            let _ = thread_handle.run_on_main_thread(move || {
                if let Some(window) = window_handle.get_webview_window("main") {
                    let _ = window.navigate(parsed);
                }
            });
            opened = true;
        }
    });

    if let Some(stderr) = stderr {
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for _ in reader.lines().map_while(Result::ok) {}
        });
    }

    Ok(())
}

#[tauri::command]
fn interface_language() -> String {
    let home = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE"));
    home.ok()
        .and_then(|home| {
            std::fs::read_to_string(std::path::Path::new(&home).join(".calabash/language.json"))
                .ok()
        })
        .and_then(|data| serde_json::from_str::<serde_json::Value>(&data).ok())
        .and_then(|value| {
            value
                .get("language")
                .and_then(|value| value.as_str())
                .map(str::to_owned)
        })
        .filter(|value| value == "en")
        .unwrap_or_else(|| "zh-CN".to_string())
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![interface_language, select_chat_files, save_tool_output])
        .plugin(tauri_plugin_dialog::init())
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "safe-quit" { app.exit(0); }
        })
        .setup(|app| {
            #[cfg(target_os = "macos")]
            install_safe_app_menu(app)?;
            let directory = std::env::temp_dir().join(format!("calabash-selections-{}", uuid::Uuid::new_v4()));
            std::fs::create_dir(&directory)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
            }
            app.manage(NativeSelections(directory));
            app.manage(SafeExit(AtomicBool::new(false)));
            start_backend(app).map_err(|error| Box::<dyn std::error::Error>::from(error))?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let active = active_job_count(&window.app_handle().state::<NativeSelections>().0);
                eprintln!("Calabash close requested; active tool tasks: {active}");
                api.prevent_close();
                request_safe_exit(window.app_handle());
                return;
            }
            let tauri::WindowEvent::DragDrop(event) = event else { return };
            let payload = match event {
                tauri::DragDropEvent::Drop { paths, position, .. } => match selection_ticket(window.app_handle(), paths.clone()) {
                    Ok(ticket) => serde_json::json!({"ticket": ticket, "position": {"x": position.x, "y": position.y}}),
                    Err(error) => serde_json::json!({"error": error}),
                },
                tauri::DragDropEvent::Enter { .. } | tauri::DragDropEvent::Over { .. } => serde_json::json!({"hover": true}),
                _ => serde_json::json!({"hover": false}),
            };
            if let Some(webview) = window.app_handle().get_webview_window(window.label()) {
                let _ = webview.eval(format!("window.dispatchEvent(new CustomEvent('calabash-native-files', {{detail: {payload}}}))"));
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Calabash desktop")
        .run(|app_handle, event| match event {
            RunEvent::ExitRequested { api, .. } => {
                let active = active_job_count(&app_handle.state::<NativeSelections>().0);
                eprintln!("Calabash exit requested; active tool tasks: {active}");
                if !app_handle.state::<NativeSelections>().0.join("exit-ready").is_file() && backend_running(app_handle) {
                    api.prevent_exit();
                    request_safe_exit(app_handle);
                } else if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                    backend.shutdown();
                }
            }
            RunEvent::Exit => {
                if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                    backend.shutdown();
                }
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn task_exit_guard_is_conservative_and_tracks_backend_completion() {
        let directory = std::env::temp_dir().join(format!("calabash-jobs-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&directory).unwrap();
        assert_eq!(active_job_count(&directory), 0);
        let file = directory.join("active-jobs.json");
        std::fs::write(&file, b"invalid").unwrap();
        assert_eq!(active_job_count(&directory), 1);
        std::fs::write(&file, br#"{"active":2}"#).unwrap();
        assert_eq!(active_job_count(&directory), 2);
        std::fs::write(&file, br#"{"active":0}"#).unwrap();
        assert_eq!(active_job_count(&directory), 0);
        std::fs::write(directory.join("active-jobs-one.json"), br#"{"active":1}"#).unwrap();
        std::fs::write(directory.join("active-jobs-two.json"), br#"{"active":2}"#).unwrap();
        assert_eq!(active_job_count(&directory), 3);
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn native_tickets_are_unique_bounded_and_private() {
        let directory =
            std::env::temp_dir().join(format!("calabash-ticket-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&directory).unwrap();
        let paths = vec![std::path::PathBuf::from("/test/office.xlsx")];
        let first = write_selection_ticket(&directory, paths.clone()).unwrap();
        let second = write_selection_ticket(&directory, paths.clone()).unwrap();
        assert_ne!(first, second);
        assert_eq!(first.len(), 32);
        let path = directory.join(format!("{first}.json"));
        let payload: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(payload["paths"][0], "/test/office.xlsx");
        assert!(payload["created"].as_f64().unwrap() > 0.0);
        assert_eq!(
            write_selection_ticket(&directory, vec![paths[0].clone(); 21]).unwrap_err(),
            "limit"
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        std::fs::remove_dir_all(directory).unwrap();
    }
}
