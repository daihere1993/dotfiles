# Neovim 配置集成设计

## 目标

将当前 `/Users/zowu/.config/nvim` 的有效配置快照纳入 dotfiles。新购置的 Apple Silicon Mac 执行 `./bootstrap/install` 后，应获得可用的 Neovim、基础命令行依赖，以及一个受 Home Manager 管理、直接链接到 dotfiles 工作树（可写）的配置目录。首次启动 Neovim 时，插件管理器和工具管理器再下载可变的运行时组件。

本设计延续仓库现有边界：Nix 构建不可变产物，Home Manager 部署用户配置，`dot` 负责变更预览、冲突检查、激活和诊断。Neovim 配置目录是这个边界内一个有意的例外——它是可写的工作树链接，不是不可变快照，理由见下文"已确认的决策"。

## 已确认的决策

- 采用混合式依赖管理。
- Nix 管理 Neovim 和系统级依赖。
- `~/.config/nvim` 作为例外不进入 Nix Store 快照：Home Manager 用 `mkOutOfStoreSymlink` 把它直接链接到 dotfiles 工作树的 `nvim/`，配置可写、可直接编辑。
- 该例外放弃 nvim 配置内容的 generation 级回滚：`dot rollback` 只切换 `nvim.nix` 模块本身的声明（是否启用、依赖包版本），不改变 `nvim/` 的文件内容；内容层面的撤销用 `git revert`/`git checkout`。
- `dot apply` 会先把仓库归档进 Nix Store（`nix flake archive`）再求值，因此 Nix 表达式里的 `self`/`./.` 指向归档副本而不是工作树。`~/.config/nvim` 的链接目标必须使用归档前的原始仓库路径，这个路径需要作为独立参数传给 Nix 求值，不能复用现有的 `repository` 参数。
- `vim.pack` 管理插件，`nvim-pack-lock.json` 锁定插件 revision。
- Mason 管理 `lua-language-server` 和 `stylua`。
- Neovim Treesitter 管理 parser。
- bootstrap 不预热插件、Mason 工具或 parser；首次启动 Neovim 时下载它们。
- 首版只覆盖当前 Lua 开发能力，不增加其他语言工具链。
- dotfiles 只接收当前配置快照，不合并独立 Neovim 仓库的 Git 历史。
- 保留当前单文件 Kickstart 结构，不在迁移期间模块化重构。
- 部署前永久删除旧的 `/Users/zowu/.config/nvim`；不保留旧仓库备份。
- 规范文档只写入工作树，不在本阶段提交。

## 范围

### 纳入范围

- 安装与锁定 Neovim。
- 安装当前配置需要的系统级命令行工具。
- 通过 Home Manager 把 `~/.config/nvim` 链接到 dotfiles 工作树的 `nvim/`。
- 将 Neovim 配置加入 system manifest 和 `dot doctor`。
- 给 `dot` 的资源模型新增一种不做内容摘要比较的链接类型（`workspace-link`），用于表达"链接到工作树、可写、无 generation 级内容回滚"的资源。
- 跟踪并验证插件锁文件。
- 修正 `stylua` 被错误当作 LSP server 的现有配置。
- 为 Nix 构建、部署计划、诊断和真实首次启动增加验证。

### 不纳入范围

- Linux、Intel Mac 或 Windows。
- Go、Rust、Python、TypeScript、Nix、C/C++ 等额外语言环境。
- Nerd Font 安装。
- Neovim 配置模块化重构。
- 将插件、Mason 工具或 Treesitter parser 打包进 Nix Store。
- 导入独立 Neovim 仓库的提交历史、分支或 remote。
- 备份或恢复旧的 `/Users/zowu/.config/nvim`。
- 为 `dot` 增加通用的用户目录覆盖功能。

## 仓库结构

新增以下文件和模块：

```text
dotfiles/
├── nvim/
│   ├── init.lua
│   ├── nvim-pack-lock.json
│   ├── .stylua.toml
│   ├── LICENSE.md
│   └── lua/
│       ├── kickstart/
│       └── custom/
└── modules/home/
    └── neovim.nix
```

`modules/home/common.nix` 导入 `neovim.nix`。Neovim 模块只管理编辑器、直接依赖和配置部署；通用开发依赖继续留在 `development.nix`。

`modules/home/neovim.nix` 需要归档前的原始仓库路径才能构造指向工作树的符号链接目标。这个路径通过新增的 `--argstr liveRepositoryRoot` 从 `dot apply`（在调用 `archive_repository` 之前捕获的仓库路径）传给 `nix/cli-domain.nix`，再经 `specialArgs.dotfilesRoot` 注入 Home Manager 模块，与现有的 `--argstr repository`（归档后的 Nix Store 路径，仍用于求值和构建）分开。

迁移不包含以下独立仓库维护文件：

- `.git/`
- `.github/`
- 上游 `README.md`
- `doc/tags`
- 其他生成文件或上游协作模板

保留 `LICENSE.md`，明确配置的 Kickstart 来源和许可证。

## 所有权与数据边界

### Nix 和 Home Manager

Nix 与 Home Manager 管理：

- Neovim，最低兼容版本为 0.12；
- `ripgrep`；
- `fd`；
- `tree-sitter` CLI；
- GNU Make；
- `unzip`。

Git 已由现有 `programs.git` 提供。C 编译器使用 bootstrap 已检查的 Xcode Command Line Tools。首版沿用已有的 Node.js、Python 和 pnpm 声明，但不为 Neovim 增加新的 Node 或 Python 工具。当前配置没有引用系统 `fzf` 或 `jq`（模糊匹配由 `telescope-fzf-native.nvim` 这个用 `make` 编译的原生扩展提供），因此不纳入这份依赖清单；如果以后确实需要，应作为通用 shell 工具加进 `development.nix`，而不是算作 Neovim 的依赖。

### Neovim 配置目录（例外）

`~/.config/nvim` 不属于上面的"Nix 管不可变产物"模型。Home Manager 用 `config.lib.file.mkOutOfStoreSymlink` 把它直接链接到 dotfiles 工作树的 `nvim/` 目录，而不是先把 `nvim/` 拷进 Nix Store 再链接过去。这意味着：

- 编辑 `~/.config/nvim` 下的任意文件等价于直接编辑仓库工作树里的 `nvim/`；改动立即生效，不需要 `dot apply`。
- 这个链接目标必须是构建时归档前的原始仓库路径（见"已确认的决策"），不能用 Nix 表达式里的 `self`/`./.`——那指向的是 `dot apply` 归档出来的只读副本。
- 放弃这个目录的 generation 级回滚和内容漂移检测：`dot rollback` 切系统 generation 不会改变 `nvim/` 的文件内容，`dot doctor` 也不对它的内容做摘要比较（见"System manifest 与诊断"）。
- `vim.pack`/Mason/Treesitter 仍然只往 XDG data/cache/state 目录写可变数据，不会污染 `nvim/` 本身，因此不需要在 `nvim/.gitignore` 之外做额外隔离。

### Neovim 运行时

以下可变数据留在用户的 XDG data、cache 和 state 目录，不进入 dotfiles：

- `vim.pack` 下载的插件；
- Mason 下载的 LSP 和 formatter；
- Treesitter parser；
- 插件编译产物；
- 缓存、日志、shada 和会话状态。

删除这些运行时数据不会改变声明式配置。Neovim 可根据锁文件和工具清单重新创建它们。

## Home Manager 部署

`modules/home/neovim.nix` 使用 `programs.neovim.enable = true` 安装 Neovim。配置部署走另一条路径：

```nix
home.file.".config/nvim".source =
  config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/nvim";
```

`dotfilesRoot` 是"仓库结构"一节里说明的、归档前的原始工作树路径。Home Manager 激活时在 `~/.config/nvim` 处创建一个指向 `dotfilesRoot/nvim` 的符号链接（`mkOutOfStoreSymlink` 会先生成一个只包含这个符号链接的小型 Nix Store 派生，`~/.config/nvim` 链接到该派生，该派生再链接到工作树；`resource_conforms` 用 `Path.resolve()` 穿透这条链，最终解析到的还是工作树路径）。

配置是可写的：普通 Neovim 会话读写的就是仓库工作树里的 `nvim/`。这换来了"改配置不用等 apply"的即时反馈，代价是这份配置不再享有 Nix generation 的不可变性和回滚——`dot rollback` 切换的是链接本身是否存在（由 `nvim.nix` 模块声明决定），不是链接指向的内容。

系统构建必须拒绝低于 0.12 的 Neovim，因为当前配置依赖内置的 `vim.pack` API；这条约束不受部署机制变化的影响。

## System manifest 与诊断

`dot` 现有的 `directory-link`/`file-link` 都假定内容被拷进了 Nix Store，靠内容摘要（`sha256`/`directorySha256`）判断"漂移"。Neovim 配置的内容会随时被直接编辑，用同一套摘要比较会导致每次改完配置、还没跑 `dot apply` 之前，`dot doctor` 都会一直报 `DRIFTED`——这是预期中的正常状态，不该被当成需要修复的问题。因此需要给 `cli/dotfiles_cli/models.py` 的 `ResourceKind` 新增一种类型 `workspace-link`，语义是"符号链接必须存在，且最终解析到的真实路径等于声明的路径；不做内容比较"。

涉及的最小改动：

- `models.py`：`ResourceKind` 增加 `"workspace-link"`。
- `manifest.py`：`workspace-link` 仍要求 `linkTarget`/`storePath`（校验逻辑不变），但不要求 `sha256`/`directorySha256`。
- `conflict.py` 的 `resource_conforms`：为 `workspace-link` 增加一个分支——校验目标是符号链接、`resolve()` 后的真实路径与 `store_path` 一致、且解析结果是目录，通过即视为符合，不调用 `directory_sha256`。
- `conflict.py` 的 `ownership_overlaps`：把 `workspace-link` 和 `directory-link` 一样当作目录命名空间参与重叠检测，防止其他资源被声明到 `~/.config/nvim` 内部。

system manifest 增加的资源：

```text
id:        home.nvim.config
owner:     home-manager
kind:      workspace-link
target:    ~/.config/nvim
linkTarget: ${homeGeneration}/home-files/.config/nvim
storePath: ${dotfilesRoot}/nvim
sources:   nvim/、modules/home/neovim.nix
```

`storePath` 字段这里存的不是 Nix Store 路径，而是归档前的工作树里 `nvim/` 的绝对路径——字段复用现有 schema，语义上表示"这个资源最终应该解析到的真实路径"，其余资源里它才恰好总是 Nix Store 路径。

`dot apply --check` 应识别以下状态：

- 目标不存在：新增配置（首次创建符号链接）；
- 目标已经是指向 `dotfilesRoot/nvim` 的符号链接：无变化；
- 目标是指向别处或已废弃路径的符号链接：可替换；
- 用户拥有的目录或未知链接：阻塞冲突。

不再有"配置目录内容变化：更新 system domain"这一条——`nvim/` 的内容变化对这个资源的 apply 状态没有影响，只有 `nvim.nix` 模块本身的声明变化（比如启停、改依赖包）才会触发 apply。

`dot doctor` 对该资源只报告 `HEALTHY` 或 `MISSING`，不会报告 `DRIFTED`。

## 插件、LSP 与 formatter

### 插件

`vim.pack` 继续读取当前的插件声明。`nvim-pack-lock.json` 纳入 Git，保存每个启用插件的 source、version 约束和 revision。

迁移时清理锁文件：

- 每个启用插件必须有锁定项；
- 已停用且不再声明的插件必须从锁文件删除；
- 每个锁定项必须包含有效 source 和 revision；
- 锁文件必须是格式正确的 JSON。

首次启动时，`vim.pack` 将缺失插件按锁定 revision 下载到用户数据目录。现有 `PackChanged` hook 继续编译 Telescope FZF、LuaSnip jsregexp 和 Treesitter 组件。

### LSP 与 formatter

当前配置将 `stylua` 放在 `servers` 表中，并对表中每一项调用 `vim.lsp.enable()`。`stylua` 是 formatter，不是 LSP server。迁移时将职责改为：

```text
LSP servers: lua_ls
Mason tools: lua_ls、stylua
Conform:     lua -> stylua
```

保留现有保存行为：保存 Lua 文件时不自动格式化。用户通过 `<leader>f` 显式运行 Stylua。

## 首次启动流程

新电脑执行 `./bootstrap/install` 后，Home Manager 已部署 Neovim、系统依赖和配置。bootstrap 不访问插件源或 Mason registry。

用户首次启动 Neovim 时：

1. Neovim 读取配置和插件锁文件（配置目录本身可写，但首次启动不涉及编辑，读取到的内容跟已提交的仓库快照一致）。
2. `vim.pack` 下载缺失插件并执行构建 hook。
3. Mason 安装 `lua-language-server` 和 `stylua`。
4. Treesitter 安装基础 parser，并在以后打开新文件类型时按需安装 parser。
5. Neovim 显示安装进度或错误通知。

首次安装允许尚未就绪的功能暂时不可用，但主界面应能启动。安装完成后重启一次 Neovim，所有当前 Lua 功能应进入稳定状态。

网络失败只影响对应的运行时组件。修复网络后重新启动 Neovim 即可重试；`dot apply` 和 system generation 不受影响。

## 插件更新流程

不再需要单独的维护入口。因为 `~/.config/nvim` 本来就是仓库工作树的 `nvim/`，普通 Neovim 会话就是可写会话，`vim.pack.update()` 改的直接就是仓库文件。更新步骤为：

1. 正常打开 `nvim`。
2. 执行并确认 `vim.pack.update()`。
3. 检查 `git status`/`git diff` 里 `nvim/nvim-pack-lock.json` 的变化。
4. 运行仓库验证（Lua 语法检查、Stylua 格式检查、锁文件结构检查）。
5. 提交配置和锁文件变更。

锁文件变更立即对下一次 Neovim 启动生效，不需要 `dot apply`。只有当 `modules/home/neovim.nix` 本身发生变化时（比如新增系统依赖、切换 Neovim 版本）才需要跑 `dot apply`。

## 当前机器的切换流程

当前独立仓库只作为新配置的输入，不保留其历史或备份。实施必须按以下顺序执行：

1. 将有效配置复制到 dotfiles 的 `nvim/`。
2. 在 dotfiles 中完成 `stylua` 职责修正和锁文件清理。
3. 对 dotfiles 中的新配置运行静态、构建和隔离验证。
4. 比较源文件，确认新配置已完整进入 dotfiles。
5. 确认删除目标精确等于 `/Users/zowu/.config/nvim`，且不是未解析变量、glob、用户主目录或工作区根目录。
6. 永久删除 `/Users/zowu/.config/nvim`，包括其中的 `.git`。
7. 运行 `dot apply`。
8. 运行真实首次启动验证和 `dot doctor`。

删除操作不可恢复。实施阶段只能在前五步全部成功后执行它。

第 7 步 `dot apply` 完成后，`~/.config/nvim` 变成指向 `nvim/` 的符号链接，不再是独立目录——后续在 `~/.config/nvim` 里的任何编辑都是在编辑 dotfiles 工作树本身。

## 错误处理与回滚

### 声明式部署失败

Nix 构建、preflight 或 Home Manager 激活失败时，`dot apply` 返回失败，旧 system generation 保持可用。由于实施流程已永久删除旧 Neovim 目录，此时旧系统仍可使用，但旧 Neovim 配置不会自动恢复。删除旧独立仓库后，回滚范围只包含 dotfiles 管理的 generation。

### 首次下载失败

插件、Mason 工具或 parser 下载失败时，Neovim 报告具体组件和错误。用户修复网络后重启 Neovim 即可重试。系统配置无需回滚。

### 原生插件构建失败

单个原生组件构建失败时，相关扩展可以降级或保持不可用，但 Neovim 主界面应继续启动。现有 hook 应给出包含插件名和构建命令的通知。

### 配置升级失败

`dot rollback` 切回上一 system generation 只影响 `nvim.nix` 模块本身声明的内容（Neovim 版本、系统依赖包、链接是否存在），不影响 `nvim/` 里的文件——因为链接目标固定指向工作树，跟哪个 generation 生效无关。如果某次编辑把 Neovim 配置改坏了，恢复手段是仓库内的 `git revert`/`git checkout`，不是 `dot rollback`。这是"配置放弃 generation 级回滚"这条决策的直接后果，需要在用户文档里说清楚，避免以后遇到坏配置时误以为 `dot rollback` 能救回来。首次接管前的独立仓库不在任何回滚范围内。

## 验证策略

### 静态验证

- 使用 Lua 语法检查覆盖 `nvim/**/*.lua`。
- 使用 nixpkgs 中的 Stylua 对配置执行格式检查；Stylua 只作为构建检查依赖，不改变运行时由 Mason 管理 Stylua 的决策。
- 解析 `nvim-pack-lock.json`，检查 JSON 结构、source 和 revision。
- 用一份显式的预期插件清单比较启用插件与锁文件，防止缺项和遗留项。
- 检查 Neovim 包版本不低于 0.12。
- 运行 Nix 格式检查、Ruff、ShellCheck 和现有 Python 测试。

### Nix 与 CLI 测试

- `nix flake check` 构建两套测试用户的 nix-darwin/Home Manager generation。
- system manifest 测试断言 `home.nvim.config` 存在、`kind` 为 `workspace-link`，且 `storePath` 等于传入的 `dotfilesRoot/nvim`（不以 `/nix/store/` 开头）。
- `conflict.py` 单元测试覆盖 `workspace-link` 的 `resource_conforms`：链接指向正确目录时判定为符合；修改 `nvim/` 里任意文件内容后仍判定为符合（验证确实不做内容比较）；链接缺失、指向别处、目标被替换为普通目录时判定为不符合。
- `ownership_overlaps` 测试验证不能有其他资源声明在 `~/.config/nvim` 内部。
- manifest 校验测试验证 `workspace-link` 不要求 `sha256`/`directorySha256`。
- planning 测试覆盖新增、无变化、可替换和用户目录冲突（不再有"内容变化"这一分类）。
- doctor 测试覆盖 `HEALTHY` 和 `MISSING`；显式断言不会出现 `DRIFTED`。
- 回滚测试验证：`dot rollback` 切换 system generation 后，符号链接依然存在且指向同一个工作树路径；`nvim/` 的文件内容不随 generation 变化（把这一点写成断言，防止将来被误当作缺陷修复掉）。
- 新增一个测试验证归档前的原始仓库路径被正确当作 `dotfilesRoot` 传入 Nix 求值，而不是被 `archive_repository` 后的 Nix Store 路径覆盖。

### 真实 E2E 验证

首次 apply 后执行：

1. `nvim --version`，确认版本不低于 0.12。
2. 启动 Neovim，等待插件、Mason 工具和基础 parser 安装结束。
3. 重启 Neovim 并打开 `nvim/init.lua`。
4. 确认 `lua_ls` 附加到 buffer。
5. 确认补全、Telescope、Neo-tree、Gitsigns 和 Treesitter 可用。
6. 通过 `<leader>f` 确认 Stylua 可用。
7. 运行 `:checkhealth kickstart` 和 `:checkhealth mason`。
8. 运行 `dot doctor`，确认 `home.nvim.config` 为 `HEALTHY`。
9. 在 `~/.config/nvim/init.lua` 里追加一行注释并保存，确认这个改动出现在 dotfiles 仓库 `nvim/init.lua` 的 `git diff` 里，然后撤销这次编辑，验证它确实是工作树的符号链接而不是只读快照。
10. 执行 `vim.pack.update(nil, { offline = true })`，确认 `git status` 能看到 `nvim/nvim-pack-lock.json` 的 diff，且这个变化没有触发 `dot doctor` 报告 `DRIFTED`。

## 完成标准

满足以下条件时，首版迁移完成：

- `/Users/zowu/.config/nvim` 的有效配置已进入 dotfiles，独立仓库已删除。
- Neovim 和基础依赖由 flake 锁定的 nixpkgs 提供。
- `dot apply --check` 能预览 Neovim 配置变化。
- `dot apply` 能在目标不存在时部署 `~/.config/nvim`。
- `dot doctor` 能诊断 Neovim 配置链接缺失，且不会把正常的内容编辑误报为漂移。
- `dot` 新增的 `workspace-link` 资源类型通过 manifest 校验、冲突分类、诊断和回滚测试。
- 新电脑执行 `./bootstrap/install` 后无需手动安装 Neovim 或基础依赖。
- 首次联网启动能安装锁定插件、Lua 工具和 parser。
- 第二次启动能稳定使用当前 Lua 编辑能力。
- 插件更新可以直接在 `~/.config/nvim`（即工作树 `nvim/`）完成并立即生效，不需要维护入口，也不需要 `dot apply`；锁文件变更通过正常 `git commit` 记录。
- `nix flake check`、仓库测试和真实 E2E 验证全部通过。
