# 给 WAV Analyzer 签名

当前发布物是**未签名**的 exe。这带来两个后果：Windows SmartScreen 会提示「未知发布者」，
全新安装的 Windows 11（智能应用控制开着）可能直接拦下或反复告警。

签名不能凭空生成——Windows 只认「由受信任的 CA 签发、且能追溯到构建来源」的证书。
本项目走的是开源项目的免费通道。

## 三条路

| 方案 | 对别人是否有效 | 成本 | 备注 |
|---|---|---|---|
| **SignPath Foundation** | ✅ | 免费 | 证书签在 `SignPath Foundation` 名下；要求二进制由公开仓库在 CI 里构建 |
| 商用 OV / EV 证书 | ✅ | 每年数千元 | 需要实名/企业资质 + 硬件令牌；EV 有即时 SmartScreen 信誉 |
| 自签名 | ❌ 仅本机 | 免费 | 只能解决自己电脑的「未知发布者」；发给别人无效 |

本项目选 SignPath Foundation。

## 为什么必须走 CI

SignPath 的核心承诺是：**「我们核实这个二进制确实由你的公开仓库构建，并用自己的名字为它背书」**。
所以它签的是 CI 的产物，不是你在本地双击打包出来的 exe。这也意味着本地那份
`dist\WAV Analyzer.exe` 永远拿不到他们的签名——这是设计使然，不是流程繁琐。

## 一次性准备

1. **仓库设为 Public**。私有仓库不能走这个通道。
2. **申请**：<https://signpath.org/apply>，需要填：
   - 项目主页（`https://github.com/HanshanSnow/wav-analyzer`）
   - 许可证（本项目是 MIT）
   - 构建方式（GitHub Actions，见 `.github/workflows/build-sign.yml`）
   - 为什么需要签名（Windows 桌面工具、用户会遇到 SmartScreen 警告）
   审核通常需要几天。
3. **拿到三个标识**（申请通过后会给你）：
   - `organization-id`
   - `project-slug`
   - `signing-policy-slug`（常见是 `release-signing`）
   - 以及 `artifact-configuration-slug`（在 SignPath 里定义「要签哪个文件、怎么打包」，本项目建议叫 `exe`）
4. **加 token**：仓库 Settings → Secrets and variables → Actions → New repository secret，
   名字 `SIGNPATH_API_TOKEN`，值用 SignPath 后台生成的 API token。

## 启用

打开 `.github/workflows/build-sign.yml`：

1. 把 `sign` 任务里的 `XXX-organization-id` / `XXX-project-slug` 换成实际值，
   `signing-policy-slug`、`artifact-configuration-slug` 按你申请到的改。
2. 删掉 `if: false` 这一行（它的唯一作用是：申请还没批下来时不让 CI 一直变红）。

之后两种触发方式：

- 手动：Actions → Build and sign (Windows) → Run workflow
- 打标签：`git tag v2.0.0 && git push origin v2.0.0`，会自动构建、签名、打 zip、挂 Release

## 签名之后能解决什么、不能解决什么

**能**
- 文件属性里出现发布者（`SignPath Foundation`），不再是「未知发布者」
- SmartScreen 不再对每个新用户拦一次
- 智能应用控制对已签名的程序通常放行（它不是只看签名，但签名是前提）

**不能**
- 不能改变程序行为，也不能让有问题的系统（文件权限、临时目录不可写）变正常
- 不能让 SmartScreen 的「信誉」立刻满分——商用 OV 证书仍需要下载量累积，EV 才是即时

## 可选：本机自签名

只想让自己这台机器不再弹「未知发布者」，可以不申请任何证书：

```powershell
# 1) 生成一张代码签名证书（管理员 PowerShell）
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject "CN=HanshanSnow (WAV Analyzer)" -KeyUsage DigitalSignature `
    -FriendlyName "WAV Analyzer 自签名" -CertStoreLocation Cert:\CurrentUser\My
$cert.Thumbprint

# 2) 签名（不需要装 signtool）
Set-AuthenticodeSignature -FilePath "D:\WAV_Analyzer\dist\WAV Analyzer.exe" `
    -Certificate $cert -TimestampServer "http://timestamp.digicert.com"

# 3) 把证书导出来，双击安装到「受信任的根证书颁发机构」和「受信任的发布者」
Export-Certificate -Cert $cert -FilePath "$env:USERPROFILE\Desktop\wav-analyzer-selfsigned.cer"
```

**注意**：自签名证书一旦被装进「受信任的根」，这台机器就信任任何用它签的东西——
只在一台你自己的开发机上这么干。另外智能应用控制是否放行自签名程序并不保证，
必要时仍需在「设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制」里关闭它。
