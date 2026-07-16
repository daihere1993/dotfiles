# Dotfiles MVP 规格

- 状态：讨论稿
- 日期：2026-07-15
- 本次迁移工作目录：`/Users/zowu/dev_space/projects/dotfiles`
- 本次迁移参考目录：`/Users/zowu/dev_space/projects/mac-config`

以上绝对路径只描述本次迁移环境，不是运行时配置或其他设备的固定路径。

## 1. 背景

`dotfiles` 是一个新建的空 Git 仓库。它将成为多台 macOS 设备个人配置的唯一事实来源。

现有 `mac-config` 仓库仅作为迁移参考。实施时把其中仍然需要的 nix-darwin、Home Manager、Git、SSH 和开发工具能力重新组织到 `dotfiles`，不移动旧仓库，不复制旧仓库的 Git 元数据，也不要求保留旧仓库历史。

迁移基线固定为 `mac-config` commit `87324b510c6bcd3e2f2d90845cbb19c17283aa8e`。后续旧仓库变化不自动进入 MVP；需要另行审查和迁移。

MVP 优先解决日常高频需求：

1. 用同一套声明管理多台 macOS 设备。
2. 统一管理 Codex、Claude Code 和 Cursor 可通过公开文件接口管理的全局 Agent 配置。
3. 在部署前验证配置并发现文件冲突。
4. 在部署后检查缺失和漂移。
5. 依靠 Nix generation 完成配置回滚。

MVP 不建设通用配置平台。设计应为后续增加 Agent、资源类型和更完整的恢复能力保留清晰边界，但不提前实现这些能力。

## 2. 设计原则

### 2.1 明确的部署所有者

Nix 构建所有 immutable artifacts。Home Manager 部署 Git、SSH 等基础用户配置；每个 Agent platform 的 Nix-built activator 只部署该 platform 的 allowlist targets。不同部署域不得共同拥有同一路径。

`dot` CLI 负责：

- 验证仓库内容；
- 编译 Agent 配置；
- 生成和读取资源 manifest；
- 检查目标路径；
- 调用 Nix、Home Manager 和 platform activator；
- 诊断当前状态。

`dot` 不直接把 canonical source 复制到 `$HOME`。Agent platform activator 只能安装通过独立 Nix profile 解析到 Nix Store 的固定入口 symlink，并且必须遵守 manifest、conflict preflight 和恢复协议。

### 2.2 明确的管理边界

系统只管理 allowlist 中的文件和目录，不接管整个 vendor 目录。

例如：

```text
managed:   ~/.codex/AGENTS.md
managed:   ~/.claude/CLAUDE.md
managed:   ~/.agents/skills/<skill-id>
managed:   ~/.claude/skills/<skill-id>
managed:   ~/.cursor/skills/<skill-id>

unmanaged: ~/.codex/auth.json
unmanaged: ~/.codex/sessions/
unmanaged: ~/.claude/ 下的认证、会话、缓存和日志
unmanaged: Cursor 的私有数据库和未公开配置
```

API key、OAuth token、SSH 私钥、cookie、session database 等秘密或运行时状态不得进入 Git 或普通 Nix Store。

### 2.3 Canonical content 与 vendor 输出分离

用户只编辑仓库中的 canonical content。Agent adapter 把 canonical content 转换成 vendor 支持的格式：

```text
canonical content
    -> compiler
        -> Agent adapter
            -> Nix Store output
                -> platform-specific activation
```

生成文件是只读产物。修改 canonical content 后，必须执行 `dot apply` 才能生效。

### 2.4 保持编译过程纯净

Compiler：

- 只接收显式输入；
- 只写入显式输出目录；
- 不读取真实 `$HOME`；
- 不访问网络；
- 不执行部署；
- 对相同输入产生相同输出。

### 2.5 安全优先于自动化

MVP 遇到未知文件冲突时停止，不自动覆盖、移动、合并或备份用户文件。

自动备份和崩溃恢复是独立的高风险能力，推迟到后续版本。

## 3. MVP 目标

MVP 必须实现：

1. 在新 `dotfiles` 仓库中重建多台设备共用的 Nix 配置。
2. 所有设备使用同一份配置，不在仓库中保存设备名或用户名。
3. 初始化时从当前系统自动获取 username 和 home directory，并保存为 machine-local operational state。
4. 迁移现有 Git、SSH、Node.js、Python 和 pnpm 配置能力。
5. 保留本机 Git identity 和 SSH 私有配置的本地扩展文件。
6. 支持共享 Agent rules 和 Agent-specific rules。
7. 支持仓库内 local skills。
8. 支持由 `flake.lock` 固定版本的第三方 skills。
9. 通过公开接口部署 Codex、Claude Code 和 Cursor 支持的全局配置。
10. 支持完整 apply，也支持只 apply 一个 Agent platform。
11. 提供 init、validate、apply、doctor 和 rollback 工作流。
12. apply 前发现未知目标冲突并安全停止。
13. doctor 检查托管文件的 missing 和 drifted 状态。
14. 所有编译和诊断逻辑能在临时目录中测试，不修改开发者真实 `$HOME`。

## 4. MVP 非目标

MVP 不实现：

- 项目级 `AGENTS.md`、`CLAUDE.md`、`.cursor/rules` 或 `.cursor/commands`；
- canonical command 模型和 slash command 生成；
- 第三方 source 的专用 registry 或自动更新服务；
- 自动修改 Cursor User Rules；
- 写入任何未公开的 vendor 数据库；
- 自动备份、恢复、prune 或崩溃事务恢复；
- 跨进程 token lock 和对直接 `darwin-rebuild` 的强制拦截；
- 对 package、service 和 generation 的通用 ownership inventory；
- 通用插件 SDK 或第三方 adapter API；
- background watcher；
- 自动合并现有 shell、Agent 或 vendor 配置；
- zsh、其他 shell、shell plugin 或 shell dotfile 管理；
- 按设备区分配置、package 或 Agent profile；
- secrets 管理；
- Linux 或非 macOS 设备；
- 自动更新依赖后立即 apply；
- 对旧 `mac-config` Git 历史的迁移。

## 5. 仓库结构

MVP 使用以下结构：

```text
dotfiles/
├── README.md
├── flake.nix
├── flake.lock
├── justfile
├── pyproject.toml
├── modules/
│   ├── darwin/
│   │   └── common.nix
│   ├── home/
│   │   ├── common.nix
│   │   ├── development.nix
│   │   ├── git.nix
│   │   └── ssh.nix
│   └── ai-agent/
│       └── default.nix
├── ai-agent/
│   ├── rules/
│   │   ├── common.md
│   │   └── agents/
│   │       ├── codex.md
│   │       └── claude.md
│   ├── skills/
│   │   └── <skill-id>/
│   │       ├── SKILL.md
│   │       └── ...
│   ├── adapters/
│   │   ├── codex.py
│   │   ├── claude.py
│   │   └── cursor.py
│   ├── profiles/
│   │   └── default.nix
│   └── external-skills.nix
├── cli/
│   └── dotfiles_cli/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── compiler.py
│       ├── manifest.py
│       ├── nix.py
│       └── doctor.py
├── bootstrap/
│   └── install
├── tests/
│   ├── unit/
│   ├── golden/
│   ├── integration/
│   └── fixtures/
└── docs/
    └── mvp-spec.md
```

MVP 不预先拆分 `domain`、`orchestration`、`backup` 等层级。模块出现明确的独立职责或文件过大时再拆分。

## 6. 从 mac-config 迁移能力

### 6.1 迁移方式

实施时：

1. 保持 `mac-config` 仓库只读。
2. 在 `dotfiles` 中创建新的目录和模块。
3. 逐项迁移仍然需要的行为。
4. 每迁移一项能力，都通过 Nix evaluation 或测试确认结果。
5. 不复制 `.git`、`result` 或其他构建产物。

### 6.2 必须迁移的能力

从 `mac-config` 迁移：

- nixpkgs、nix-darwin 和 Home Manager flake inputs；
- `aarch64-darwin` 平台配置；
- `system.stateVersion = 6`；
- `home.stateVersion = "26.05"`；
- `nix.enable = true`；
- `nix.package = pkgs.nix`；
- `nix.settings.experimental-features = [ "nix-command" "flakes" ]`；
- `nix.optimise.automatic = true`；
- 由初始化命令传入的当前 username 和 home directory；
- Git `init.defaultBranch = "main"`；
- Git `push.autoSetupRemote = true`；
- Git `pull.rebase = false`；
- `~/.config/git/local.inc` include；
- SSH 默认设置和 `~/.ssh/config.local` include；
- Home Manager packages `nodejs`、`python3` 和 `pnpm`，具体版本由 `flake.lock` 固定；
- `home-manager.useGlobalPkgs = true`；
- `home-manager.useUserPackages = true`；
- `programs.home-manager.enable = true`。

SSH 共享默认值迁移为：

```text
AddKeysToAgent yes
Compression yes
ControlMaster auto
ControlPersist 10m
ServerAliveInterval 60
ServerAliveCountMax 3
```

旧配置中的 `flint-server` 地址、用户、端口和转发规则不进入共享模块，迁移到对应机器的 `~/.ssh/config.local`。

### 6.3 Home Manager backup 行为

旧配置中的：

```nix
home-manager.backupFileExtension = "backup";
```

不迁移到 MVP。

原因是该行为可能在 apply 时自动重命名未知文件，与 MVP 的“发现冲突后停止”策略不一致。

## 7. Machine identity 与基础 Home Manager 配置

MVP 只有一份共享配置，不定义 host 或 machine-specific module。设备差异仅限初始化时发现的 machine identity：

```json
{
  "schemaVersion": 1,
  "username": "zowu",
  "homeDirectory": "/Users/zowu",
  "nixSystem": "aarch64-darwin"
}
```

`dot init` 使用系统 API 和 `id -un` 获取当前登录用户，使用系统用户目录记录确认 home directory，使用 Nix 或 `uname -m` 确认 `nixSystem`。它不得只信任可由调用者任意覆盖的 `$USER` 或 `$HOME`。

初始化结果原子写入：

```text
~/.local/state/dotfiles/machine.json
```

该文件是 machine-local operational state，不进入 Git。`~/.local/state/dotfiles` 必须由当前用户拥有、权限为 `0700`，`machine.json` 必须是非 symlink 普通文件、权限为 `0600`。username 必须符合 macOS 本地账户名约束，home directory 必须是该账户在系统目录服务中登记的绝对路径。读取失败、字段不一致、owner/权限不安全或当前用户是 root 时，初始化停止。

Nix 配置以显式参数接收 username、home directory 和 `nixSystem`。`dot` 从 `machine.json` 读取参数，调用仓库导出的 `lib.mkDarwinConfiguration`。Nix 调用使用固定表达式，通过 `--argstr` 传入规范 JSON，再由 `builtins.fromJSON` 解析；不得把 identity 字段拼接成 Nix source。共享 Nix module 不读取环境变量，也不使用 `builtins.getEnv`。这样可以保持仓库配置统一，同时不把用户名写入仓库。

首次 init 前，依赖 machine identity 的 apply、doctor 和 rollback 命令必须停止并提示运行 `dot init`。

如果当前 system 或 Agent platform generation 包含 dotfiles manifest，apply、doctor 和 rollback 都必须先确认其 username、home directory 和 `nixSystem` 与 `machine.json` 完全一致。只要不一致，命令就停止，不读取、删除或替换旧 identity 对应 Home 下的资源。

### 7.1 Git 和 SSH 本地扩展

以下文件由用户在每台机器上维护，dotfiles 只引用，不管理其内容：

```text
~/.config/git/local.inc
~/.ssh/config.local
```

这两个文件在 MVP 中都是 optional。`dot doctor` 只检查：

- 文件是否存在；
- 是否为普通文件；
- owner 是否为当前用户；
- group 或 other 是否具有写权限。

它不得输出文件内容。

## 8. Agent canonical content

### 8.1 Rules

共享规则位于：

```text
ai-agent/rules/common.md
```

Agent-specific 补充规则位于：

```text
ai-agent/rules/agents/<agent>.md
```

编译顺序固定为：

```text
common.md
Agent-specific rules
```

Adapter 可以改变 vendor 所需的表现格式，但不得静默改变规则语义。

生成文件包含简短 provenance header，至少记录：

- generated file 警告；
- canonical source 相对路径；
- compiler schema version。

### 8.2 Local skills

每个 local skill 是一个完整目录，至少包含 `SKILL.md`：

```text
ai-agent/skills/network-diagnosis/
├── SKILL.md
├── scripts/
└── references/
```

规则：

- 目录名是 skill ID；
- ID 只允许小写字母、数字和连字符；
- 整个目录是安装单元；
- 目录内不得包含 secrets 或 mutable state；
- symlink 不得逃出 skill 目录；
- 同一目标根目录内不得出现重复 ID。

`SKILL.md` 必须包含 YAML frontmatter，其中：

- `name` 必须等于目录 ID；
- `description` 必须是非空字符串。

MVP 不要求额外 `skill.toml`。确实需要 machine-readable metadata 时再引入，避免维护与目录结构重复的数据。

### 8.3 第三方 skills

第三方 skill repository 作为 `flake.nix` 的 non-flake input 声明，并由 `flake.lock` 固定 revision 和 content hash。构建和 apply 不读取 floating branch。

`ai-agent/external-skills.nix` 从已固定 source 中选择完整 skill 目录。例如：

```nix
{ inputs }:
{
  sources.superpowers = {
    inputName = "superpowers";
  };

  skills."superpowers/brainstorming" = {
    sourceId = "superpowers";
    skillId = "brainstorming";
    path = "skills/brainstorming";
  };
}
```

`source-id` 和 `skill-id` 都必须匹配 `[a-z0-9][a-z0-9-]*`。`sources` attribute name、`inputName`、`flake.nix` 根级 input attribute name，以及每个 skill entry 的 `sourceId` 四者必须完全相等；skill entry 必须引用已存在的 `sources.<sourceId>`。Compiler 通过 `inputs.${inputName}` 取得 source。`skills` attribute name 必须严格等于 `<source-id>/<skill-id>`。

第三方 skill 的 canonical ID 严格编码为 `external:<source-id>/<skill-id>`，其中必须恰好包含一个 `/`；local skill 的 canonical ID 是 `local:<skill-id>`。部署到 Agent platform 时使用未限定的 `<skill-id>`。同一 platform 上两个选项映射到同一 target ID 时 validation 失败，不自动覆盖或合并。

MVP 验证：

- source 必须是 `flake.nix` 根级直接声明、`flake = false` 的 input，不支持 `follows`；
- `flake.lock` 的 `root.inputs.<source-id>` 必须直接指向一个 locked node；compiler 用该 node 读取 lock identity；
- 对应 `flake.lock` node 必须包含 `locked.narHash`；该 `narHash` 是稳定 lock identity，`locked.rev` 存在时作为附加审查信息；
- 选择路径必须是相对路径且不能包含 `..`；
- 选择路径不能通过 symlink 逃出 source；
- 完整目录必须包含合法的 `SKILL.md`；
- `SKILL.md` 的 `name` 必须等于 `<skill-id>`；
- 整个目录作为安装单元，不能只复制 `SKILL.md`；
- profile 引用的 canonical ID 必须存在。

MVP 不提供第三方 source 专用更新命令。更新流程使用：

```text
nix flake update <source-id>
dot validate
dot apply --check
dot apply
```

完整 apply 会更新所有使用该 source 的 Agent platforms；更新 lock file 本身不自动 apply。用户也可以根据 `dot validate` 输出的受影响 platform 列表逐一执行单 platform check/apply，但不能把只更新一个 platform 误报为 source 已全面部署。需要长期修改第三方 skill 时，将其 fork 或转换成 local skill。

## 9. Agent adapter

MVP adapter 是仓库内受信任的 Python 模块。每个 adapter 接收统一的 compile plan，并返回资源列表。

统一输入至少包含：

- Agent ID；
- rules source 列表；
- local skill 目录；
- 已锁定的第三方 skill 目录；
- 显式 output root。

统一输出至少包含：

- 实际部署入口的 resources：resource ID、owner、kind、output path、target path、source 列表和 content hash；
- skills inventory：canonical ID、target skill ID、bundle-relative path、directory hash 和 provenance。

Adapter 只能写入 output root。Compiler 必须验证返回路径没有逃出 output root。

文件的 content hash 是文件原始字节的 SHA-256。

目录 hash 是 canonical JSON UTF-8 字节的 SHA-256。Canonical JSON 是一个 entry array：

- 递归包含目录下的普通文件、目录和 symlink，空目录也有 entry；
- `path` 使用相对 POSIX 路径；
- entry 按 `path` 的 UTF-8 字节序排列；
- 每个 entry 都有 `path` 和 `type`；
- 普通文件增加 `sha256` 和 `executable`；
- symlink 增加原始 `target`；
- 目录没有额外字段；
- object key 按字典序排列；
- JSON 不转义非 ASCII 字符，不包含无意义空格，以 `\n` 结尾；
- 不包含绝对 Store path、owner、group 或时间戳。

`executable` 在任意 user、group 或 other execute bit 被设置时为 `true`。无法解码为 UTF-8 的路径或 symlink target，以及逃出目录树的 symlink，都使 validation 失败。

MVP 不使用独立 renderer 进程协议。将来确实需要加载外部 adapter 时，可以在不改变 compile plan 和 resource model 的前提下增加进程边界。

### 9.1 Codex

管理：

```text
~/.codex/AGENTS.md
~/.agents/skills/<skill-id>
```

不管理 Codex auth、session、log、cache 和数据库。

### 9.2 Claude Code

管理：

```text
~/.claude/CLAUDE.md
~/.claude/skills/<skill-id>
```

不管理 Claude Code auth、session、log、cache 和数据库。

### 9.3 Cursor

Cursor User Rules 目前通过 Cursor Settings/Customize 管理，官方说明其不存储在文件系统。MVP：

- 不自动部署 Cursor 全局 Rules；
- 不修改 Cursor 私有数据库；
- 在 `validate`、`doctor` 和 README 中明确显示该限制。

Cursor 已公开支持全局 skills。MVP 使用 Cursor-specific global skill root：

```text
~/.cursor/skills/<skill-id>
```

Cursor 使用自己的公开 global skill root，避免与 Codex 的 `~/.agents/skills` 共享 target ownership，从而允许两个 platform 独立 apply。

`~/.cursor/cli-config.json` 虽然是公开接口，但不属于本次 MVP 核心目标，除非迁移过程中确认存在必须声明管理的配置。

## 10. Nix 与部署

### 10.1 构建输出

Agent compiler 在 Nix build 中执行。每个生成输出和 manifest 都进入 `/nix/store`。

部署分成四个互不重叠的 domain：

```text
system
codex
claude
cursor
```

`system` domain 是 nix-darwin generation，其中 Home Manager 管理 Git、SSH 等基础配置。三个 Agent platform 各自产生一个 Nix Store bundle，包含：

- platform manifest；
- 生成的 rules 文件；
- 选中的完整 skill 目录；
- 固定目录结构。

每个平台只拥有固定的入口 symlink：

```text
codex:
  ~/.codex/AGENTS.md  -> <codex-profile>/AGENTS.md
  ~/.agents/skills/<skill-id> -> <codex-profile>/skills/<skill-id>

claude:
  ~/.claude/CLAUDE.md -> <claude-profile>/CLAUDE.md
  ~/.claude/skills/<skill-id> -> <claude-profile>/skills/<skill-id>

cursor:
  ~/.cursor/skills/<skill-id> -> <cursor-profile>/skills/<skill-id>
```

MVP 不管理 platform-specific skills root，只管理 profile 显式选择的单个 skill 入口。skills root 可以包含 manual skills；同名的非托管 skill 仍按 conflict 停止，绝不自动覆盖。

Activator 可以创建缺失的父目录，但不得替换 `~/.codex`、`~/.claude` 或 `~/.cursor` vendor 根目录。入口 symlink 经过 platform profile 最终解析到 immutable Nix Store bundle。

每个平台使用独立的 user-owned Nix profile：

```text
~/.local/state/dotfiles/platforms/codex/profile
~/.local/state/dotfiles/platforms/claude/profile
~/.local/state/dotfiles/platforms/cursor/profile
```

Profile 的当前 Store bundle 即该 platform 的 active generation。非目标 platform 的 profile 和入口 symlinks 不参与单平台 apply。

只有 manifest 中所有 managed resources 都完整且健康时，profile manifest 才属于 active runtime ownership。`STAGED_NOT_DEPLOYED` profile 不拥有 runtime target；其 manifest 只用于重试和诊断。无论 staged 状态如何，validate 都必须检查三个内置 adapter 的固定 target contracts，防止仓库静态配置产生跨 domain overlap。

Profile switch 使用固定命令原语 `nix-env --profile <profile-path> --set <bundle-store-path>`，并验证 profile 最终解析到目标 bundle。该操作必须保留 Nix profile generation，使旧 bundle 在切换完成前可用。

除首次部署或修复缺失入口外，platform apply 只切换一个 profile symlink，不逐个改写 rules 或 skills target。Platform activator 接收 versioned JSON activation plan，再次验证 machine identity、旧/新 manifests 和固定入口路径，并拒绝任何额外路径。

System Home Manager 声明必须从 system resource 集合生成，或通过 Nix assertion 证明每个 Home Manager target 都存在于 system manifest。禁止在 manifest 之外增加 Home Manager file target。

`dot` package 仍由共享 nix-darwin 配置加入 system packages，但 CLI 可用性不依赖 System activation。Bootstrap 先将 package 设置到 `~/.local/state/dotfiles/cli/profile`，再创建稳定入口 `~/.local/bin/dot`。Git、SSH 或其他 System conflict 不得阻止 CLI 安装或升级。首次 bootstrap 前仍可通过 `nix run .#dot -- ...` 调用。

### 10.2 Profile

`ai-agent/profiles/default.nix` 显式声明：

- 每个 Agent platform 选择哪些 local 或 external skills。

MVP 固定支持并部署 Codex、Claude 和 Cursor 三个平台，不实现 enable/disable 开关。Codex 和 Claude 编译 rules 与 skills；Cursor 只编译 skills 并报告 global rules 能力缺口。Skill 选择显式列出 canonical ID 和目标 platforms。未选择的 skill 不部署，adapter 的存在不等于向所有 platform 广播。

### 10.3 不支持能力

MVP 不实现通用 capability negotiation 模型。内置 adapter 的能力由代码固定。

Cursor global rules 是唯一已知的能力缺口：`validate` 和 `doctor` 输出 `UNSUPPORTED_OPTIONAL` warning，但不使命令失败。

## 11. Resource manifest

MVP 为每个 deployment domain 生成独立 manifest：

- system manifest 记录 Git、SSH 等 system/Home Manager targets；
- 每个 Agent platform manifest 只记录该 platform 的 rules 和 skills targets。

Manifest 不记录 package、service 或通用 generation inventory。Agent platform manifest 把“实际部署入口”和“bundle 内 skill inventory”分开：

- `resources` 记录固定 rules 入口和每个已选择 skill 的独立入口；
- `skills` 逐项记录 bundle 中的 local/external skill provenance。

最小结构：

```json
{
  "schemaVersion": 1,
  "username": "zowu",
  "homeDirectory": "/Users/zowu",
  "nixSystem": "aarch64-darwin",
  "deploymentDomain": "codex",
  "resources": [
    {
      "id": "ai-agent.codex.global-rules",
      "owner": "ai-agent.codex",
      "kind": "file-link",
      "target": "/Users/zowu/.codex/AGENTS.md",
      "linkTarget": "/Users/zowu/.local/state/dotfiles/platforms/codex/profile/AGENTS.md",
      "storePath": "/nix/store/<hash>-codex-rules/AGENTS.md",
      "sha256": "<content-sha256>",
      "sources": [
        "ai-agent/rules/common.md",
        "ai-agent/rules/agents/codex.md"
      ]
    }
  ],
  "skills": [
    {
      "canonicalId": "external:superpowers/brainstorming",
      "targetId": "brainstorming",
      "bundlePath": "skills/brainstorming",
      "directorySha256": "<directory-sha256>",
      "sourceKind": "external",
      "sourceId": "superpowers",
      "narHash": "sha256-...",
      "rev": "<optional-revision>",
      "sourcePath": "skills/brainstorming"
    }
  ]
}
```

支持的 resource kind：

```text
file-link
directory-link
local-prerequisite
```

`file-link` 和 `directory-link` 都必须记录：

- `target`：`$HOME` 下的入口路径；
- `linkTarget`：入口 symlink 的原始 `readlink` 期望值；
- `storePath`：沿 profile symlink 完全解析后的期望 Store path。

`file-link` 额外记录 `sha256`；`directory-link` 额外记录 `directorySha256`。System domain 的 Home Manager link 如果直接指向 Store，则 `linkTarget` 可以等于 `storePath`。

Apply 和 doctor 的“完全符合”统一表示：入口本身是 symlink，原始 `readlink` 等于 `linkTarget`，完全解析路径等于 `storePath`，并且文件或目录 hash 匹配对应字段。

`local-prerequisite` 表示 dotfiles 依赖但不管理的本地文件，例如 Git 和 SSH include。它增加：

```json
{
  "managed": false
}
```

它不包含文件内容或 Store path。MVP 中的 local prerequisites 都是 optional；缺失不会阻塞 bootstrap、apply 或 doctor。

Manifest 在 build 阶段生成，不包含时间戳等运行时数据。同一输入必须生成相同 manifest。

Local skill inventory entry 使用 `sourceKind = "local"` 并记录 canonical repository path。External skill inventory entry 使用 `sourceKind = "external"`，并额外记录 `sourceId`、`narHash`、可选 `rev` 和所选 source-relative path；不记录 floating branch 名作为版本身份。

Doctor 对 filesystem ownership 只检查 `resources`，并通过每个 skill 的 directory hash 检查漂移；`skills` 用于验证 bundle inventory、来源展示和逐 skill 诊断。

每个 generation 必须包含自己的 immutable manifest。当前 system manifest 通过以下路径暴露：

```text
/run/current-system/sw/share/dotfiles/system-manifest.json
```

当前 Agent platform manifest 通过对应 profile 暴露：

```text
~/.local/state/dotfiles/platforms/<platform>/profile/share/dotfiles/manifest.json
```

Doctor 读取 machine identity、当前 system manifest 和三个 platform profiles，并要求所有现存 manifest 的 username、home directory 和 `nixSystem` 一致。切换 generation 会自然切换对应 manifest，不维护额外 current pointer 或 activation record。

## 12. `dot` CLI

MVP 使用 Python 3。优先使用标准库，并由 Nix 固定解释器和运行环境。

`init`、`validate` 和 `apply` 从当前工作目录开始向上查找 `flake.nix` 与 `.git`，两者所在目录必须相同，并把该目录作为本次仓库根目录；找不到时停止。MVP 不在 machine state 中固定仓库路径，因此移动或重新 clone 仓库不需要修改 identity。`doctor` 和 `rollback` 只依赖已安装的 `dot`、machine state 和 system generations，可以从任意目录运行。

公开命令：

```text
dot init
dot validate
dot apply [--check] [--platform codex|claude|cursor]
dot doctor [--json] [--platform codex|claude|cursor]
dot rollback
```

### 12.1 `dot init`

`dot init` 是 machine-local 初始化命令：

1. 确认当前系统是支持的 macOS 平台。
2. 自动获取并交叉验证 username 和 home directory。
3. 写入 `machine.json`。
4. 用发现的 machine identity 对共享 Nix 配置执行 evaluation。
5. 输出检测结果，不执行 system switch。

重复运行时，如果检测结果与现有 `machine.json` 相同则成功且不改写。如果不同则显示差异并停止。MVP 不支持原地替换已经初始化的 machine identity；账户迁移需要先通过单独规格处理旧 generation 和旧 Home 中的资源。

### 12.2 `dot validate`

只读检查：

- Nix evaluation；
- 共享配置能否接受合法的 machine identity；
- canonical 路径和 ID；
- skill 目录结构；
- external source 是否已声明并由 `flake.lock` 固定；
- external selected path 和 symlink 边界；
- rule composition；
- 内置 adapter 支持范围；
- duplicate target；
- 跨 deployment domain target ownership；
- generated manifest schema；
- 内置 adapter 能否成功编译固定的最小输入。

没有 `machine.json` 时，validate 使用固定的测试 identity 验证仓库结构，不创建 machine state。它不读取或修改真实 `$HOME`。

### 12.3 `dot apply --check`

不带 `--platform` 时，检查 system domain 和三个 Agent platforms。带 `--platform` 时，只检查选中的 Agent platform；不构建或检查 system domain 和其他 Agent platforms。

单 platform check 执行：

1. 读取并验证 machine identity。
2. 验证共享 canonical content、选中 platform adapter、该 platform 选择的 local/external skills。
3. 构建一个确定的目标 platform Store bundle。
4. 从该 platform profile 读取 active manifest；首次部署时 active manifest 不存在。
5. 只检查该 platform 固定入口 symlinks，同时只读加载其他 active domain manifests 以验证没有相等或祖先/后代 ownership 重叠。其他 domain 的 `STAGED_NOT_DEPLOYED` manifest 不算 active ownership。
6. 输出目标 bundle、计划、warning 和 conflict。

不执行 switch，不修改目标文件。

### 12.4 `dot apply`

#### 12.4.1 单 Agent platform apply

`dot apply --platform codex` 只更新 Codex domain。macOS system generation、Git/SSH 配置、Claude 和 Cursor profiles 与 targets 保持当前已部署版本。

支持的 platform ID 固定为：

```text
codex
claude
cursor
```

未知值或重复 `--platform` 参数是 usage error。MVP 一次只接受零个或一个 platform。

Platform apply 执行与对应 `--check` 相同的 build 和 preflight，然后：

1. 记录 apply 前的部署状态（`DEPLOYED`、`STAGED_NOT_DEPLOYED` 或 `NOT_DEPLOYED`）和旧 Store bundle。
2. 使用固定 profile switch 原语设置为目标 Store bundle。
3. 首次部署时创建固定入口 symlinks；后续 apply 不改写健康的入口 symlinks，只补回 active manifest 已声明但当前缺失的入口。
4. 验证 profile、全部入口 symlinks、rules hash、skills directory hash 和 platform manifest。

Profile switch 必须表现为“旧 bundle”或“新 bundle”二选一；命令结束后解析到其他状态视为失败。

如果切换后验证失败：

- apply 前状态是 `DEPLOYED` 时，把 profile 切回旧 bundle 并重新验证；原有固定入口无需改写，因为它们指向稳定 profile path。
- apply 前状态是 `STAGED_NOT_DEPLOYED` 时，先在 profile 仍指向新 bundle 时删除本次创建且仍精确符合新 manifest 的全部入口，再把 profile 切回旧 staged bundle并验证仍无入口，保持未部署状态。
- apply 前状态是 `NOT_DEPLOYED` 时，删除本次创建且仍精确匹配预期值的入口；不尝试删除当前 profile generation，把 bundle 保留为未激活的 staged profile。
- 不删除或覆盖任何与预期不符的路径。

首次失败后，如果所有本次创建的入口都已安全删除，doctor 报告 `STAGED_NOT_DEPLOYED`。部分资源成功且其他资源被 skip 时报告 `PARTIALLY_DEPLOYED`，后续 rules 更新仍可继续。

有旧 bundle且恢复成功时返回非零并报告 `ROLLED_BACK`。恢复失败时报告实际 profile 和入口状态；下次 apply 的 preflight 会因 profile/manifest 或入口不一致而停止，不需要单独的 activation journal。

#### 12.4.2 完整 apply

不带 `--platform` 的 `dot apply`：

1. 构建 system closure 和三个 Agent platform bundles。
2. 在修改任何状态前，对全部 deployment domains 独立完成 preflight。
3. System conflict 跳过整个 system domain；Agent conflict 按 resource 交互决定 overwrite 或 skip。
4. 激活 conflict-free 的 system closure。
5. 按 `codex`、`claude`、`cursor` 固定顺序激活 conflict-free 的 platform bundles。
6. 写入逐 platform activation receipt，并对已激活的 Agent domains 运行 doctor。

MVP 不提供跨 system 与多个 Agent platforms 的全局原子事务。一个 resource 的 conflict 不阻止同平台的安全 resources；部分成功报告 `PARTIAL_UPDATED` 并返回 3。每个失败 domain 按 receipt、backup 和旧 profile 恢复。

#### 12.4.3 System activation

System domain 没有 conflict 时，必须激活刚刚完成 preflight 的同一个 system Store closure，不得重新根据可能已经变化的 working tree 构建另一个 closure。

MVP 使用以下激活协议：

1. 用户态 `nix build --no-link --print-out-paths` 得到目标 system Store path，不在仓库创建 `result`。
2. 记录 `/run/current-system` 当前指向的已激活 Store path。
3. 完成目标 Store path 的 manifest preflight。
4. 通过 sudo 把 `/nix/var/nix/profiles/system` 设置为目标 Store path，并记录新建的 profile generation number。
5. 以 root 执行目标 Store path 自带的 `activate`。
6. 确认 `/run/current-system` 指向目标 Store path。
7. 运行 doctor。

Phase 0 必须先用当前固定的 nix-darwin 版本验证该协议。若目标 system output 不提供 `activate`，实施暂停并修订规格，不允许退化成重新构建未检查的 closure。

如果第 5 步 activation 失败，目标 activation 可能已经产生部分修改，不能仅凭 `/run/current-system` 仍指向旧 Store path 就声称已经回滚。命令必须：

1. 把 system profile 恢复到第 2 步记录的旧 Store path；
2. 重新执行旧 Store path 的 `activate`；
3. 确认 `/run/current-system` 指回旧 Store path；
4. 使用旧 generation 的 manifest 运行 doctor；
5. 删除激活协议第 4 步为失败目标创建的特定 profile generation，避免它被后续 rollback 当成已成功状态；
6. 分别报告目标 activation、旧 profile 恢复、旧 generation 重新 activation、doctor 和失败 generation 清理的结果。

只有以上恢复步骤全部成功，命令才能报告“已恢复到旧 generation”。删除操作只允许删除本次 apply 记录的失败 generation number。任一步失败都报告 `RECOVERY_REQUIRED`，保留完整命令输出，并停止其他状态变更。Phase 0 必须测试 activation 在更新 `/run/current-system` 之前和之后失败的两种情况。

Apply 不更新 `flake.lock`，也不编辑 canonical content。

`dot apply` 是受支持的部署入口。MVP 不阻止用户直接调用 `darwin-rebuild` 或 `home-manager`，但 README 必须说明这些入口不会获得 `dot` 的完整 preflight 和 post-apply 检查。

MVP 不提供并发部署保证。apply 开始前检查是否存在另一个可识别的 `dot apply` 进程并拒绝明显并发；无法阻止外部部署命令，README 要求用户不要并行运行配置切换。

### 12.5 `dot doctor`

Doctor 是只读命令。不带 `--platform` 时检查 system 和三个 Agent platforms；带参数时只检查选中的 Agent platform。

检查：

- machine identity；
- 对应 domain 的 active profile/generation 和 manifest 是否存在、匹配且可读；
- managed target 是否存在；
- symlink 是否指向预期 Store path；
- file 或 directory content hash 是否匹配；
- local prerequisite 是否存在及权限是否安全；
- optional capability 是否不受支持。

MVP 状态：

```text
HEALTHY
NOT_DEPLOYED
STAGED_NOT_DEPLOYED
MISSING
DRIFTED
LOCAL_PRESENT
LOCAL_ABSENT_OPTIONAL
LOCAL_UNSAFE_PERMISSIONS
UNSUPPORTED_OPTIONAL
```

`NOT_DEPLOYED` 表示一个 Agent platform 尚无 profile。`STAGED_NOT_DEPLOYED` 表示 profile 已存在但所有固定入口都尚未安装。`MISSING` 表示已经部署的平台缺少 active manifest 中的部分托管入口。`DRIFTED` 表示入口存在但类型、profile symlink target、文件 hash 或目录 hash 不符合 active manifest。`CONFLICT` 只属于 apply preflight，不是 doctor 对当前 generation 的状态。

Local prerequisite 缺失时报告健康的 `LOCAL_ABSENT_OPTIONAL`。存在但不是当前用户拥有的普通文件，或 group/other 可写时，报告不健康的 `LOCAL_UNSAFE_PERMISSIONS`。

默认输出只显示摘要和异常。`--json` 输出稳定、可测试的 schema。

### 12.6 `dot rollback`

MVP 的 `dot rollback` 只回滚 system domain，不隐式改变 Agent platform profiles。Agent platform 的手工历史回滚推迟到后续版本；平台 apply 自身仍必须在失败时恢复到 apply 前 bundle。

Rollback：

1. 以 `/run/current-system` 确定当前已激活 generation；
2. 列出 system profile generations，取 generation number 最大且 Store path 解析为当前 `/run/current-system` 的条目作为当前 profile generation；
3. 选择 generation number 小于当前条目、且 Store path 不同于当前 closure 的最近一个 generation；重复指向当前 closure 的条目跳过；
4. 在切换前读取并验证目标 generation 自带的 manifest，并要求其 machine identity 与当前 `machine.json` 完全一致；
5. 使用 Section 13 的相同算法，对目标 manifest 执行完整 filesystem conflict preflight；
6. 显示当前和目标 generation，并请求交互确认；
7. 使用与 apply 相同的“激活指定 Store closure”原语执行切换；
8. 从目标 generation 自带的 manifest 运行 doctor。

Rollback 不修改 Git 或 `flake.lock`。

如果目标 generation 不包含有效 manifest，命令必须停止，不得猜测。

## 13. Conflict 处理

每个 deployment domain 独立对该 domain 的 active manifest 与 desired manifest 中 `file-link` 和 `directory-link` 资源并集进行分类。Preflight 还要读取其他 active domain manifests，但不得修改它们。

不同 domain 的 target ownership 不得：

- 路径相等；
- 让一个 `directory-link` target 成为另一个 resource target 的祖先或后代。

发现静态 profile 中的重叠时 validation 失败；发现与其他 active domain 的重叠时 apply 以 conflict 停止。

```text
ABSENT
ADOPTABLE_EMPTY
CURRENTLY_MANAGED
REPLACEABLE_MANAGED
RETIRED_ABSENT
RETIRABLE_MANAGED
OVERWRITABLE_CONFLICT
CONFLICT
```

- `ABSENT`：目标不存在，可以部署。
- `ADOPTABLE_EMPTY`：首次部署的 rules target 是当前用户拥有、权限安全的空普通文件，可以接管；失败恢复时重建原空文件和 mode。
- `CURRENTLY_MANAGED`：目标的类型、Store symlink target 和 hash 都符合 desired manifest。
- `REPLACEABLE_MANAGED`：active manifest 中存在相同 resource ID 和 target，且当前实际资源符合 active manifest，可以由 desired generation 替换。
- `RETIRED_ABSENT`：资源只存在于 active manifest，且实际目标已经不存在。
- `RETIRABLE_MANAGED`：资源只存在于 active manifest，且实际目标仍完全符合 active manifest，可以由 desired generation 安全移除。
- `OVERWRITABLE_CONFLICT`：非受管的同名 Agent skill 可以原子备份后覆盖，或由用户选择 skip。
- `CONFLICT`：目标存在，但无法证明由 dotfiles 当前 generation 管理。

判定顺序固定为：

1. 资源存在于 desired manifest 且目标不存在时为 `ABSENT`。
2. 首次部署的 desired `file-link` 是当前用户拥有、group/other 不可写的空普通文件时为 `ADOPTABLE_EMPTY`。
3. 资源存在于 desired manifest 且目标完全符合 desired manifest 时为 `CURRENTLY_MANAGED`。
4. 资源同时存在于 active 和 desired manifest，ID 与 target 相同，且目标完全符合 active manifest 时为 `REPLACEABLE_MANAGED`。
5. 资源只存在于 active manifest 且目标不存在时为 `RETIRED_ABSENT`。
6. 资源只存在于 active manifest 且目标完全符合 active manifest 时为 `RETIRABLE_MANAGED`。
7. 满足固定 Agent skill contract、owner、文件类型和同 filesystem 检查的同名 skill 为 `OVERWRITABLE_CONFLICT`。
8. 其他情况均为 `CONFLICT`。

“完全符合”使用 Section 11 定义的 raw `readlink`、resolved Store path 和对应 hash 三项检查。active manifest 缺失或损坏时，只有符合 desired manifest 的目标可放行；未知旧 Store symlink 仍然是 conflict。删除一个旧资源与新增或替换资源一样，必须先完成分类，不得默认把 active-only target 当作可删除文件。

`local-prerequisite` 不进入 conflict 分类，因为 dotfiles 不管理或替换它。Doctor 按 optional prerequisite 的权限策略单独观察。

交互式 apply 对 `OVERWRITABLE_CONFLICT` 提供 overwrite、skip、overwrite all 和 skip all。非 TTY 默认 skip。Overwrite 使用 `~/.local/state/dotfiles/backups/` 保存原入口；其他 conflict 只 skip resource。所有选择在第一次状态修改前完成。

多目标 apply 必须先完成全部 domain 的 preflight，再进行任何 switch；conflict 只跳过对应 domain。

## 14. Bootstrap

`bootstrap/install` 是一个小型、幂等的 shell 脚本。

调用：

```bash
./bootstrap/install
```

它负责：

1. 验证 macOS 和 Apple Silicon；
2. 检查 Xcode Command Line Tools；
3. 安装或验证 Nix；
4. 运行 `nix run .#dot -- init`，自动检测 machine identity；
5. 运行 `nix run .#dot -- validate`；
6. 运行完整 `dot apply --check`；
7. 没有 conflict 时运行完整 `dot apply`；
8. 运行 doctor。

无法自动完成的 Apple GUI、GitHub、Agent vendor 登录只提供明确提示。

## 15. 错误处理

所有失败信息必须回答：

1. 哪个操作失败；
2. 哪个 machine identity、owner 或 target 受影响；
3. 是否已经发生修改；
4. 用户下一步应执行什么安全命令。

建议退出码：

```text
0 success
2 usage or validation error
3 conflict or user abort
4 build failure
5 switch or rollback failure
6 doctor found unhealthy state
```

日志不得读取后再过滤 secrets；应从数据模型上避免读取秘密文件。

## 16. 测试策略

### 16.1 单元测试

覆盖：

- ID 和相对路径验证；
- rule composition 顺序；
- provenance header；
- local skill discovery；
- external skill declaration、qualified ID 和 locked source 选择；
- external path traversal 和 symlink escape；
- symlink escape；
- duplicate target；
- 跨 deployment domain duplicate target；
- directory target 祖先/后代 ownership overlap；
- Cursor global rules warning；
- manifest serialization；
- resource classification；
- doctor 状态；
- machine identity discovery、validation 和 serialization；
- machine state owner、mode 和 symlink 拒绝；
- Nix command 构造。

### 16.2 Golden tests

为 Codex、Claude Code 和 Cursor 保存固定输入和预期输出树。

Golden tests 检查：

- 输出路径；
- rules 内容；
- skill 目录；
- local 和 external skill provenance；
- provenance；
- manifest resources；
- unsupported capability diagnostics。

### 16.3 Integration tests

使用临时 source、output、HOME 和 state 目录，至少覆盖：

- clean apply plan；
- 未知文件 conflict；
- 当前 managed target；
- generation 更新后的 replaceable managed target；
- 单 platform apply 不改变 system 和其他 platform profiles；
- 后续单 platform apply 只切换 profile，不改写健康入口 symlinks；
- 单 platform 验证失败后恢复旧 profile；
- 首次 platform activation 失败后只移除本次创建且仍匹配预期的入口 symlinks，并报告 `STAGED_NOT_DEPLOYED`；
- profile switch 只能解析为旧 bundle 或新 bundle；
- 单 platform preflight 拒绝与其他 active domain 的 ownership overlap；
- raw `readlink` 正确但 resolved Store path 或 hash 错误时报告 drift；
- staged profile 重试失败后不留下任何本次创建的入口；
- staged domain 不算 active ownership，但仍参与静态 target contract validation；
- 完整 apply 在所有 domain preflight 完成前不修改状态；
- 完整 apply 的部分成功 domain 状态报告；
- platform doctor 的 `NOT_DEPLOYED`、`MISSING` 和 `DRIFTED`；
- missing target；
- drifted symlink；
- optional local prerequisite missing；
- init 自动检测 username 和 home directory；
- init 拒绝 root、身份不一致和不支持的平台；
- 同一共享配置使用不同 machine identity 构建；
- active manifest 与 machine identity 不一致时拒绝 apply、doctor 和 rollback；
- activation 失败后恢复旧 profile、重新激活旧 closure 并清理失败 generation；
- rollback 跳过指向当前 closure 的重复 profile generations；
- Cursor rules warning 和 global skills 输出；
- external skill 完整目录安装；
- floating source 不参与 apply；
- 更新 `flake.lock` 后不自动 apply；
- rollback 后自动读取目标 generation 自带的 manifest。

测试不得修改开发者真实 `$HOME`。

### 16.4 Nix checks

`nix flake check` 至少聚合：

- 使用固定测试 identity 的共享配置 evaluation/build；
- `dot` package build；
- Python tests；
- adapter golden tests；
- bootstrap ShellCheck；
- Nix 和 Python formatting/lint。

MVP 不设置任意的整体覆盖率门槛。路径安全、冲突分类和会触发 switch 的分支必须有明确测试。

## 17. 实施阶段

### Phase 0：仓库基础

- 在现有空 `dotfiles` repo 中创建基础文件；
- 配置 flake、formatter、test entry points；
- 建立单一共享 darwin 和 Home Manager module；
- 导出参数化的 `lib.mkDarwinConfiguration`；
- 使用固定测试 identity 确认共享配置可以 evaluation/build；
- 用固定的 nix-darwin 版本验证 system output 的 `activate` 和指定 Store closure 激活协议；
- 为 apply、bootstrap 和 rollback 定义并测试同一个 activation primitive。

退出条件：`dotfiles` 独立构建，不依赖 `mac-config` 路径；指定 Store closure 能在测试机上按协议激活。若激活协议不成立，后续阶段暂停并修订规格。

### Phase 1：迁移基础配置

- 迁移 Git、SSH 和 development 配置；
- 保留 Git 和 SSH 本地扩展点；
- 确认不声明或修改任何 zsh 配置；
- 不迁移 `backupFileExtension`。

退出条件：共享配置能使用自动发现的不同 machine identity 构建，Git、SSH 和开发工具行为符合迁移基线，zsh 不受管理。

### Phase 2：Agent compiler

- 建立 canonical rules；
- 建立 local skills；
- 支持由 flake inputs 和 `flake.lock` 固定的 external skills；
- 实现三个内置 adapter；
- 生成独立 platform bundles 和 manifests；
- 增加 unit 和 golden tests。

退出条件：固定输入能产生确定的 Codex、Claude Code 和 Cursor 输出。

### Phase 3：部署与 CLI

- 用 Nix 构建 Agent outputs；
- 实现三个 platform-specific profiles 和 activators；
- 实现 init、validate、apply check、apply 和 doctor；
- 实现 `dot apply --platform <platform>`；
- 实现 conflict abort；
- 验证 system generation 内置 manifest 的切换。

退出条件：临时 HOME integration tests 通过；单 platform apply 不改变 system 和其他 platforms；真实 apply 前可以完整预览。

### Phase 4：回滚和 bootstrap

- 实现上一 generation rollback；
- 实现 bootstrap；
- 完成 README。

退出条件：新 Mac 可以从 clone 加一条无参数 bootstrap 命令进入声明状态，必须的人工认证除外。

## 18. MVP 验收标准

MVP 完成时，以下条件全部成立：

1. 所有实现都位于新 `dotfiles` 仓库，运行时不依赖 `mac-config`。
2. 同一份共享配置能使用初始化发现的不同 username 和 home directory 构建。
3. Git、SSH、Node.js、Python 和 pnpm 能力完成迁移。
4. 仓库不声明、生成或修改任何 zsh 配置。
5. Codex 和 Claude Code 通过公开用户级文件加载生成的 global rules。
6. Codex、Claude Code 和 Cursor 通过公开路径加载选中的 global skills。
7. Local 和 external skills 都能按 platform 显式选择；external source 由 `flake.lock` 固定并作为完整目录安装。
8. `dot apply --platform codex` 只更新 Codex，system、Claude 和 Cursor 保持当前版本；其他 platform 同理。
9. Cursor global rules 的限制被明确报告，且没有私有数据库写入。
10. Agent 固定入口 symlink 通过独立 platform profile 解析到 Nix Store，而不是 Git working tree。
11. Agent credentials 和 mutable state 不受管理。
12. 未知目标冲突会在 activation 前使 apply 停止，现有文件不被修改。
13. Doctor 能按 domain 报告 not deployed、missing、drifted 和 local prerequisite 状态；apply 能报告 conflict。
14. System 和各 Agent platform manifest 只记录各自管理的文件系统资源，并且可重复生成。
15. System rollback 只在目标 generation 自带有效 manifest 时执行，不改变 Agent platforms。
16. 自动化测试不修改真实 `$HOME`。
17. `nix flake check` 通过。
18. README 包含 init、完整 apply、单 platform apply、新 Mac bootstrap、修改 rules、添加 local/external skill、更新第三方 source、处理 conflict、doctor 和 rollback 的操作说明。
19. 首次部署后 `dot` 位于 system PATH；首次部署前所有操作可通过 `nix run .#dot -- ...` 完成。

## 19. 后续演进候选

只有出现明确需求后才考虑：

- 经过独立安全设计和测试的 conflict backup/restore；
- activation journal 和 crash recovery；
- 更完整的 ownership inventory；
- package 和 service observer；
- canonical commands；
- Agent platform 的手工 generation rollback；
- 外部 adapter process protocol；
- declarative secrets；
- project-level Agent 配置；
- Linux 设备。

这些能力不得反向破坏 MVP 的核心边界：Nix 构建 immutable artifacts，各 deployment domain 有唯一 owner，compiler 保持纯净，managed targets 使用 allowlist，未知文件默认不修改。
