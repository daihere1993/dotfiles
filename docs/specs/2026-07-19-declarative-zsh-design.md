# 声明式 zsh 配置设计

日期：2026-07-19  
状态：待实现

## 目标

使用 Home Manager 完整管理 zsh。`~/.zshrc` 和登录初始化文件由 Nix 生成，用户不再直接编辑这些文件。两台机器共享同一套配置，但允许用户名和 Home 目录不同。

本次迁移还要达到以下目标：

- 使用 Starship 作为唯一提示符。
- 使用 Home Manager 管理补全、命令建议、语法高亮和 history。
- 删除旧的 Oh My Zsh、Powerlevel10k、NVM、pyenv 和手工 PATH 初始化。
- 把现有代理命令纳入版本控制，但不在 shell 启动时自动开启代理。
- 从 macOS Keychain 读取 Cursor API key，密钥不进入 Git、Nix 表达式、Nix Store 或日志。
- 保留安全恢复旧配置的路径。

## 非目标

本次不处理以下内容：

- 除用户名和 Home 目录外的机器差异。
- 安装 Flutter、depot_tools、Yarn global、scrcpy、Windsurf CLI、ninja 或 gn。
- 为项目创建 dev shell。
- 引入 `sops-nix` 或 `agenix`。
- 重新设计代理命令的业务行为。
- 用 Starship 模仿 Powerlevel10k 的左右状态条。

## 当前状态

当前 `~/.zshrc` 由用户手工维护，并包含以下内容：

- Oh My Zsh 和 Powerlevel10k。
- `git` 与 `zsh-autosuggestions` 插件。
- NVM、pyenv、Python Framework、PNPM 和 Yarn global 初始化。
- Flutter、depot_tools、极空间内置 scrcpy、Windsurf、`~/.local/bin`、ninja 和 gn 的路径。
- Obsidian workspace、网络检查、Git rebase、Python、ninja 和 gn alias。
- 外部代理脚本。
- 明文 `CURSOR_API_KEY`。

现有 `.zprofile` 还初始化 Python 3.9 Framework 和 Homebrew。nix-homebrew 已通过系统 profile 提供 `brew`，Home Manager 也已安装 Node.js、pnpm 和 Python，因此这些旧初始化重复且不可复现。

当前 `.zshrc` 已备份到：

```text
~/Downloads/zshrc.backup-2026-07-19
```

源文件与备份的 SHA-256 均为：

```text
fdb6080b558e82af69e9b6fadc7a2bc8e92a041ab54a1cc8a89feafa8bddaf89
```

该备份含旧 Cursor API key。实施时必须把权限收紧为 `0600`，迁移成功后提醒用户轮换密钥。不得自动删除备份。

## 配置结构

zsh 使用独立 Home Manager 模块：

```text
home.nix
└── imports ./zsh
    ├── zsh/default.nix
    └── zsh/proxy.zsh
```

各文件职责如下：

- `home.nix` 导入 `./zsh`，继续管理通用用户包和其他 Home Manager 程序。
- `zsh/default.nix` 是 zsh 与 Starship 的唯一声明入口。它管理 shell 选项、history、alias、函数、Keychain 初始化和代理脚本加载。
- `zsh/proxy.zsh` 保存代理函数实现。Nix 把它复制到 Store，生成的 `.zshrc` 从不可变 Store 路径加载它。

不得把完整传统 `.zshrc` 作为 `home.file` 链接，也不得把代理实现内嵌进 `home.nix`。

## 用户身份与路径

配置不得包含 `lukewu`、`/Users/lukewu` 或另一台机器的用户名。Nix 声明使用现有机器身份中的 `username` 和 `homeDirectory`；zsh 运行时代码使用 `$USER` 和 `$HOME`。

测试必须用现有的 `testuser` 和 `otheruser` 两套身份构建配置，并扫描生成内容，防止重新引入硬编码用户名或 Home 路径。

## zsh 行为

Home Manager 启用并管理 zsh：

- 启用 completion。
- 启用 autosuggestion。
- 启用 syntax highlighting。
- 不启用 Oh My Zsh。
- 不加载 Powerlevel10k 或 `.p10k.zsh`。
- 不加载 NVM、pyenv 或任何旧工具路径。

history 使用以下策略：

- 保存 50,000 条记录。
- 多个交互式 shell 共享 history。
- 去除重复记录并减少连续重复写入。
- 忽略以前导空格开始的命令。

Home Manager 生成并拥有 `.zshrc` 及其所需的登录初始化。用户更新配置时修改 dotfiles 中的 Nix 或 zsh 源文件，然后运行：

```sh
nix flake check
~/.dotfiles/scripts/rebuild.sh
```

配置激活后，新开终端或执行 `exec zsh` 载入新配置。

## Starship

Starship 是唯一提示符。现有 Starship 设置从 `home.nix` 移入 `zsh/default.nix`，并显式启用 zsh integration。

提示符保持当前双行布局：

- 第一部分显示目录、Git 分支、Git 状态和命令耗时。
- 第二行显示成功或失败状态对应的 `❯`。
- 不显示 Powerlevel10k 的右侧时间、状态条或 powerline 图标。
- 不在 Starship 之外设置 `PROMPT` 或 `RPROMPT`。

## 包与 PATH 策略

全局 Node.js、pnpm 和 Python 继续由 `home.packages` 管理。删除以下初始化：

- NVM 与 NVM completion。
- pyenv shims。
- Python 3.9 Framework PATH。
- `/usr/bin/python3` alias。
- PNPM_HOME 与 Yarn global PATH。
- `brew shellenv`。
- Flutter、depot_tools、极空间 scrcpy、Windsurf 和 `~/.local/bin` PATH。
- ninja 和 gn alias。

README 必须说明以后添加工具或路径的规则：

- 所有项目都需要的可执行文件加入 `home.packages`。
- 项目专属工具放进项目 flake/dev shell。
- 只有 Nix 无法提供且路径稳定的外部工具才加入 `home.sessionPath`。
- shell 初始化代码写入 `zsh/default.nix` 或职责单一的受管脚本。
- 不直接编辑生成的 `~/.zshrc` 或 `~/.zprofile`。

## Alias 与函数

迁移以下用户命令：

- 保留 Obsidian Cursor workspace 命令，workspace 路径以 `$HOME` 为根。
- 将 `g_test` 改成含义清晰的 Google 网络检查命令。
- 将 `git_rebase_master_to_dev` 从长 alias 改为 zsh 函数。

Git rebase 函数必须：

1. 确认当前目录属于 Git 工作树。
2. 确认工作树和暂存区干净。
3. 确认本地 `master` 与 `dev` 分支存在。
4. 记录调用前的分支。
5. 切换到 `master`，执行 `git pull --ff-only origin master`。
6. 切换到 `dev`，执行 `git rebase master`。
7. 前置检查或更新 master 失败时，尽力恢复调用前的分支并返回非零状态。
8. rebase 已开始后发生冲突时保留标准 Git rebase 状态，让用户选择继续或中止，不自动回滚。

删除 Python、ninja 和 gn alias。

## Cursor API key

Cursor API key 存放在每台机器 login keychain 的 application password 中：

```text
service/name/where: nok-cursor-api-key
account:            当前机器用户名
```

当前机器的 account 是 `lukewu`。另一台机器使用自己的用户名创建同名条目。配置通过动态 `$USER` 查询，不把用户名写死。

每个交互式 shell 按以下规则加载密钥：

1. 如果已经继承非空 `CURSOR_API_KEY`，不查询 Keychain。
2. 否则调用 `/usr/bin/security find-generic-password`，同时按 account `$USER` 和 service `nok-cursor-api-key` 查询。
3. 查询成功时全局导出 `CURSOR_API_KEY`。
4. 查询失败、条目缺失或访问被拒绝时，保持变量未设置且不输出警告。
5. 不打印查询结果，不把结果传给日志或测试输出。

首次读取时 macOS 可能显示 Keychain 访问授权对话框。用户必须在系统对话框中完成授权；聊天、脚本参数和日志不得接收密钥。

## 代理模块

现有代理脚本迁入 `zsh/proxy.zsh`，保留以下公开命令：

```text
haitunwan_proxy_on
clash_proxy_on
disable_socks_proxy
proxy_off
```

迁移保留当前命令对以下目标的行为：

- 当前 shell 的代理环境变量。
- macOS HTTP、HTTPS 和 SOCKS 网络代理。
- Git、npm 和 pnpm 代理配置。
- VS Code 与 Cursor 的代理配置。

代理模块必须满足以下约束：

- shell 启动时只定义函数，不自动执行任何代理命令。
- 加载模块不得修改网络、Git、包管理器或编辑器配置。
- 所有用户路径使用 `$HOME`。
- 外部命令依赖必须由系统或 Nix 显式提供。
- 函数失败时返回非零状态，并说明失败的步骤；不得打印密钥或其他敏感值。
- 保持现有公开命令名称，避免破坏用户习惯。

本次只迁移和整理现有行为，不扩展代理类型或改变端口策略。

## 安全切换

实施必须按以下顺序执行：

1. 确认 `.zshrc` 备份存在且 SHA-256 匹配。
2. 将 `.zshrc` 备份权限收紧为 `0600`。
3. 把现有 `.zprofile` 备份到 `~/Downloads/zprofile.backup-2026-07-19`，校验内容一致，并设置为 `0600`。
4. 在不移动当前 shell 文件的情况下构建完整 darwin system closure。
5. 保持现有终端会话打开，临时移开 `.zshrc` 和 `.zprofile`。
6. 激活已构建的 closure。
7. 激活失败时立即恢复原文件。
8. 激活成功时确认 `.zshrc` 和相关登录文件已成为 Home Manager 受管链接。
9. 保留 Downloads 备份，不自动删除。

密钥备份和 Keychain 内容不属于 Nix rollback。迁移完成后必须提醒用户轮换 Cursor API key。

## 验证

### 配置级验证

flake checks 必须覆盖：

- `testuser` 与 `otheruser` 都能构建 zsh 配置。
- 生成内容不含 `lukewu`、`/Users/lukewu` 或第二台机器的固定用户名。
- zsh、completion、autosuggestion、syntax highlighting 和 Starship zsh integration 已启用。
- history 策略与设计一致。
- Keychain service 是 `nok-cursor-api-key`，account 来自动态用户名。
- 代理模块包含 5 个公开函数，但生成配置中没有自动调用。
- 旧 Oh My Zsh、Powerlevel10k、NVM、pyenv 和手工 PATH 标记不再出现。

### 静态与构建验证

- 对 Nix 文件运行 formatter 检查。
- 对 `zsh/proxy.zsh` 运行 `zsh -n`。
- 保持仓库现有 shellcheck 检查通过。
- 运行完整 `nix flake check`。
- 构建真实机器的 darwin system closure。

### 端到端验证

激活后使用真实交互式 zsh 验证：

- `STARSHIP_SHELL` 和 Starship hook 已生效。
- completion、autosuggestion 和 syntax highlighting 已加载。
- history 选项符合设计。
- alias、Git rebase 函数和 5 个代理函数存在。
- shell 启动没有自动修改代理状态。
- `CURSOR_API_KEY` 在 Keychain 可访问时非空；检查命令只输出布尔结果，不输出值。
- 旧 NVM、pyenv、Oh My Zsh 和 Powerlevel10k 初始化不存在。

最后打开新的 WezTerm 窗口，检查提示符布局、字体、换行、颜色和错误状态。发现明显 UI 问题时在本次迁移中修正。

默认不执行代理开启或关闭命令，因为它们会修改系统网络设置和多个应用配置。若需要验证真实代理切换，必须在执行前单独确认。

## 失败恢复

构建失败不会触碰当前 shell 文件。激活失败时恢复临时移开的 `.zshrc` 和 `.zprofile`。

迁移成功后若需要回到旧配置：

1. 回滚到迁移前的 nix-darwin generation。
2. 从 Downloads 备份恢复 `.zshrc` 和 `.zprofile`。
3. 启动新的 zsh 会话验证旧配置。

Nix generation rollback 不会自动恢复迁移前的手工文件，因此 README 必须保留上述恢复说明。

## 验收标准

满足以下条件后迁移完成：

- Home Manager 是 zsh 配置的唯一来源。
- 两个不同用户名的测试身份均通过构建和配置检查。
- Starship 在新 WezTerm 会话中生效，Oh My Zsh 和 Powerlevel10k 不再加载。
- Node.js、pnpm 和 Python 来自 Nix，旧手工 PATH 已删除。
- Keychain 密钥可按动态用户名加载，任何输出均不泄露密钥值。
- 代理函数可用且默认不改变系统状态。
- alias、history、completion、autosuggestion 和 syntax highlighting 符合设计。
- README 说明更新、添加 PATH 和恢复旧配置的方法。
- 格式化、语法检查、flake checks、真实构建和端到端检查全部通过。
