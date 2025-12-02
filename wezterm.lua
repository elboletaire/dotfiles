-- Pull in the wezterm API
local wezterm = require 'wezterm'

-- This will hold the configuration.
local config = wezterm.config_builder()

-- This is where you actually apply your config choices.

-- For example, changing the initial geometry for new windows:
config.initial_cols = 130
config.initial_rows = 35

-- Change scrollback
config.scrollback_lines = 10000

-- or, changing the font size and color scheme.
config.font_size = 10
config.color_scheme = 'Monokai Pro (Gogh)'

config.window_frame = {
  active_titlebar_bg = "#161517",
  inactive_titlebar_bg = "#363537"
}

-- open in same window as new tab
config.prefer_to_spawn_tabs = true

-- Finally, return the configuration to wezterm:
return config
