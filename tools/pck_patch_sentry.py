#!/usr/bin/env python3
"""Patch a Godot 4.x GDPC v3 (unencrypted) pck to fully disable Sentry.

Three in-place edits (all offsets of untouched file data preserved):
  1. .godot/extension_list.cfg  -> drop the sentry.gdextension line (shrinks)
  2. project.binary             -> rename autoload key 'autoload/SentryInit'
                                    to 'xutoload/SentryInit' (same length) so
                                    Godot no longer runs the Sentry autoload,
                                    which would call the (now absent) native API.
  3. directory                  -> remove the addons/sentry/sentry.gdextension
                                    entry, fix sizes/md5 of the edited files,
                                    rewrite the directory (which lives at the
                                    end of the file) and truncate.

Usage: pck_patch_sentry.py <src.pck> <dst.pck>
"""
import struct, sys, os, shutil, hashlib

def u32(b, o): return struct.unpack_from("<I", b, o)[0]

def patch(src, dst):
    shutil.copyfile(src, dst)
    f = open(dst, "r+b")

    try:
        assert f.read(4) == b"GDPC", "bad magic"
        fmt = struct.unpack("<I", f.read(4))[0]
        assert fmt >= 3, f"only format v3+ supported, got {fmt}"
        f.read(12)                                    # version major/minor/patch
        flags = struct.unpack("<I", f.read(4))[0]
        assert not (flags & 1), "directory encrypted"
        files_base = struct.unpack("<Q", f.read(8))[0]
        dir_offset = struct.unpack("<Q", f.read(8))[0]
        rel = bool(flags & 2)
    
        f.seek(dir_offset)
        count = struct.unpack("<I", f.read(4))[0]
        entries = []  # [plen, pathbytes, off_stored, size, md5, eflags]
        for _ in range(count):
            plen = struct.unpack("<I", f.read(4))[0]
            pathb = f.read(plen)
            off = struct.unpack("<Q", f.read(8))[0]
            size = struct.unpack("<Q", f.read(8))[0]
            md5 = f.read(16)
            ef = struct.unpack("<I", f.read(4))[0]
            entries.append([plen, pathb, off, size, md5, ef])
        dir_end = f.tell()
    
        file_size = os.path.getsize(dst)
        assert dir_end == file_size, (
            f"directory is not the last section (dir_end={dir_end:#x}, "
            f"file_size={file_size:#x}); patcher assumption violated")
    
        def abs_off(o): return o + files_base if rel else o
        def pstr(pb): return pb.rstrip(b"\x00").decode("utf-8")
    
        ext = proj = None
        sentry_idx = None
        for i, e in enumerate(entries):
            p = pstr(e[1])
            if p == ".godot/extension_list.cfg": ext = e
            elif p == "project.binary": proj = e
            elif p == "addons/sentry/sentry.gdextension": sentry_idx = i
        assert ext is not None, "extension_list.cfg not found"
        assert proj is not None, "project.binary not found"
        assert sentry_idx is not None, "sentry.gdextension not found"
    
        # 1. extension_list.cfg: drop the sentry line
        o = abs_off(ext[2]); sz = ext[3]
        f.seek(o); old = f.read(sz)
        lines = [ln for ln in old.split(b"\n") if ln.strip() and b"sentry" not in ln]
        new = b"".join(ln + b"\n" for ln in lines)
        assert len(new) <= sz, "new extension_list larger than old"
        assert b"sentry" not in new and b"fmod" in new and b"spine" in new
        f.seek(o); f.write(new)
        ext[3] = len(new); ext[4] = hashlib.md5(new).digest()
        print(f"extension_list.cfg: {sz} -> {len(new)} bytes")
    
        # 2. project.binary: neutralize the SentryInit autoload key (same length)
        po = abs_off(proj[2]); psz = proj[3]
        f.seek(po); pdata = bytearray(f.read(psz))
        # v0.111.0 uses SentryBootstrap, earlier builds use SentryInit. Read ECFG
        # keys rather than guessing the name or replacing script-path bytes.
        assert pdata[:4] == b"ECFG", "project.binary must use ECFG"
        cursor = 8
        changed = []
        for _ in range(u32(pdata, 4)):
            length = u32(pdata, cursor); cursor += 4
            key_offset = cursor
            key = bytes(pdata[cursor:cursor + length]); cursor += length
            value_length = u32(pdata, cursor); cursor += 4
            value = bytes(pdata[cursor:cursor + value_length]); cursor += value_length
            assert cursor <= len(pdata), "ECFG property extends past end"
            if key.startswith(b"autoload/") and (
                b"sentry" in key.lower() or b"addons/sentry/" in value.lower()
            ):
                pdata[key_offset:key_offset + 8] = b"xutoload"
                changed.append(key.decode())
        assert changed, "Sentry autoload key not found in project.binary"
        f.seek(po); f.write(pdata)
        proj[4] = hashlib.md5(bytes(pdata)).digest()
        print(f"project.binary: disabled {changed} (same-length rename)")
    
        # 3. remove sentry.gdextension entry, rewrite directory, truncate
        del entries[sentry_idx]
        out = bytearray(struct.pack("<I", len(entries)))
        for plen, pathb, off, size, md5, ef in entries:
            out += struct.pack("<I", plen) + pathb
            out += struct.pack("<Q", off) + struct.pack("<Q", size) + md5
            out += struct.pack("<I", ef)
        f.seek(dir_offset); f.write(out); f.truncate(dir_offset + len(out))
        print(f"directory: {count} -> {len(entries)} entries, "
              f"file {file_size} -> {dir_offset + len(out)} bytes")
    finally:
        f.close()

if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
    print("OK")
