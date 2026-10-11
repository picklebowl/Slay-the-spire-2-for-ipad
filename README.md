# 杀戮尖塔2 iPad 离线移植

目标设备：iPad Air 2025，用户报告 iPadOS 26.6.1。
方案：Godot 4.5.1 + .NET 9 NativeAOT，单机、本地存档，不需要 JIT。
安装采用用户接受的免费签名侧载；免费签名周期约 7 天，需要定期联网续签。

目前状态：Windows 上补丁编译成功，针对用户 v0.111.0 程序集的 35 处静态修改成功。
云端 NativeAOT 编译、Xcode 归档、IPA 打包已通过：
[FMOD 修复版构建](https://github.com/picklebowl/Slay-the-spire-2-for-ipad/actions/runs/38117720910)。
IPA 为 56,808,716 字节，已校验 arm64 游戏原生库、FMOD/Spine 依赖、ZIP 与文件哈希。
真机已签名安装并完整校验 Documents 资源包，开发者模式已启用。
首次启动在 Godot 图标后闪退；设备崩溃栈指向 FMOD 插件加载入口，旧主程序缺少该动态导出。
已修正链接器保留、显式导出及归档符号清理设置，打包时必须检查真实 dyld 导出表。
修复版已独立确认插件加载入口位于 0x4018；覆盖安装和真机复测待完成。
离线游玩与性能测试仍待完成；编译存在 AOT 反射/动态代码告警，需通过实际玩法覆盖验证。

## 构建

本仓库必须为 Private。`private-build-inputs.zip` 包含用户自己的合法游戏程序集，
不能公开。约 2 GB 的 PCK 美术/音频内容不上传，也不嵌入安装包。

GitHub Actions 的 `Build offline iPad IPA` 在 macOS 运行器编译 AOT 并打包
`StS2-iPad-unsigned.ipa`。该 IPA 使用 ad-hoc 签名供侧载工具重新签名，不能直接装到普通 iPad。
已验证修复版 IPA SHA256：`5173e27191a37163b912e9a04df5a3a98f9dbf35cd16cd05b65c318844b21877`。
`application/app_store_team_id` 的零值仅用于无证书导出，不是用户的开发者身份。

## 安装和资源

1. 从私有 Actions 下载 IPA 和 `cs_paths.txt`。
2. 在 Windows 上运行 `python tools/prepare_content.py --game "你的Steam游戏目录" --paths "下载的cs_paths.txt" --out "本地StS2.pck"`。
3. 用 iloader 等工具以自己的 Apple ID 重新签名安装 IPA。
4. 通过 Apple Devices 文件共享，将处理后的 `StS2.pck` 放到 App 的 Documents。
5. 关闭 Wi-Fi 并开启飞行模式，结束 App 进程后重新启动，进行完整单机测试。

同一 Bundle ID 覆盖更新；更新前备份 Documents 的存档。不要用卸载方式更新。
`increased-memory-limit` 权限在重签时须获 provisioning profile 支持，能否保留需装机核验。

## 范围

保留触控、UI 缩放、后台生命周期与着色器预热。关闭 Steam 初始化、Sentry、
遥测上报、程序集级 Sentry 自动初始化、mod 初始化及主菜单联机入口。
未添加四倍速、选牌建议、快照或进度解锁。
仍须通过真机飞行模式测试核验所有离线路径；目前不宣称游戏完全无网络请求。

验收：飞行模式冷启动；新开局；卡牌拖放与取消；商店/事件/奖励；保存退出再续局；
后台恢复；至少 30 分钟连续战斗。目标 60 fps，记录高负载帧时间、内存和发热；尚无实测数据。

## 来源与许可证

原始静态织入器和移动补丁来自
[jhaizhou-ops/sts2-ios](https://github.com/jhaizhou-ops/sts2-ios)，
固定参考提交 `be1144210c7d5ac5d6c78fa56f7cb1d969397389`。
其 MIT 许可证保留在 `UPSTREAM-LICENSE.txt`。
Godot、FMOD 插件、Spine 和 FMOD Engine 各自许可证须随构建遵守。
游戏程序集与资源属于原游戏权利人；本项目只用于用户合法副本的个人适配。

其他参考：[DeadAKJ/sts2-ios-port](https://github.com/DeadAKJ/sts2-ios-port)、
[TheUnknownThing/StS2-Launcher-iOS](https://github.com/TheUnknownThing/StS2-Launcher-iOS)。
后者使用 Mono JIT，其每次启动启用 JIT 的要求不适合本次目标。
