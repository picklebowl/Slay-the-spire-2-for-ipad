use serde_json::{json, Value};
use std::{path::PathBuf, process::Stdio};
use tauri::{AppHandle, Emitter, Manager};
use tokio::{io::{AsyncBufReadExt, BufReader}, process::Command};

fn payload_root() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|_| "无法找到助手文件夹。")?;
    Ok(exe.parent().ok_or("无法找到助手文件夹。")?.join("payload"))
}

#[tauri::command]
pub async fn sts2_action(handle: AppHandle, action: String, udid: Option<String>, game: Option<String>, expected_bundle: Option<String>, backup_folder: Option<String>) -> Result<Value, String> {
    let allowed = ["environment", "payload", "prepare", "inspect", "backup", "upload", "renew-check"];
    if !allowed.contains(&action.as_str()) { return Err("不支持此操作。".into()); }
    let root = payload_root()?;
    let state = handle.path().app_data_dir().map_err(|_| "无法创建助手数据目录。")?;
    let mut cmd = Command::new(root.join("python/python.exe"));
    cmd.arg(root.join("windows-assistant/backend.py")).arg(&action).arg("--state").arg(&state);
    if let Some(v) = udid { cmd.arg("--udid").arg(v); }
    if let Some(v) = game { if !v.is_empty() { cmd.arg("--game").arg(v); } }
    if let Some(v) = expected_bundle { cmd.arg("--expected-bundle").arg(v); }
    if let Some(v) = backup_folder { cmd.arg("--backup-folder").arg(v); }
    cmd.env("PYTHONIOENCODING", "utf-8").stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)] cmd.creation_flags(0x08000000);
    let mut child = cmd.spawn().map_err(|_| "助手运行文件不完整，请重新解压完整安装包。")?;
    let mut lines = BufReader::new(child.stdout.take().ok_or("无法读取操作状态。")?).lines();
    let mut result = None; let mut error = None;
    while let Some(line) = lines.next_line().await.map_err(|_| "读取操作状态失败。")? {
        if let Ok(value) = serde_json::from_str::<Value>(&line) {
            if let Some(v) = value.get("result") { result = Some(v.clone()); }
            if let Some(v) = value.get("error").and_then(Value::as_str) { error = Some(v.to_string()); }
            if value.get("message").is_some() { let _ = handle.emit("sts2-progress", value); }
        }
    }
    let status = child.wait().await.map_err(|_| "操作未能结束。")?;
    if !status.success() { return Err(error.unwrap_or_else(|| "操作未完成，请检查连接后重试。".into())); }
    result.ok_or_else(|| "没有收到操作结果，请勿拔线，先重新检查。".into())
}

#[tauri::command]
pub async fn sts2_driver_setup(handle: AppHandle) -> Result<Value, String> {
    let cache=handle.path().app_data_dir().map_err(|_| "无法创建下载目录。")?.join("downloads");
    let mut cmd=Command::new("powershell.exe");
    cmd.args(["-NoProfile","-NonInteractive","-Command",include_str!("sts2-driver.ps1")]).env("STS2_DRIVER_CACHE",cache);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)] cmd.creation_flags(0x08000000);
    let status=cmd.status().await.map_err(|_| "无法启动 Apple 组件安装。")?;
    match status.code() {
        Some(0) => Ok(json!({"driver_ready":true})),
        Some(3010) => Err("Apple 组件安装完成，请先重启电脑，再打开助手。".into()),
        _ => Err("Apple 组件未安装完成。请检查网络和 Windows 管理员授权，再重试。安装包变化时助手会停止运行以保护电脑。".into())
    }
}
