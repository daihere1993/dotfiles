-- Neo-tree is a Neovim plugin to browse the file system
-- https://github.com/nvim-neo-tree/neo-tree.nvim

vim.pack.add {
  { src = 'https://github.com/nvim-neo-tree/neo-tree.nvim', version = vim.version.range '*' },
  'https://github.com/nvim-lua/plenary.nvim',
  'https://github.com/MunifTanjim/nui.nvim',
}

vim.keymap.set('n', '\\', '<Cmd>Neotree reveal<CR>', { desc = 'NeoTree reveal', silent = true })

local file_ignore = require 'custom.file_ignore'

require('neo-tree').setup {
  filesystem = {
    filtered_items = file_ignore.neo_tree_filtered_items(),
    window = {
      mappings = {
        ['\\'] = 'close_window',
      },
    },
  },
}
