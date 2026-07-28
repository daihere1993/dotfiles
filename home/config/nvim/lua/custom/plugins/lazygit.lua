-- lazygit.nvim: run lazygit in a floating window; reloads affected buffers on exit.
vim.pack.add { 'https://github.com/kdheepak/lazygit.nvim' }

vim.g.lazygit_floating_window_scaling_factor = 0.9
vim.g.lazygit_use_neovim_remote = 0

vim.keymap.set('n', '<leader>gg', '<cmd>LazyGit<cr>', { desc = '[G]it [G]ui (lazygit)' })
