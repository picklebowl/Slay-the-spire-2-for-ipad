import { useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { openUrl } from '@tauri-apps/plugin-opener';
import { load } from '@tauri-apps/plugin-store';
import { AppleID } from './AppleID';
import { Device, DeviceInfo } from './Device';
import './Sts2Assistant.css';

type Mode = 'install' | 'renew';
type Report = { installed?: boolean; bundle_id?: string; developer_mode?: boolean; ipa_path?: string;
  backup_folder?: string; backup_files?: number; resource_verified?: boolean; saves_preserved?: boolean; driver_ready?: boolean };
const action = (name: string, args: Record<string, unknown> = {}) => invoke<Report>('sts2_action', {
  action: name, udid: null, game: null, expectedBundle: null, backupFolder: null, ...args,
});

export default function App() {
  const [loggedInAs, setLoggedInAs] = useState<string | null>(null);
  const [device, setDevice] = useState<DeviceInfo | null>(null);
  const [noKeyring, setNoKeyring] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{mode: Mode; ipa: string} | null>(null);
  const [message, setMessage] = useState('用 USB 连接 iPad，解锁并确认“信任此电脑”。首次安装前，电脑须已安装 Steam 游戏。');
  const [progress, setProgress] = useState<number | null>(null);
  const [gameFolder, setGameFolder] = useState('');
  const [closed, setClosed] = useState(false);
  const [lastSuccess, setLastSuccess] = useState('');
  const [backupFolder, setBackupFolder] = useState('');
  const [error, setError] = useState(false);
  const [stage, setStage] = useState(0);
  const lock = useRef(false);
  const refresh = useRef<(() => void) | null>(null);

  useEffect(() => {
    invoke<boolean>('keyring_available').then(v => setNoKeyring(!v)).catch(() => setNoKeyring(true));
    load('preferences.json').then(async s => setLastSuccess((await s.get<string>('sts2LastSuccess')) ?? ''));
    let dispose: (() => void) | undefined;
    listen<{message: string; percent?: number}>('sts2-progress',e => {
      setMessage(e.payload.message);setProgress(e.payload.percent ?? null);
    }).then(fn => { dispose = fn; });
    return () => dispose?.();
  }, []);

  const fail = (e: unknown) => {
    setError(true);setMessage(typeof e === 'string' ? e : '操作未完成，请检查网络、USB 连接和设备解锁状态后重试。');
    setPending(null);setProgress(null);
  };

  async function start(mode: Mode) {
    if (lock.current || pending) return;
    if (!closed) {setError(true);setMessage('请先在 iPad 保存退出并关闭游戏，再勾选下方确认。');return;}
    lock.current=true;setBusy(true);setError(false);setStage(1);setProgress(null);
    try {
      setMessage('正在检查电脑环境。缺少 Apple 组件时会自动下载，请亲自确认 Windows 管理员授权。');
      const env=await action('environment');
      if (!env.driver_ready) await invoke('sts2_driver_setup');
      refresh.current?.();
      setStage(2);setMessage(mode==='install'?'正在识别游戏并准备安装文件。':'正在校验续签安装包；不会重新生成或传输资源。');
      const files=await action(mode==='install'?'prepare':'payload',{game:gameFolder || null});
      if (!files.ipa_path) throw '安装包未准备完成，请重新下载助手。';
      if (!loggedInAs) {
        const prefs=await load('preferences.json');const saved=await load('data.json');
        const email=await prefs.get<string>('sts2Account');const ids=(await saved.get<string[]>('ids'))??[];
        const storedEmail=email ? ids.find(id=>id.toLowerCase()===email.toLowerCase()) : undefined;
        if (storedEmail && !noKeyring) {
          setMessage('正在使用你此前明确保存的账号续签。若 Apple 要求验证，请亲自完成。');
          try {
            await invoke('login_stored',{email:storedEmail,anisetteServer:'ani.sidestore.io'});
            setLoggedInAs(await invoke<string>('logged_in_as'));
          } catch { setMessage('保存的登录暂不可用，请在账号区域亲自登录并完成验证。'); }
        }
      }
      setPending({mode,ipa:files.ipa_path});
      setMessage('文件已准备好。请完成账号登录和 USB 设备选择，助手随后自动继续。');
    } catch(e) { fail(e); }
    finally {lock.current=false;setBusy(false);}
  }

  async function finish(job: {mode: Mode; ipa: string}, target: DeviceInfo, account: string) {
    if (lock.current) return;
    lock.current=true;setBusy(true);setPending(null);setError(false);
    const udid=(target as DeviceInfo & {udid?: string}).udid;
    try {
      if (target.connectionType!=='USB' || !udid) throw '请选择通过 USB 连接的 iPad；不使用无线设备。';
      const prefs=await load('preferences.json');const original=await prefs.get<string>('sts2Account');
      if (job.mode==='renew' && original && original!==account) throw '续签必须使用上次安装的 Apple 账号。请切回原账号，再点击续签。';
      setStage(3);setMessage('正在检查 iPad，并在覆盖安装前备份现有存档。请保持接线。');
      const before=await action('inspect',{udid});
      if (job.mode==='renew' && !before.installed) throw 'iPad 尚未安装本项目游戏，请使用“一键安装”。';
      let backed: Report={};
      if (before.installed) {
        backed=await action('backup',{udid,expectedBundle:before.bundle_id});
        setBackupFolder(backed.backup_folder??'');
      }
      const activeAccount=await invoke<string>('logged_in_as');
      if (activeAccount!==account) throw '操作期间账号已改变，未开始签名，请重新选择原账号。';
      setStage(4);setMessage(job.mode==='renew'?'正在重新签名并覆盖安装游戏。不会卸载、导入存档或重传资源。':'正在签名并安装游戏。Apple 若要求验证，请在账号弹窗亲自完成。');
      await invoke('sideload_operation',{appPath:job.ipa});
      setStage(5);setMessage('安装已返回成功，正在独立检查应用和资源。请暂时不要打开游戏。');
      let after: Report;
      if (job.mode==='renew') {
        after=await action('renew-check',{udid,expectedBundle:before.bundle_id,backupFolder:backed.backup_folder});
      } else {
        after=await action('upload',{udid,expectedBundle:before.bundle_id || null});
        if (backed.backup_folder) await action('renew-check',{udid,expectedBundle:after.bundle_id,backupFolder:backed.backup_folder});
      }
      const stamp=new Date().toISOString();
      await prefs.set('sts2Account',account);await prefs.set('sts2LastSuccess',stamp);await prefs.save();
      setLastSuccess(stamp);setStage(6);setProgress(null);
      setMessage(after.developer_mode
        ? (job.mode==='renew'?'续签成功，已确认同一应用及原存档保留。可以拔线离线游玩。':'安装和资源校验完成，可以拔线。首次预热完成后，彻底关闭再重开游戏。')
        : '安装与资源已完成。请在 iPad 信任开发者，并到“隐私与安全性 → 开发者模式”开启、重启及确认。');
    } catch(e) {fail(e);}
    finally {lock.current=false;setBusy(false);}
  }

  useEffect(() => {
    if (pending && loggedInAs && device && !busy) void finish(pending,device,loggedInAs);
  }, [pending, loggedInAs, device, busy]);

  return <main className="assistant">
    <header><span className="eyebrow">SLAY THE SPIRE 2 · IPAD</span><h1>连上 iPad，其余交给助手。</h1>
      <p>首次安装自动准备工具和游戏资源。以后接回 USB，点击续签，保留现有存档。</p></header>
    <div className="steps" aria-label="安装步骤">{['电脑环境','游戏文件','存档备份','签名安装','资源校验','完成'].map((s,i)=><span key={s} className={stage>i?'done':''}>{i+1}. {s}</span>)}</div>
    <section className={'status '+(error?'error':'')} role="status" aria-live="polite"><strong>{message}</strong>
      {progress!==null && <progress max={100} value={progress} />}
      {lastSuccess && <small>上次成功：{new Date(lastSuccess).toLocaleString()}。免费签名约 7 天有效，请到期前续签。</small>}
    </section>
    <section className="actions"><label><input type="checkbox" checked={closed} disabled={busy||!!pending} onChange={e=>setClosed(e.target.checked)} />我已在 iPad 保存退出并关闭游戏</label>
      <div><button className="primary" disabled={busy||!!pending} onClick={()=>void start('install')}>一键安装 / 配置</button>
        <button disabled={busy||!!pending} onClick={()=>void start('renew')}>一键续签</button>
        {pending && <button onClick={()=>{setPending(null);setMessage('已取消等待，没有开始签名。');}}>取消等待</button>}</div>
      <small>安装时需要电脑已购买并安装匹配版本的 Steam 游戏；续签只需本助手、联网电脑和 USB。密码与验证码由你亲自输入。</small>
    </section>
    <div className="columns"><section className={busy?'account-column busy':'account-column'}><h2>1 · Apple 账号</h2>
      <p>首次登录并完成双重验证。选择保存登录后，后续续签可自动登录；Apple 仍可能要求再次验证。</p>
      <AppleID loggedInAs={loggedInAs} setLoggedInAs={setLoggedInAs} noKeyringAvailable={noKeyring} />
    </section><section className="device-column" inert={busy}><h2>2 · USB iPad</h2>
      <p>解锁后点“信任此电脑”。只连接一台时会自动选择；首次开启开发者模式仍需在 iPad 上完成。</p>
      <Device selectedDevice={device} setSelectedDevice={setDevice} registerRefresh={fn=>{refresh.current=fn??null;}} />
      <details><summary>未自动找到 Steam 游戏？</summary><p>{gameFolder||'默认自动识别 Steam 安装目录和其他库。'}</p>
        <button disabled={busy||!!pending} onClick={async()=>{const path=await open({directory:true,multiple:false,title:'选择 Slay the Spire 2 游戏文件夹'});if(typeof path==='string')setGameFolder(path);}}>选择游戏文件夹</button></details>
      {backupFolder && <p className="backup">本次存档备份已保留在：<code>{backupFolder}</code></p>}
    </section></div>
    <footer><p>支持 Windows 10/11 x64 · 已验证游戏 v0.111.0 · 无需 Mac、越狱或 JIT。免费签名到期前需联网续签，游玩可离线。</p>
      <button onClick={()=>void openUrl('https://github.com/picklebowl/Slay-the-spire-2-for-ipad')}>项目与使用说明</button>
      <button onClick={()=>void openUrl('https://github.com/nab138/iloader')}>基于 iloader 开源签名流程 · 非官方产品</button></footer>
  </main>;
}
