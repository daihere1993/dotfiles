local wezterm = require("wezterm")
local act = wezterm.action

local config = wezterm.config_builder()

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
