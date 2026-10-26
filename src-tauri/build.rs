fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "interface_language",
            "select_chat_files",
            "save_tool_output",
        ]),
    ))
    .expect("failed to build desktop permissions")
}
