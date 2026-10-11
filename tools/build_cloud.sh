#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORK="$ROOT/work"
EXPORT="$ROOT/ios-export"
mkdir -p "$WORK" "$EXPORT/prebuilt/deps" "$ROOT/build"
python3 - <<'PY'
import hashlib,json,zipfile
from pathlib import Path
m=json.loads(Path('private-inputs-manifest.json').read_text())
p=Path('private-build-inputs.zip')
assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==m['sha256']
with zipfile.ZipFile(p) as z:
    for n in z.namelist():
        assert not Path(n).is_absolute() and '..' not in Path(n).parts
    z.extractall('work/input')
PY
GAME="$WORK/input/game-refs"
dotnet build src/STS2MobileIos -c Release -p:GameRefsDir="$GAME" -o "$WORK/patch-out"
dotnet run --project src/STS2Weaver -c Release -- "$GAME/sts2.dll" \
  "$WORK/patch-out/STS2MobileIos.dll" src/STS2MobileIos/manifest.json "$EXPORT/prebuilt/sts2.dll"
cp "$WORK/patch-out/STS2MobileIos.dll" "$EXPORT/prebuilt/deps/"
for dll in "$GAME"/*.dll; do
  case "$(basename "$dll")" in sts2.dll|GodotSharp.dll) continue;; esac
  cp "$dll" "$EXPORT/prebuilt/deps/"
done
python3 - <<'PY'
import re
from pathlib import Path
b=Path('ios-export/prebuilt/sts2.dll').read_bytes()
paths=sorted(set(p.decode() for p in re.findall(rb'res://[A-Za-z0-9_/.]+\.cs',b)))
assert len(paths)>600
Path('build/cs_paths.txt').write_text('\n'.join(paths)+'\n')
PY
dotnet publish "$EXPORT/sts2.csproj" -c ExportRelease -r ios-arm64 \
  -p:GodotTargetPlatform=ios --self-contained
PUB="$EXPORT/.godot/mono/temp/bin/ExportRelease/ios-arm64/publish/sts2.dylib"
test -s "$PUB"
file "$PUB" | grep -q arm64
"$GODOT_BIN" --headless --editor --import --path "$EXPORT"
# Godot may attempt signing after generating the Xcode project; this build's
# archive is signed on the user's device instead. Require the project itself.
"$GODOT_BIN" --headless --path "$EXPORT" --export-release iOS "$ROOT/build/StS2.ipa" || {
  test -d "$ROOT/build/StS2.xcodeproj" || exit 1
}
python3 tools/prepare_xcode.py build
cd "$ROOT/build"
xcodebuild -project StS2.xcodeproj -scheme StS2 -configuration Release \
  -destination 'generic/platform=iOS' -archivePath StS2.xcarchive archive \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY='' \
  DEVELOPMENT_TEAM='' CODE_SIGN_STYLE=Manual
cd "$ROOT"
python3 tools/package_ipa.py build/StS2.xcarchive build/StS2-iPad-unsigned.ipa
