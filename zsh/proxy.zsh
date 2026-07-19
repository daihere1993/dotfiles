# Proxy setup for zsh. Sourcing this file only defines helpers and commands.

PROXY_NETWORK_SERVICE="Wi-Fi"
PROXY_NO_PROXY="localhost,127.0.0.1,localaddress,.localdomain.com"

haitunwan_proxy="http://127.0.0.1:4780"
clash_proxy="http://127.0.0.1:7897"

VSCODE_SETTINGS_FILE="$HOME/Library/Application Support/Code/User/settings.json"
CURSOR_SETTINGS_FILE="$HOME/Library/Application Support/Cursor/User/settings.json"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  PROXY_COLOR_RESET=$'\033[0m'
  PROXY_COLOR_INFO=$'\033[36m'
  PROXY_COLOR_OK=$'\033[32m'
  PROXY_COLOR_WARN=$'\033[33m'
  PROXY_COLOR_ERROR=$'\033[31m'
else
  PROXY_COLOR_RESET=''
  PROXY_COLOR_INFO=''
  PROXY_COLOR_OK=''
  PROXY_COLOR_WARN=''
  PROXY_COLOR_ERROR=''
fi

_proxy_log() {
  local level="$1"
  local color="$2"
  local message="$3"
  printf '%b[%s]%b %s\n' "$color" "$level" "$PROXY_COLOR_RESET" "$message"
}

_proxy_info() { _proxy_log "INFO" "$PROXY_COLOR_INFO" "$1"; }
_proxy_ok() { _proxy_log "OK" "$PROXY_COLOR_OK" "$1"; }
_proxy_warn() { _proxy_log "WARN" "$PROXY_COLOR_WARN" "$1"; }
_proxy_error() { _proxy_log "ERROR" "$PROXY_COLOR_ERROR" "$1" >&2; }

_set_terminal_proxy() {
  local proxy_url="$1"
  export no_proxy="$PROXY_NO_PROXY"
  export http_proxy="$proxy_url"
  export https_proxy="$proxy_url"
  _proxy_ok "Terminal proxy set to $proxy_url"
}

_clear_terminal_proxy() {
  unset http_proxy https_proxy all_proxy
  _proxy_ok "Terminal proxy variables cleared"
}

_set_network_http_proxy() {
  local host="$1"
  local port="$2"
  if ! /usr/sbin/networksetup -setwebproxy "$PROXY_NETWORK_SERVICE" "$host" "$port"; then
    _proxy_error "Failed to set the macOS HTTP proxy"
    return 1
  fi
  if ! /usr/sbin/networksetup -setsecurewebproxy "$PROXY_NETWORK_SERVICE" "$host" "$port"; then
    _proxy_error "Failed to set the macOS HTTPS proxy"
    return 1
  fi
  _proxy_ok "macOS HTTP/HTTPS proxy set to $host:$port on $PROXY_NETWORK_SERVICE"
}

_clear_network_http_proxy() {
  if ! /usr/sbin/networksetup -setwebproxystate "$PROXY_NETWORK_SERVICE" off; then
    _proxy_error "Failed to disable the macOS HTTP proxy"
    return 1
  fi
  if ! /usr/sbin/networksetup -setsecurewebproxystate "$PROXY_NETWORK_SERVICE" off; then
    _proxy_error "Failed to disable the macOS HTTPS proxy"
    return 1
  fi
  _proxy_ok "macOS HTTP/HTTPS proxy disabled on $PROXY_NETWORK_SERVICE"
}

_set_network_socks_proxy() {
  local host="$1"
  local port="$2"
  if ! /usr/sbin/networksetup -setsocksfirewallproxy "$PROXY_NETWORK_SERVICE" "$host" "$port"; then
    _proxy_error "Failed to set the macOS SOCKS proxy"
    return 1
  fi
  _proxy_ok "macOS SOCKS proxy set to $host:$port on $PROXY_NETWORK_SERVICE"
}

_clear_network_socks_proxy() {
  if ! /usr/sbin/networksetup -setsocksfirewallproxystate "$PROXY_NETWORK_SERVICE" off; then
    _proxy_error "Failed to disable the macOS SOCKS proxy"
    return 1
  fi
  _proxy_ok "macOS SOCKS proxy disabled on $PROXY_NETWORK_SERVICE"
}

_clear_network_bypass_domains() {
  if ! /usr/sbin/networksetup -setproxybypassdomains "$PROXY_NETWORK_SERVICE" ""; then
    _proxy_error "Failed to clear macOS proxy bypass domains"
    return 1
  fi
  _proxy_ok "macOS proxy bypass domains cleared on $PROXY_NETWORK_SERVICE"
}

_ensure_valid_json_file() {
  local settings_file="$1"

  if [[ ! -s "$settings_file" ]] || ! jq empty "$settings_file" >/dev/null 2>&1; then
    _proxy_warn "Invalid or empty JSON in $settings_file. Reinitializing to {}."
    if ! printf '{}\n' > "$settings_file"; then
      _proxy_error "Failed to initialize editor settings JSON"
      return 1
    fi
  fi
}

_update_editor_proxy() {
  local editor_name="$1"
  local settings_file="$2"
  local action="${3:-enable}"
  local proxy_url="${4:-${http_proxy:-}}"
  local temp_file

  if [[ ! -f "$settings_file" ]]; then
    _proxy_warn "$editor_name settings not found: $settings_file"
    return 0
  fi

  if ! command -v jq >/dev/null 2>&1; then
    _proxy_error "jq is unavailable; failed to update $editor_name proxy settings"
    return 1
  fi

  if ! /bin/cp "$settings_file" "$settings_file.bak"; then
    _proxy_error "Failed to back up $editor_name settings"
    return 1
  fi
  _ensure_valid_json_file "$settings_file" || return 1

  if ! temp_file="$(/usr/bin/mktemp)"; then
    _proxy_error "Failed to create a temporary file for $editor_name settings"
    return 1
  fi

  if [[ "$action" == "enable" ]]; then
    if ! jq --arg proxy "$proxy_url" '. ["http.proxy"] = $proxy' "$settings_file" > "$temp_file"; then
      /bin/rm -f "$temp_file"
      _proxy_error "Failed to update $editor_name proxy settings"
      return 1
    fi
  else
    if ! jq 'del(. ["http.proxy"])' "$settings_file" > "$temp_file"; then
      /bin/rm -f "$temp_file"
      _proxy_error "Failed to clear $editor_name proxy settings"
      return 1
    fi
  fi

  if ! /bin/mv "$temp_file" "$settings_file"; then
    /bin/rm -f "$temp_file"
    _proxy_error "Failed to replace $editor_name settings"
    return 1
  fi

  if [[ "$action" == "enable" ]]; then
    _proxy_ok "$editor_name proxy enabled ($proxy_url)"
  else
    _proxy_ok "$editor_name proxy cleared"
  fi
}

_set_npm_proxy() {
  if ! command -v npm >/dev/null 2>&1; then
    _proxy_error "npm is unavailable; failed to configure its proxy"
    return 1
  fi
  if ! npm config set proxy "$http_proxy" >/dev/null; then
    _proxy_error "Failed to set the npm HTTP proxy"
    return 1
  fi
  if ! npm config set https-proxy "$http_proxy" >/dev/null; then
    _proxy_error "Failed to set the npm HTTPS proxy"
    return 1
  fi
  _proxy_ok "npm proxy configured"
}

_clear_npm_proxy() {
  if ! command -v npm >/dev/null 2>&1; then
    _proxy_error "npm is unavailable; failed to clear its proxy"
    return 1
  fi
  if ! npm config delete proxy >/dev/null; then
    _proxy_error "Failed to clear the npm HTTP proxy"
    return 1
  fi
  if ! npm config delete https-proxy >/dev/null; then
    _proxy_error "Failed to clear the npm HTTPS proxy"
    return 1
  fi
  _proxy_ok "npm proxy cleared"
}

_set_pnpm_proxy() {
  if ! command -v pnpm >/dev/null 2>&1; then
    _proxy_error "pnpm is unavailable; failed to configure its proxy"
    return 1
  fi
  if ! pnpm config set proxy "$http_proxy" >/dev/null; then
    _proxy_error "Failed to set the pnpm HTTP proxy"
    return 1
  fi
  if ! pnpm config set https-proxy "$http_proxy" >/dev/null; then
    _proxy_error "Failed to set the pnpm HTTPS proxy"
    return 1
  fi
  _proxy_ok "pnpm proxy configured"
}

_clear_pnpm_proxy() {
  if ! command -v pnpm >/dev/null 2>&1; then
    _proxy_error "pnpm is unavailable; failed to clear its proxy"
    return 1
  fi
  if ! pnpm config delete proxy >/dev/null; then
    _proxy_error "Failed to clear the pnpm HTTP proxy"
    return 1
  fi
  if ! pnpm config delete https-proxy >/dev/null; then
    _proxy_error "Failed to clear the pnpm HTTPS proxy"
    return 1
  fi
  _proxy_ok "pnpm proxy cleared"
}

_set_git_proxy() {
  if ! git config --global http.proxy "$http_proxy"; then
    _proxy_error "Failed to set the Git HTTP proxy"
    return 1
  fi
  if ! git config --global https.proxy "$http_proxy"; then
    _proxy_error "Failed to set the Git HTTPS proxy"
    return 1
  fi
  _proxy_ok "git proxy configured"
}

_clear_git_proxy_value() {
  local key="$1"
  local command_status

  if git config --global --get-all "$key" >/dev/null 2>&1; then
    command_status=0
  else
    command_status=$?
  fi
  if (( command_status == 1 )); then
    return 0
  fi
  if (( command_status != 0 )); then
    _proxy_error "Failed to inspect the Git $key setting"
    return 1
  fi
  if ! git config --global --unset-all "$key"; then
    _proxy_error "Failed to clear the Git $key setting"
    return 1
  fi
}

_clear_git_proxy() {
  _clear_git_proxy_value http.proxy || return 1
  _clear_git_proxy_value https.proxy || return 1
  _proxy_ok "git proxy cleared"
}

_set_cli_proxies() {
  _set_npm_proxy || return 1
  _set_pnpm_proxy || return 1
  _set_git_proxy || return 1
}

_clear_cli_proxies() {
  _clear_npm_proxy || return 1
  _clear_pnpm_proxy || return 1
  _clear_git_proxy || return 1
}

_clear_editor_proxies() {
  _update_editor_proxy "VS Code" "$VSCODE_SETTINGS_FILE" clear || return 1
  _update_editor_proxy "Cursor" "$CURSOR_SETTINGS_FILE" clear || return 1
}

disable_socks_proxy() {
  _clear_network_socks_proxy
}

haitunwan_proxy_on() {
  _proxy_info "Enabling Haitunwan proxy profile"
  _set_terminal_proxy "$haitunwan_proxy" || return 1
  export all_proxy="socks5://127.0.0.1:4781"
  _proxy_ok "Terminal SOCKS proxy set to $all_proxy"
  _set_network_http_proxy "127.0.0.1" "4780" || return 1
  _set_network_socks_proxy "127.0.0.1" "4781" || return 1
  _clear_network_bypass_domains || return 1
  _set_cli_proxies || return 1
  _update_editor_proxy "VS Code" "$VSCODE_SETTINGS_FILE" enable || return 1
  _update_editor_proxy "Cursor" "$CURSOR_SETTINGS_FILE" enable || return 1
  _proxy_ok "Haitunwan proxy is ON"
}

clash_proxy_on() {
  _proxy_info "Enabling Clash proxy profile"
  _set_terminal_proxy "$clash_proxy" || return 1
  unset all_proxy
  _proxy_ok "Terminal SOCKS proxy cleared"
  _set_network_http_proxy "127.0.0.1" "7897" || return 1
  _clear_network_bypass_domains || return 1
  _set_cli_proxies || return 1
  _update_editor_proxy "VS Code" "$VSCODE_SETTINGS_FILE" enable || return 1
  _update_editor_proxy "Cursor" "$CURSOR_SETTINGS_FILE" enable || return 1
  _proxy_ok "Clash proxy is ON"
}

proxy_off() {
  _proxy_info "Disabling all proxy settings"
  _clear_terminal_proxy || return 1
  _clear_editor_proxies || return 1
  _clear_cli_proxies || return 1
  _clear_network_bypass_domains || return 1
  _clear_network_socks_proxy || return 1
  _clear_network_http_proxy || return 1
  _proxy_ok "Proxy is OFF"
}
