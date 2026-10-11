#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TOOLS="$RUNNER_TEMP/sts2-tools"
mkdir -p "$TOOLS" ios-export/addons
BASE='https://github.com/godotengine/godot/releases/download/4.5.1-stable'
curl -fL --retry 3 "$BASE/Godot_v4.5.1-stable_mono_macos.universal.zip" -o "$TOOLS/godot.zip"
curl -fL --retry 3 "$BASE/Godot_v4.5.1-stable_mono_export_templates.tpz" -o "$TOOLS/templates.tpz"
curl -fL --retry 3 "$BASE/SHA512-SUMS.txt" -o "$TOOLS/SHA512-SUMS.txt"
python3 - "$TOOLS" <<'PY'
import hashlib,sys
from pathlib import Path
d=Path(sys.argv[1]); sums=d.joinpath('SHA512-SUMS.txt').read_text()
for local,name in [('godot.zip','Godot_v4.5.1-stable_mono_macos.universal.zip'),('templates.tpz','Godot_v4.5.1-stable_mono_export_templates.tpz')]:
    matching=[line for line in sums.splitlines() if line.split()[-1].lstrip('*')==name]
    assert len(matching)==1,name
    assert hashlib.file_digest(d.joinpath(local).open('rb'),'sha512').hexdigest()==matching[0].split()[0]
PY
unzip -q "$TOOLS/godot.zip" -d "$TOOLS/godot"
GODOT_APP=$(find "$TOOLS/godot" -name '*.app' -type d | head -1)
GODOT_BIN="$GODOT_APP/Contents/MacOS/Godot"
test -x "$GODOT_BIN"
echo "GODOT_BIN=$GODOT_BIN" >> "$GITHUB_ENV"
TEMPLATES="$HOME/Library/Application Support/Godot/export_templates/4.5.1.stable.mono"
mkdir -p "$TEMPLATES"
unzip -q "$TOOLS/templates.tpz" 'templates/ios.zip' 'templates/version.txt' -d "$TOOLS/template-unpack"
cp "$TOOLS/template-unpack/templates/ios.zip" "$TEMPLATES/"
cp "$TOOLS/template-unpack/templates/version.txt" "$TEMPLATES/"
dotnet nuget add source "$GODOT_APP/Contents/Resources/GodotSharp/Tools/nupkgs" --name GodotLocal
curl -fL --retry 3 'https://github.com/utopia-rise/fmod-gdextension/releases/download/6.1.0-4.5.0/addons.zip' -o "$TOOLS/fmod.zip"
curl -fL --retry 3 'https://spine-godot.s3.eu-central-1.amazonaws.com/4.2/4.5.1-stable/spine-godot-extension-4.2-4.5.1-stable.zip' -o "$TOOLS/spine.zip"
unzip -q "$TOOLS/fmod.zip" -d "$TOOLS/fmod"
unzip -q "$TOOLS/spine.zip" -d "$TOOLS/spine"
cp -R "$TOOLS/fmod/fmod" ios-export/addons/fmod
cp -R "$TOOLS/spine/bin" ios-export/addons/spine
# Match the game's lowercase ios path on case-sensitive file systems.
if [ -d ios-export/addons/fmod/libs/iOS ]; then
  mv ios-export/addons/fmod/libs/iOS ios-export/addons/fmod/libs/ios
fi
python3 - <<'PY'
from pathlib import Path
p=Path('ios-export/addons/fmod/fmod.gdextension')
p.write_text(p.read_text().replace('libs/iOS','libs/ios'))
sp=Path('ios-export/addons/spine/spine_godot_extension.gdextension')
assert sp.is_file(), 'Spine extension descriptor missing'
for required in [
 'ios-export/addons/fmod/libs/ios/libGodotFmod.ios.template_release.xcframework',
 'ios-export/addons/fmod/libs/ios/libfmod_iphoneos.a',
 'ios-export/addons/fmod/libs/ios/libfmodstudio_iphoneos.a',
 'ios-export/addons/spine/ios/libspine_godot.ios.template_release.framework']:
 assert Path(required).exists(), required
PY
"$GODOT_BIN" --version
xcodebuild -version
