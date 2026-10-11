"""Own-game USB operations. No Apple credentials or uninstallation commands."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PREFIX = 'com.picklebowl.sts2.ipad'

def emit(message=None, **values):
    if message is not None: values['message'] = message
    print(json.dumps(values, ensure_ascii=False), flush=True)

def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def manifest(): return json.loads((ROOT/'windows-assistant/payload.json').read_text(encoding='utf-8'))

def payload():
    spec=manifest()
    ipa=checked_file(ROOT/'StS2-iPad-unsigned.ipa',spec['ipa_sha256'],spec['ipa_bytes'])
    return {'ipa_path':str(ipa),'game_version':spec['game_version']}

def checked_file(path, digest, size=None):
    path = Path(path)
    if not path.is_file() or (size is not None and path.stat().st_size != size) or sha(path) != digest:
        raise ValueError('文件校验不通过，请重新下载完整的安装助手。')
    return path

def game_roots():
    roots = []
    if os.name == 'nt':
        import winreg
        for hive, key, value in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as k: roots.append(Path(winreg.QueryValueEx(k,value)[0]))
            except OSError: pass
    roots.append(Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Steam')
    libraries = list(roots)
    for steam in roots:
        vdf = steam/'steamapps/libraryfolders.vdf'
        if vdf.is_file():
            for item in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"',vdf.read_text(encoding='utf-8')):
                libraries.append(Path(item.replace('\\\\','\\')))
    return list(dict.fromkeys(p/'steamapps/common/Slay the Spire 2' for p in libraries))

def validate_game(game):
    game = Path(game).resolve()
    info = game/'release_info.json'
    if not info.is_file(): raise ValueError('未找到 Steam 游戏。请先在电脑安装《杀戮尖塔2》，或选择游戏文件夹。')
    if json.loads(info.read_text(encoding='utf-8'))['version'] != manifest()['game_version']:
        raise ValueError('游戏版本与安装包不匹配。本助手支持 '+manifest()['game_version']+'；请等待配套新版，不能混用资源。')
    checked_file(game/'data_sts2_windows_x86_64/sts2.dll',manifest()['original_assembly_sha256'])
    return game

def detect_game(supplied=None):
    if supplied: return validate_game(supplied)
    candidates = [p for p in game_roots() if (p/'release_info.json').is_file()]
    if len(candidates) != 1: raise ValueError('未能唯一识别 Steam 游戏目录，请点击“选择游戏文件夹”。')
    return validate_game(candidates[0])

def environment():
    available = False
    try:
        with socket.create_connection(('127.0.0.1',27015),timeout=2): available = True
    except OSError: pass
    return {'driver_ready':available,'game_detected':any((p/'release_info.json').is_file() for p in game_roots())}

def prepare(state, game=None):
    spec = manifest()
    ipa = checked_file(ROOT/'StS2-iPad-unsigned.ipa',spec['ipa_sha256'],spec['ipa_bytes'])
    cache = state/'content'; cache.mkdir(parents=True,exist_ok=True)
    resource = cache/'StS2.pck'
    if resource.is_file() and resource.stat().st_size == spec['resource_bytes'] and sha(resource)==spec['resource_sha256']:
        emit('已复用校验通过的资源，无需重新处理。')
    else:
        game = detect_game(game)
        if shutil.disk_usage(cache).free < 7*1024**3: raise ValueError('电脑可用空间不足，请至少腾出 7 GB。')
        emit('已找到匹配的 Steam 游戏，正在自动处理并校验资源。首次约需数分钟。')
        with tempfile.TemporaryDirectory(prefix='sts2-prepare-',dir=cache) as folder:
            staged = Path(folder)/'StS2.pck'
            run = subprocess.run([sys.executable,str(ROOT/'tools/prepare_content.py'),'--game',str(game),
                                  '--paths',str(ROOT/'cs_paths.txt'),'--out',str(staged)],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace')
            if run.returncode: raise ValueError('资源处理失败。请确认游戏版本一致、文件完整且磁盘空间充足。')
            checked_file(staged,spec['resource_sha256'],spec['resource_bytes'])
            if resource.exists(): resource.rename(cache/('StS2.previous-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.pck'))
            staged.replace(resource)
    return {'ipa_path':str(ipa),'resource_ready':True,'game_version':spec['game_version']}

def read_state(state):
    file = state/'device-state.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}

def write_state(state,data):
    state.mkdir(parents=True,exist_ok=True)
    temp = state/'device-state.json.tmp'
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(state/'device-state.json')

async def app_info(lockdown, required=False):
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    async with InstallationProxyService(lockdown) as apps:
        found = await apps.get_apps(application_type='User')
    matches = [(k,v) for k,v in found.items() if k==BUNDLE_PREFIX or k.startswith(BUNDLE_PREFIX+'.')]
    if len(matches)>1: raise ValueError('发现多个游戏副本。请先明确保留哪一份；助手不会自动删除应用。')
    if not matches:
        if required: raise ValueError('iPad 尚未安装本项目游戏，请先点击“一键安装”。')
        return None
    bundle,app = matches[0]
    if app.get('CFBundleShortVersionString') != manifest()['app_version']:
        raise ValueError('iPad 游戏与本助手版本不匹配，已停止操作以保护存档。')
    return bundle

async def remote_hash(afc,path,size):
    h=hashlib.sha256(); done=0
    file=await afc.fopen(path,'r')
    try:
        while done<size:
            block=await afc.fread(file,min(4*1024**2,size-done))
            if not block: raise ValueError('iPad 文件读回不完整，请重新连接 USB。')
            h.update(block); done+=len(block)
    finally: await afc.fclose(file)
    return h.hexdigest()

async def backup(afc,state):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root=state/'backups'/stamp; root.mkdir(parents=True)
    files=[]
    async def visit(folder,depth=0):
        if depth>12: raise ValueError('存档目录层级异常，已停止操作。')
        for name in await afc.listdir(folder):
            if name in ('.','..'): continue
            if '/' in name or '\\' in name: raise ValueError('存档路径异常，已停止操作。')
            path=posixpath.join(folder,name)
            stat=await afc.stat(path)
            if stat.get('st_ifmt')=='S_IFDIR': await visit(path,depth+1)
            else:
                if len(files)>=10000 or int(stat['st_size'])>64*1024**2: raise ValueError('存档规模异常，已停止操作。')
                data=await afc.get_file_contents(path)
                relative=path.removeprefix('/Documents/')
                target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
                files.append({'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    # Game saves/settings only. No device logs, pairing files or resource caches.
    if await afc.exists('/Documents/default'): await visit('/Documents/default')
    (root/'manifest.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'backup_files':len(files),'backup_folder':str(root)}

async def upload(afc,state):
    spec=manifest(); source=checked_file(state/'content/StS2.pck',spec['resource_sha256'],spec['resource_bytes'])
    active='/Documents/StS2.pck'
    if await afc.exists(active):
        size=int((await afc.stat(active))['st_size'])
        if size==spec['resource_bytes'] and await remote_hash(afc,active,size)==spec['resource_sha256']:
            return {'resource_verified':True,'resource_reused':True}
        raise ValueError('iPad 已有不同资源包。已停止写入，避免覆盖现有游戏。')
    # Only this helper's fixed, content-addressed temporary file is resumable.
    # Never truncate the active resource or any save. Single-instance UI prevents parallel writers.
    staged=active+'.uploading-assistant-'+spec['resource_sha256'][:16]
    done=0; mode='w'; percent=-1
    if await afc.exists(staged):
        length=int((await afc.stat(staged))['st_size'])
        if 0<=length<=spec['resource_bytes']:
            h=hashlib.sha256();remaining=length
            with source.open('rb') as f:
                while remaining:
                    data=f.read(min(4*1024**2,remaining));h.update(data);remaining-=len(data)
            if await remote_hash(afc,staged,length)==h.hexdigest():
                done=length;mode='a';emit('已校验中断的临时资源，继续传输。')
        if mode=='w': emit('助手自己的临时资源校验失败，将重新传输；原游戏资源和存档保持不变。')
    if done<spec['resource_bytes']:
        file=await afc.fopen(staged,mode)
        try:
            with source.open('rb') as f:
                f.seek(done)
                while data:=f.read(4*1024**2):
                    await afc.fwrite(file,data); done+=len(data)
                    current=int(done/spec['resource_bytes']*100)
                    if current//10 != percent:
                        percent=current//10; emit('正在通过 USB 传输资源。',percent=current)
        finally: await afc.fclose(file)
    if done!=spec['resource_bytes'] or await remote_hash(afc,staged,done)!=spec['resource_sha256']:
        raise ValueError('资源读回校验失败，未启用未完成资源。请重试并保持接线。')
    if await afc.exists(active): raise ValueError('传输期间已有资源出现，已停止覆盖。')
    await afc.rename(staged,active)
    return {'resource_verified':True,'resource_reused':False}

async def verify_backup(afc,state,folder):
    root=Path(folder).resolve()
    if not root.is_relative_to((state/'backups').resolve()): raise ValueError('备份目录无效，已停止检查。')
    entries=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for entry in entries:
        relative=entry['path']
        if not relative.startswith('default/') or '..' in relative.split('/') or '\\' in relative:
            raise ValueError('备份清单路径异常。')
        path='/Documents/'+relative
        if not await afc.exists(path) or int((await afc.stat(path))['st_size'])!=entry['bytes']:
            raise ValueError('续签后存档检查不一致，原档备份已保留，请勿卸载游戏。')
        if await remote_hash(afc,path,entry['bytes'])!=entry['sha256']:
            raise ValueError('续签后存档内容检查不一致，原档备份已保留，请勿卸载游戏。')
    return {'save_files_verified':len(entries),'saves_preserved':True}

async def device_action(action,state,udid,expected_bundle=None,backup_folder=None):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.house_arrest import HouseArrestService
    async with await create_using_usbmux(serial=udid,autopair=False,connection_type='USB',pairing_records_cache_folder=state/'pairing') as lockdown:
        bundle=await app_info(lockdown,required=action!='inspect')
        stored=read_state(state)
        expected=expected_bundle or stored.get('bundle_id')
        if expected and bundle and bundle!=expected: raise ValueError('签名身份与之前不同。已停止资源操作，请使用原 Apple 账号续签。')
        result={'installed':bundle is not None,'bundle_id':bundle,'developer_mode':await lockdown.get_developer_mode_status()}
        if bundle:
            async with await HouseArrestService.create(lockdown,bundle,documents_only=True) as afc:
                if action=='backup': result.update(await backup(afc,state))
                elif action=='upload': result.update(await upload(afc,state))
                if await afc.exists('/Documents/StS2.pck'): result['resource_present']=True
                if action=='renew-check':
                    # Renew never writes resources or saves; actual install has already returned success.
                    if not await afc.exists('/Documents/StS2.pck'): raise ValueError('续签后未找到资源，请保留当前应用并重新检查。')
                    result['resource_present']=True
                    if not backup_folder: raise ValueError('缺少本次续签前备份，不能确认存档保留。')
                    result.update(await verify_backup(afc,state,backup_folder))
        if action in ('upload','renew-check'):
            result['last_success_utc']=datetime.now(timezone.utc).isoformat()
            write_state(state,{'bundle_id':bundle,'last_success_utc':result['last_success_utc']})
        return result

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['environment','payload','prepare','inspect','backup','upload','renew-check'])
    p.add_argument('--state',type=Path,required=True);p.add_argument('--game');p.add_argument('--udid');p.add_argument('--expected-bundle');p.add_argument('--backup-folder')
    a=p.parse_args();a.state.mkdir(parents=True,exist_ok=True)
    if a.action=='environment': result=environment()
    elif a.action=='payload': result=payload()
    elif a.action=='prepare': result=prepare(a.state,a.game)
    else:
        if not a.udid or not re.fullmatch(r'[A-Za-z0-9-]{10,64}',a.udid): raise ValueError('请选择 USB 连接的 iPad。')
        result=asyncio.run(device_action(a.action,a.state,a.udid,a.expected_bundle,a.backup_folder))
    emit(result=result)

if __name__=='__main__':
    try: main()
    except Exception as e:
        # Do not emit arbitrary library diagnostics containing device IDs or pairing data.
        message=str(e) if isinstance(e,ValueError) else '设备通信失败。请解锁 iPad、确认“信任”、检查 USB 线，再重试。'
        emit(error=message);sys.exit(1)
