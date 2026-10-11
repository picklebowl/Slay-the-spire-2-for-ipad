"""Apply a bounded patch to the pinned MIT iloader source, never a live installation."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

PIN='dc396af059fd46982062cd8fc90252d7e27085e9'
HERE=Path(__file__).resolve().parent

def replace(file,before,after):
    s=file.read_text(encoding='utf-8')
    assert s.count(before)==1,(file,before)
    file.write_text(s.replace(before,after),encoding='utf-8',newline='\n')

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args();src=a.source.resolve()
    head=subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD'],text=True).strip()
    assert head==PIN,'Only the audited pinned upstream is accepted'
    shutil.copy2(HERE/'App.tsx',src/'src/App.tsx')
    shutil.copy2(HERE/'Sts2Assistant.css',src/'src/Sts2Assistant.css')
    shutil.copy2(HERE/'sts2.rs',src/'src-tauri/src/sts2.rs')
    shutil.copy2(HERE/'driver-setup.ps1',src/'src-tauri/src/sts2-driver.ps1')
    replace(src/'src-tauri/src/lib.rs','mod operation;','mod operation;\nmod sts2;')
    replace(src/'src-tauri/src/lib.rs','.plugin(tauri_plugin_process::init())',
            '.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {\n                if let Some(w) = app.get_webview_window("main") { let _ = w.set_focus(); }\n            }))\n        .plugin(tauri_plugin_process::init())')
    replace(src/'src-tauri/src/lib.rs','            login_new,','            sts2::sts2_action,\n            sts2::sts2_driver_setup,\n            login_new,')
    cargo=src/'src-tauri/Cargo.toml'
    replace(cargo,'tokio = "1.49.0"','tokio = { version = "1.49.0", features = ["process", "io-util"] }\ntauri-plugin-single-instance = "2"')
    # Isolate this product's keyring and settings from the official iloader.
    for file in [src/'src-tauri/src/account.rs',src/'src-tauri/src/secure_storage.rs']:
        text=file.read_text(encoding='utf-8').replace('"iloader"','"sts2-ipad-assistant"')
        file.write_text(text,encoding='utf-8',newline='\n')
    replace(src/'src/Device.tsx','if (devicesWithPairing.length > 0) {\n            selectDevice(devicesWithPairing[0]);\n          }',
            'const usb = devices.filter(d => d.connectionType === "USB");\n          if (!selectedDevice && usb.length === 1) selectDevice(usb[0]);')
    replace(src/'src/Device.tsx','const devicesWithPairing = await Promise.all(','await Promise.all(')
    replace(src/'src/i18next.ts','fallbackLng: "en",','lng: "zh_cn",\n    fallbackLng: "zh_cn",')
    config=src/'src-tauri/tauri.conf.json'; data=json.loads(config.read_text(encoding='utf-8'))
    data['productName']='StS2 iPad Assistant';data['version']='0.1.0';data['identifier']='com.picklebowl.sts2assistant'
    data['app']['windows'][0].update(title='杀戮尖塔2 · iPad 安装与续签助手',width=1120,height=840,minWidth=750,minHeight=600)
    data['bundle'].update(targets=['nsis'],createUpdaterArtifacts=False,resources={'../payload/':'payload/'})
    data['bundle']['windows']={'nsis':{'displayLanguageSelector':False,'languages':['SimpChinese'],'installMode':'currentUser'},'webviewInstallMode':{'type':'downloadBootstrapper'}}
    config.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    print('Applied StS2 assistant patch to pinned upstream '+PIN)

if __name__=='__main__':main()
