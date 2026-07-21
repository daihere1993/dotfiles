local wezterm = require("wezterm")
local act = wezterm.action

local config = wezterm.config_builder()

local smart_paste_dir = (os.getenv("TMPDIR") or "/tmp") .. "/wezterm-clipboard-images"

local function clipboard_has_image()
  local success, stdout = wezterm.run_child_process({
    "/usr/bin/osascript",
    "-e",
    "clipboard info",
  })

  return success
    and stdout ~= nil
    and (stdout:find("PNGf", 1, true) ~= nil
      or stdout:find("TIFF", 1, true) ~= nil
      or stdout:find("JPEG", 1, true) ~= nil)
end

local function save_clipboard_image()
  local created = wezterm.run_child_process({ "/bin/mkdir", "-p", smart_paste_dir })
  if not created then
    return nil
  end

  local success, path = wezterm.run_child_process({
    "/usr/bin/mktemp",
    smart_paste_dir .. "/paste-XXXXXX.png",
  })
  if not success or path == nil then
    return nil
  end

  path = path:gsub("[\r\n]+$", "")
  local script = [[
on run argv
  set imagePath to POSIX file (item 1 of argv)
  set imageData to the clipboard as «class PNGf»
  set fileRef to open for access imagePath with write permission
  try
    set eof fileRef to 0
    write imageData to fileRef
    close access fileRef
  on error errorMessage number errorNumber
    close access fileRef
    error errorMessage number errorNumber
  end try
end run
]]
  local saved = wezterm.run_child_process({
    "/usr/bin/osascript",
    "-e",
    script,
    path,
  })
  if saved then
    return path
  end

  os.remove(path)
  return nil
end

config.color_scheme = "rose-pine-moon"
config.font = wezterm.font_with_fallback({
  { family = "Hack Nerd Font" },
  { family = "Sarasa Gothic SC" },
})
config.font_size = 15.0
config.window_background_opacity = 0.8
config.macos_window_background_blur = 50
config.hide_tab_bar_if_only_one_tab = true
config.window_decorations = "RESIZE"
-- Point units keep this calibration stable across standard and Retina scaling.
config.window_padding = {
  left = "10pt",
  right = "10pt",
  top = "14.5pt",
  bottom = "15pt",
}

-- Let Cmd+Q quit immediately instead of opening WezTerm's confirmation overlay.
config.window_close_confirmation = "NeverPrompt"

-- macOS-style line navigation in the shell (Ctrl+a / Ctrl+e).
config.keys = {
  { key = "LeftArrow", mods = "SUPER", action = act.SendKey({ key = "a", mods = "CTRL" }) },
  { key = "RightArrow", mods = "SUPER", action = act.SendKey({ key = "e", mods = "CTRL" }) },
  { key = "Backspace", mods = "SUPER", action = act.SendKey({ key = "u", mods = "CTRL" }) },
  {
    key = "v",
    mods = "SUPER",
    action = wezterm.action_callback(function(window, pane)
      if not clipboard_has_image() then
        window:perform_action(act.PasteFrom("Clipboard"), pane)
        return
      end

      local path = save_clipboard_image()
      if path then
        pane:send_paste(path)
        window:toast_notification("Smart Paste", "Image saved: " .. path, nil, 3000)
        return
      end

      window:toast_notification("Smart Paste", "Could not save clipboard image", nil, 3000)
      window:perform_action(act.PasteFrom("Clipboard"), pane)
    end),
  },
  {
    key = "k",
    mods = "SUPER",
    action = act.Multiple({
      act.ClearScrollback("ScrollbackAndViewport"),
      act.SendKey({ key = "L", mods = "CTRL" }),
    }),
  },
}

-- These logical dimensions match the initial outer window size for the font and
-- window settings above. Supplying the position to spawn_window places the first
-- frame correctly and avoids a visible jump from macOS's default position.
local initial_window_width = 1100
local initial_window_height = 660
local initial_window_cols = 120
local initial_window_rows = 36

-- Center the initial window on the display active when WezTerm launches.
wezterm.on("gui-startup", function(cmd)
  local screen = wezterm.gui.screens().active
  local scale = screen.scale or 1
  local spawn = cmd or {}

  -- WezTerm sizes new windows in terminal cells; these values are calibrated
  -- with the configured font to produce the logical outer dimensions above.
  spawn.width = initial_window_cols
  spawn.height = initial_window_rows
  spawn.position = {
    x = math.floor((screen.width - initial_window_width * scale) / 2),
    y = math.floor((screen.height - initial_window_height * scale) / 2),
    origin = "ActiveScreen",
  }

  wezterm.mux.spawn_window(spawn)
end)

return config
