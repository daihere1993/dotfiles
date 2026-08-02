-- Markdown preview + inline Mermaid rendering.
-- Mermaid requires an external CLI: `bm` (recommended) or `mermaid-ascii`.
vim.pack.add {
  'https://github.com/MeanderingProgrammer/render-markdown.nvim',
  'https://github.com/cavanaug/render-markdown-mermaid.nvim',
}

require('render-markdown-mermaid').setup {
  placement = 'above',
  render_markdown = {
    -- Render in normal/visual mode; switch to raw text in insert mode for easier editing.
    modes = { 'n', 'c', 'v' },
    file_types = { 'markdown' },
  },
}

vim.keymap.set('n', '<leader>mp', '<cmd>RenderMarkdown buf_toggle<cr>', { desc = '[M]arkdown [P]review toggle' })
