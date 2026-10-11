param([string]$Cache = $env:STS2_DRIVER_CACHE)
$ErrorActionPreference = 'Stop'
if (!$Cache) { throw 'Missing assistant cache directory' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$service = Get-Service -Name 'Apple Mobile Device Service' -ErrorAction SilentlyContinue
if ($service -and $service.Status -eq 'Running') { exit 0 }
New-Item -ItemType Directory -Path $Cache -Force | Out-Null
$setup = Join-Path $Cache 'iTunes64Setup.exe'
$expected = '25b28905a81406a5edbf482f7f3ee4831a8641d32d29dceda5d1eb3e8d534c08'
if (!(Test-Path -LiteralPath $setup) -or (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash.ToLowerInvariant() -ne $expected) {
    $partial = Join-Path $Cache 'iTunes64Setup.download'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.apple.com/itunes/download/win64' -OutFile $partial
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Apple 安装包与已验证版本不同。未运行，请等待助手更新。'
    }
    Move-Item -LiteralPath $partial -Destination $setup -Force
}
$signature = Get-AuthenticodeSignature -LiteralPath $setup
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(?:CN|O)=Apple Inc\.') {
    throw 'Apple 数字签名校验失败，未运行安装程序。'
}
# Windows displays its own UAC prompt. This app never accepts it for the user.
$process = Start-Process -FilePath $setup -ArgumentList '/passive' -Verb RunAs -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -eq 3010) { exit 3010 }
if ($process.ExitCode -ne 0) { throw ('Apple 组件安装失败，代码：'+$process.ExitCode) }
$service = Get-Service -Name 'Apple Mobile Device Service' -ErrorAction SilentlyContinue
if (!$service -or $service.Status -ne 'Running') { throw 'Apple 设备服务未运行，请重启电脑后再次检查。' }
